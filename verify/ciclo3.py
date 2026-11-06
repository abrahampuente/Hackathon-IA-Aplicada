"""Ciclo 3: modelo de riesgo explicable + auditoría de sesgos.

Criterios:
  C1  AUC en test >= 0,75 (modelo de producción guardado en data/modelo.pkl)
  C2  Ninguna variable demográfica/identificadora entre las features
  C3  explicar() da % en 0-100 y exactamente 3 razones legibles para 5 IDs al azar
  C4  auditoria.json tiene métricas por grupo antes y después de mitigar
  C5  Brecha de FP del subgrupo sesgado menor después que antes
  C6  Mismos datos -> mismas predicciones
  C7  nivel() respeta los umbrales de config
  C8  Artefactos: modelo.pkl, metricas.json; disparidad evaluada por variable
  C9  La bandera dato_asistencia_poco_confiable se informa pero no entra al modelo
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_demo  # noqa: E402
from src import config, modelo  # noqa: E402

PROHIBIDAS = {"genero", "jornada", "sede", "trabaja", "carrera", "nombre_ficticio", "correo_ficticio"}
GRUPOS = ("genero", "jornada", "sede", "trabaja")
METRICAS = ("tasa_alerta", "tasa_fp", "recall")

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def c1_auc(m: modelo.ModeloRiesgo) -> None:
    auc = m.metricas.get("auc_test", 0.0)
    record("C1 AUC test >= 0,75", auc >= 0.75, f"AUC test = {auc:.3f} (n_test={m.metricas.get('n_test')})")


def c2_features(m: modelo.ModeloRiesgo) -> None:
    usadas = set(m.features) | set(config.FEATURES_BASE) | set(config.FEATURES_ROBUSTAS)
    cruce = usadas & PROHIBIDAS
    try:
        modelo.validar_features(["asistencia_mediana", "genero"])
        guardia = False
    except ValueError:
        guardia = True
    record("C2 Sin variables prohibidas en features", not cruce and guardia,
           f"features={list(m.features)}; cruce={sorted(cruce) or 'ninguno'}; validar_features rechaza genero={guardia}")


def _legible(r: str) -> bool:
    return (isinstance(r, str) and len(r) > 15 and r[0].isupper() and r.endswith(").")
            and "_" not in r and ("(sube el riesgo)" in r or "(baja el riesgo)" in r))


def c3_explicar(m: modelo.ModeloRiesgo, est: pd.DataFrame) -> None:
    ids = random.sample(est["id_seudonimo"].tolist(), 5)
    problemas = []
    for i in ids:
        e = modelo.explicar(i, m, est)
        if not 0 <= e["riesgo_pct"] <= 100:
            problemas.append(f"{i}: riesgo {e['riesgo_pct']}")
        if len(e["razones"]) != 3 or not all(_legible(r) for r in e["razones"]):
            problemas.append(f"{i}: razones {e['razones']}")
        if e["nivel"] != modelo.nivel(e["riesgo_pct"]):
            problemas.append(f"{i}: nivel inconsistente")
    ejemplo = modelo.explicar(ids[0], m, est)
    print(f"      ejemplo {ids[0]}: {ejemplo['riesgo_pct']}% ({ejemplo['nivel']}) -> {ejemplo['razones']}")
    record("C3 explicar(): % 0-100 y 3 razones legibles", not problemas,
           "; ".join(problemas) or f"IDs {ids}")


def c4_auditoria_json() -> dict:
    datos = json.loads(config.RUTA_AUDITORIA_JSON.read_text(encoding="utf-8"))
    faltan = []
    for etapa in ("antes", "despues"):
        filas = datos.get(etapa, {}).get("por_grupo", [])
        for var in GRUPOS + ("mujer_vespertina",):
            sub = [f for f in filas if f["variable"] == var]
            if len(sub) < 2 or not all(all(k in f for k in METRICAS) for f in sub):
                faltan.append(f"{etapa}.{var}")
    record("C4 auditoria.json con métricas por grupo antes y después", not faltan,
           "faltan: " + ", ".join(faltan) if faltan else "genero, jornada, sede, trabaja, mujer_vespertina")
    return datos


def c5_brecha(datos: dict) -> None:
    antes = datos["antes"]["brecha_fp_subgrupo_pp"]
    despues = datos["despues"]["brecha_fp_subgrupo_pp"]
    ref = datos["referencia_sintetica"]["brecha_fp_subgrupo_pp"]
    record("C5 Brecha FP subgrupo menor después", despues < antes,
           f"antes {antes:.1f} pp -> después {despues:.1f} pp (brecha con riesgo real: {ref:.1f} pp)")


def c6_determinismo(est: pd.DataFrame) -> None:
    feats = modelo.construir_features(est)
    p = []
    for _ in range(2):
        m = modelo.entrenar(feats, est["deserto"], config.FEATURES_MODELO)
        p.append(modelo.predecir(m, feats, est))
    guardadas = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    iguales = p[0].equals(p[1])
    igual_archivo = np.allclose(guardadas["prob_riesgo"], p[0]["prob_riesgo"]) and \
        (guardadas["nivel"] == p[0]["nivel"]).all()
    record("C6 Mismos datos -> mismas predicciones", iguales and igual_archivo,
           f"dos entrenamientos idénticos={iguales}, coincide con predicciones.csv={igual_archivo}")


def c7_niveles() -> None:
    casos = {0: "bajo", 39.9: "bajo", 40: "medio", 55: "medio", 70: "medio", 70.1: "alto", 100: "alto"}
    malos = {k: modelo.nivel(k) for k, v in casos.items() if modelo.nivel(k) != v}
    record("C7 nivel() según umbrales de config", not malos,
           f"medio>={config.UMBRAL_MEDIO}, alto>{config.UMBRAL_ALTO}" + (f"; errores {malos}" if malos else ""))


def c8_artefactos(datos: dict) -> None:
    ok_archivos = config.RUTA_MODELO.is_file() and config.RUTA_METRICAS.is_file()
    met = json.loads(config.RUTA_METRICAS.read_text(encoding="utf-8")) if config.RUTA_METRICAS.is_file() else {}
    disp = datos["despues"]["disparidades"]
    evaluadas = all(v in disp and "disparidad" in disp[v] for v in GRUPOS)
    marcadas = [v for v, d in disp.items() if d["disparidad"]]
    record("C8 modelo.pkl, metricas.json y disparidad por variable", ok_archivos and evaluadas and "robusto" in met,
           f"disparidad (> {config.UMBRAL_DISPARIDAD_FP_PP:.0f} pp) después en: {marcadas or 'ninguna'}")


def c9_bandera(m: modelo.ModeloRiesgo) -> None:
    pred = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    ok = "dato_asistencia_poco_confiable" not in m.features and "dato_asistencia_poco_confiable" in pred
    record("C9 Bandera informativa fuera del modelo", ok,
           f"{int(pred['dato_asistencia_poco_confiable'].sum())} estudiantes marcados")


def main() -> int:
    print("== Ciclo 3: modelo explicable + auditoría ==")
    run_demo.ejecutar_pipeline()
    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    m = modelo.cargar_modelo()
    c1_auc(m)
    c2_features(m)
    c3_explicar(m, est)
    datos = c4_auditoria_json()
    c5_brecha(datos)
    c6_determinismo(est)
    c7_niveles()
    c8_artefactos(datos)
    c9_bandera(m)
    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo 3: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
