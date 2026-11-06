"""Ciclo 2: dataset sintético tipo VIVO con sesgo inyectado.

Criterios:
  C1  600 filas, sin nulos en columnas obligatorias, valores en rango
  C2  Misma semilla -> archivos idénticos (mismo hash) en dos corridas
  C3  Tasa de deserción entre 20% y 30%
  C4  Correlación negativa entre asistencia promedio y deserción
  C5  SD del ruido de asistencia en mujer + vespertina >= 1,5 x la del resto
  C6  Sin RUT y sin correos con dominios reales
  C7  estudiantes_demo.csv: 12 filas (3 bajo, 4 medio, 5 alto) + caso sesgado mal marcado por el ingenuo
  C8  La fórmula de deserción no recibe variables demográficas y la vespertina deserta más
  C9  checkin_texto en ~30% de los estudiantes, con textos variados
  C10 data/README_datos.md documenta el sesgo
"""
from __future__ import annotations

import hashlib
import inspect
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config, generar_datos as g  # noqa: E402

ARCHIVOS = ("estudiantes.csv", "estudiantes_demo.csv", "README_datos.md")
RE_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
RE_CORREO = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def c1_estructura(est: pd.DataFrame) -> None:
    errores = []
    if len(est) != 600:
        errores.append(f"{len(est)} filas")
    faltan = [c for c in g.COLUMNAS_ESTUDIANTES if c not in est.columns]
    if faltan:
        errores.append(f"faltan columnas {faltan}")
    nulos = est[[c for c in g.COLUMNAS_OBLIGATORIAS if c in est.columns]].isna().sum()
    if nulos.any():
        errores.append(f"nulos: {nulos[nulos > 0].to_dict()}")
    asis = est[list(config.COLS_ASISTENCIA)]
    if not ((asis >= 0) & (asis <= 100)).all().all():
        errores.append("asistencia fuera de 0-100")
    notas = est[list(config.COLS_NOTAS)]
    if not ((notas >= 1.0) & (notas <= 7.0)).all().all():
        errores.append("notas fuera de 1,0-7,0")
    dominios = {
        "jornada": {"diurna", "vespertina"}, "genero": {"F", "M", "otro"},
        "trabaja": {"sí", "no"}, "deserto": {0, 1},
    }
    for col, validos in dominios.items():
        extra = set(est[col].unique()) - validos
        if extra:
            errores.append(f"{col} con valores {extra}")
    if est["carrera"].nunique() != 4:
        errores.append(f"{est['carrera'].nunique()} carreras")
    if est["sede"].nunique() != 2:
        errores.append(f"{est['sede'].nunique()} sedes")
    esperados = [f"EST-{i:04d}" for i in range(1, 601)]
    if est["id_seudonimo"].tolist() != esperados:
        errores.append("id_seudonimo no es EST-0001..EST-0600")
    record("C1 600 filas, sin nulos, valores en rango", not errores, "; ".join(errores) or "ok")


def c2_reproducible() -> None:
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        g.generar_todo(destino=Path(a))
        g.generar_todo(destino=Path(b))
        distintos = [f for f in ARCHIVOS if sha(Path(a) / f) != sha(Path(b) / f)]
        igual_a_data = all(sha(Path(a) / f) == sha(config.DATA_DIR / f) for f in ARCHIVOS)
    record("C2 Misma semilla -> mismo hash", not distintos and igual_a_data,
           f"distintos={distintos or 'ninguno'}, data/ coincide={igual_a_data}")


def c3_tasa(est: pd.DataFrame) -> None:
    tasa = est["deserto"].mean()
    record("C3 Tasa de deserción 20-30%", 0.20 <= tasa <= 0.30, f"{tasa:.1%}")


def c4_correlacion(est: pd.DataFrame) -> None:
    corr = est[list(config.COLS_ASISTENCIA)].mean(axis=1).corr(est["deserto"])
    record("C4 Corr(asistencia promedio, deserción) < 0", corr < 0, f"r = {corr:.3f}")


