"""Ciclo 0: verificación del entorno.

Criterios:
  C1  Python >= 3.11
  C2  Paquetes del stack importables
  C3  .env presente con ANTHROPIC_API_KEY no vacía
  C4  .env ignorado por git (la key nunca se versiona)
  C5  Una llamada mínima a Claude responde (imprime solo OK y el modelo)

Nunca imprime la API key: cualquier texto de error se sanitiza antes de mostrarse.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DEFAULT_MODEL = "claude-opus-5-5"
STACK = ["pandas", "sklearn", "streamlit", "anthropic", "dotenv", "pytest"]

results: list[tuple[str, bool, str]] = []
_secret: str | None = None


def safe(text: str) -> str:
    """Quita la API key de cualquier texto antes de imprimirlo."""
    if _secret:
        text = text.replace(_secret, "***")
    return text


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {safe(detail)}" if detail else ""))


def c1_python() -> None:
    v = sys.version_info
    record("C1 Python >= 3.11", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}")


def c2_packages() -> None:
    missing = []
    for mod in STACK:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{mod} ({type(exc).__name__})")
    record("C2 Paquetes del stack importables", not missing,
           "faltan: " + ", ".join(missing) if missing else ", ".join(STACK))


def c3_env() -> dict[str, str | None]:
    global _secret
    if not ENV_PATH.is_file():
        record("C3 .env con ANTHROPIC_API_KEY", False, f"no existe {ENV_PATH.name} en {ROOT}")
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        record("C3 .env con ANTHROPIC_API_KEY", False, "python-dotenv no instalado")
        return {}
    values = dotenv_values(ENV_PATH)
    key = (values.get("ANTHROPIC_API_KEY") or "").strip()
    _secret = key or None
    record("C3 .env con ANTHROPIC_API_KEY", bool(key),
           "presente (valor oculto)" if key else "variable ausente o vacía")
    return values


def c4_gitignore() -> None:
    try:
        proc = subprocess.run(["git", "check-ignore", "-q", str(ENV_PATH)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        record("C4 .env ignorado por git", False, f"no se pudo ejecutar git: {type(exc).__name__}")
        return
    record("C4 .env ignorado por git", proc.returncode == 0,
           "ignorado" if proc.returncode == 0 else "git NO lo ignora")


def c5_claude(values: dict[str, str | None]) -> None:
    name = "C5 Llamada mínima a Claude"
    key = (values.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        record(name, False, "omitida: falta ANTHROPIC_API_KEY en .env")
        return
    model = (values.get("ANTHROPIC_MODEL") or "").strip() or DEFAULT_MODEL
    try:
        import anthropic
    except ImportError:
        record(name, False, "paquete anthropic no instalado")
        return
    try:
        client = anthropic.Anthropic(api_key=key, timeout=60.0, max_retries=2)
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": "Responde solo con la palabra OK."}],
        )
    except anthropic.AuthenticationError:
        record(name, False, "401: API key inválida")
        return
    except anthropic.NotFoundError:
        record(name, False, f"404: modelo '{model}' no encontrado")
        return
    except anthropic.RateLimitError:
        record(name, False, "429: límite de tasa o sin créditos")
        return
    except anthropic.APIStatusError as exc:
        record(name, False, f"HTTP {exc.status_code}: {type(exc).__name__}")
        return
    except anthropic.APIConnectionError as exc:
        record(name, False, f"sin conexión: {type(exc).__name__}")
        return
    ok = resp.stop_reason in {"end_turn", "max_tokens", "stop_sequence"} and bool(resp.content)
    record(name, ok, f"OK modelo={resp.model}" if ok else f"stop_reason={resp.stop_reason}")


def main() -> int:
    print("== Ciclo 0: verificación del entorno ==")
    c1_python()
    c2_packages()
    values = c3_env()
    c4_gitignore()
    c5_claude(values)
    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo 0: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
