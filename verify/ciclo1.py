"""Ciclo 1: arquitectura y estructura del repositorio.

Criterios:
  C1  Todos los archivos de la estructura existen
  C2  Los módulos de src/ se importan sin error
  C3  Funciones públicas de src/ con docstring y anotaciones de tipo completas
  C4  .env y data/ están en .gitignore (y git los ignora)
  C5  No hay ninguna API key escrita en el repo (búsqueda del prefijo de keys de Anthropic)
  C6  app.py se carga sin excepción con streamlit.testing.v1.AppTest
  C7  run_demo.py corre de punta a punta (código 0)
  C8  run_all.py devuelve 0 si todo pasa y != 0 si algo falla
  C9  config: UMBRAL_MEDIO=40, UMBRAL_ALTO=70, OFFLINE leído del entorno
"""
from __future__ import annotations

import importlib
import inspect
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["MODO_CORREO_REAL"] = "0"   # las pruebas nunca envían correos reales
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARCHIVOS = [
    "src/config.py", "src/generar_datos.py", "src/modelo.py", "src/auditoria.py",
    "src/seudonimizar.py", "src/claude_client.py",
    "prompts/explicar_riesgo.txt", "prompts/invitacion.txt",
    "prompts/clasificar_checkin.txt", "prompts/resumen_seccion.txt",
    "app.py", "run_demo.py", "verify/run_all.py", "verify/ciclo0.py", "verify/ciclo1.py",
    "requirements.txt", ".env.example", ".gitignore", "README.md",
]
MODULOS = ["src.config", "src.generar_datos", "src.modelo", "src.auditoria",
           "src.seudonimizar", "src.claude_client"]
EXCLUIR_DIRS = {".git", "data", "__pycache__", ".pytest_cache", ".venv"}
EXCLUIR_ARCHIVOS = {".env"}  # ignorado por git (C4): no forma parte del repo
PATRON_KEY = "sk-" + "ant"   # construido por partes para no autodetectarse

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def c1_archivos() -> None:
    faltan = [a for a in ARCHIVOS if not (ROOT / a).is_file()]
    if not (ROOT / "data").is_dir():
        faltan.append("data/ (se crea con run_demo.py)")
    record("C1 Estructura completa", not faltan, "faltan: " + ", ".join(faltan) if faltan else f"{len(ARCHIVOS)} archivos")


def c2_imports() -> list:
    mods, errores = [], []
    for m in MODULOS:
        try:
            mods.append(importlib.import_module(m))
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{m}: {type(exc).__name__}: {exc}")
    record("C2 Módulos de src/ importables", not errores, "; ".join(errores) or f"{len(mods)} módulos")
    return mods


def c3_firmas(mods: list) -> None:
    problemas = []
    for mod in mods:
        for nombre, obj in inspect.getmembers(mod):
            if nombre.startswith("_") or getattr(obj, "__module__", None) != mod.__name__:
                continue
            funcs = []
            if inspect.isfunction(obj):
                funcs = [(nombre, obj)]
            elif inspect.isclass(obj):
                if not inspect.getdoc(obj):
                    problemas.append(f"{mod.__name__}.{nombre}: sin docstring")
                funcs = [(f"{nombre}.{n}", f) for n, f in vars(obj).items()
                         if inspect.isfunction(f) and (not n.startswith("_") or n == "__init__")]
            for fn_name, fn in funcs:
                ref = f"{mod.__name__}.{fn_name}"
                if fn.__name__ != "__init__" and not inspect.getdoc(fn):
                    problemas.append(f"{ref}: sin docstring")
                sig = inspect.signature(fn)
                sin_tipo = [p for p in sig.parameters if p not in ("self", "cls")
                            and sig.parameters[p].annotation is inspect.Parameter.empty]
                if sin_tipo:
                    problemas.append(f"{ref}: parámetros sin tipo {sin_tipo}")
                if sig.return_annotation is inspect.Signature.empty:
                    problemas.append(f"{ref}: sin tipo de retorno")
    record("C3 Stubs con docstring y tipos", not problemas, "; ".join(problemas[:5]) or "ok")