def c5_ruido(ds: g.Dataset) -> None:
    ruido = ds.latentes.attrs["ruido_efectivo"]
    sub = ds.latentes["subgrupo_sesgo"].to_numpy()
    # el subgrupo debe ser exactamente mujer + vespertina según el export
    est = ds.estudiantes
    coincide = bool(((est["genero"] == "F") & (est["jornada"] == "vespertina")).to_numpy().tolist() == sub.tolist())
    sd_sub, sd_resto = ruido[sub].std(), ruido[~sub].std()
    razon = sd_sub / sd_resto
    record("C5 SD ruido mujer+vespertina >= 1,5x resto", razon >= 1.5 and coincide,
           f"{sd_sub:.2f} vs {sd_resto:.2f} pp (x{razon:.2f}), n subgrupo={sub.sum()}, subgrupo correcto={coincide}")


def c6_privacidad(est: pd.DataFrame, demo: pd.DataFrame) -> None:
    textos = [str(v) for df in (est, demo) for v in df.to_numpy().ravel()]
    ruts = [t for t in textos if RE_RUT.search(t)]
    dominios = {m.group(1).lower() for t in textos for m in RE_CORREO.finditer(t)}
    reales = dominios - {config.DOMINIO_CORREO_FICTICIO}
    todos_ficticios = est["correo_ficticio"].str.endswith("@" + config.DOMINIO_CORREO_FICTICIO).all()
    ok = not ruts and not reales and todos_ficticios
    record("C6 Sin RUT ni correos con dominios reales", ok,
           f"RUT={len(ruts)}, dominios={sorted(dominios)}")


def c7_demo(demo: pd.DataFrame) -> None:
    dist = demo["nivel_esperado"].value_counts().to_dict()
    orden = {"bajo": 0, "medio": 1, "alto": 2}
    sesgados = demo[(demo["caso_sesgo"]) & (demo["genero"] == "F") & (demo["jornada"] == "vespertina")
                    & (demo["nivel_ingenuo"].map(orden) > demo["nivel_esperado"].map(orden))]
    historias = demo["nota_demo"].fillna("").str.len().gt(20).all()
    ok = len(demo) == 12 and dist == g.DISTRIBUCION_DEMO and len(sesgados) >= 1 and historias
    record("C7 Demo: 12 casos 3/4/5 + caso sesgado", ok,
           f"filas={len(demo)}, distribución={dist}, casos sesgados mal marcados={len(sesgados)}, historias={historias}")


def c8_formula(est: pd.DataFrame) -> None:
    params = set(inspect.signature(g._prob_desercion).parameters)
    sin_demograficas = not (params & set(config.VARIABLES_PROHIBIDAS))
    tasas = est.groupby("jornada")["deserto"].mean()
    ok = sin_demograficas and tasas["vespertina"] > tasas["diurna"]
    record("C8 Deserción por conducta; vespertina deserta más", ok,
           f"parámetros={sorted(params)}, vesp={tasas['vespertina']:.1%}, diurna={tasas['diurna']:.1%}")


def c9_checkin(est: pd.DataFrame) -> None:
    txt = est["checkin_texto"].fillna("")
    frac = (txt.str.len() > 0).mean()
    distintos = txt[txt.str.len() > 0].nunique()
    record("C9 checkin_texto ~30% y variado", 0.25 <= frac <= 0.35 and distintos >= 30,
           f"{frac:.1%} con texto, {distintos} textos distintos")


def c10_readme() -> None:
    p = config.RUTA_README_DATOS
    txt = p.read_text(encoding="utf-8") if p.is_file() else ""
    ok = "mujer + vespertina" in txt and "Sesgo inyectado" in txt
    record("C10 README_datos.md documenta el sesgo", ok, "ok" if ok else "falta o incompleto")


def main() -> int:
    print("== Ciclo 2: dataset sintético con sesgo ==")
    g.generar_todo()  # regenera data/ con la semilla fija
    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    demo = pd.read_csv(config.RUTA_DEMO, encoding="utf-8")
    ds = g.generar_dataset()
    c1_estructura(est)
    c2_reproducible()
    c3_tasa(est)
    c4_correlacion(est)
    c5_ruido(ds)
    c6_privacidad(est, demo)
    c7_demo(demo)
    c8_formula(est)
    c9_checkin(est)
    c10_readme()
    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo 2: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