def c4_gitignore() -> None:
    lineas = {l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    en_archivo = {".env", "data/"} <= lineas
    ignorados = True
    for ruta in (ROOT / ".env", ROOT / "data" / "x.csv"):
        r = subprocess.run(["git", "check-ignore", "-q", str(ruta)], cwd=ROOT, capture_output=True)
        ignorados &= r.returncode == 0
    record("C4 .env y data/ en .gitignore", en_archivo and ignorados,
           f"en archivo={en_archivo}, git los ignora={ignorados}")


def c5_sin_keys() -> None:
    hallazgos, revisados = [], 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUIR_DIRS]
        for f in filenames:
            if f in EXCLUIR_ARCHIVOS:
                continue
            p = Path(dirpath) / f
            try:
                contenido = p.read_bytes()
            except OSError:
                continue
            revisados += 1
            if PATRON_KEY.encode() in contenido:
                hallazgos.append(str(p.relative_to(ROOT)))
    record("C5 Sin API keys en el repo", not hallazgos,
           "encontrado en: " + ", ".join(hallazgos) if hallazgos else f"{revisados} archivos revisados")


def c6_app() -> None:
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
        errores = [str(e.value) for e in at.exception]
        record("C6 app.py carga con AppTest", not errores, "; ".join(errores) or f"título: {at.title[0].value}")
    except Exception as exc:  # noqa: BLE001
        record("C6 app.py carga con AppTest", False, f"{type(exc).__name__}: {exc}")


def c7_run_demo() -> None:
    env = {**os.environ, "OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "run_demo.py"], cwd=ROOT, capture_output=True, text=True,
                       env=env, timeout=300, encoding="utf-8")
    detalle = "código 0" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["?"])[-1]
    record("C7 run_demo.py de punta a punta", r.returncode == 0, detalle)


def c8_run_all() -> None:
    run_all = ROOT / "verify" / "run_all.py"
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "ciclo0.py").write_text("import sys; print('ok'); sys.exit(0)\n")
        (t / "ciclo1.py").write_text("import sys; print('ok'); sys.exit(0)\n")
        todo_pasa = subprocess.run([sys.executable, str(run_all), "--dir", tmp],
                                   capture_output=True).returncode
        (t / "ciclo2.py").write_text("import sys; print('fail'); sys.exit(1)\n")
        uno_falla = subprocess.run([sys.executable, str(run_all), "--dir", tmp],
                                   capture_output=True).returncode
    ok = todo_pasa == 0 and uno_falla != 0
    record("C8 run_all.py: 0 si todo pasa, !=0 si algo falla", ok,
           f"todo pasa -> {todo_pasa}, uno falla -> {uno_falla}")


def c9_config() -> None:
    from src import config
    code = "import sys; sys.path.insert(0, r'%s'); from src import config; print(config.OFFLINE)" % ROOT
    leer = lambda v: subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                    env={**os.environ, "OFFLINE": v}).stdout.strip()
    offline_on, offline_off = leer("1"), leer("0")
    ok = (config.UMBRAL_MEDIO == 40 and config.UMBRAL_ALTO == 70
          and offline_on == "True" and offline_off == "False" and bool(config.ANTHROPIC_MODEL))
    record("C9 config: umbrales 40/70 y OFFLINE desde entorno", ok,
           f"medio={config.UMBRAL_MEDIO}, alto={config.UMBRAL_ALTO}, OFFLINE=1->{offline_on}, 0->{offline_off}")


def main() -> int:
    print("== Ciclo 1: arquitectura y estructura ==")
    c7_run_demo()  # primero: crea data/ que C1 y C6 esperan
    c1_archivos()
    mods = c2_imports()
    c3_firmas(mods)
    c4_gitignore()
    c5_sin_keys()
    c6_app()
    c8_run_all()
    c9_config()
    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo 1: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
