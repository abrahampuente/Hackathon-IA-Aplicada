"""Ejecuta todos los verify/cicloN.py en orden y resume PASS/FAIL por ciclo.

Devuelve 0 solo si hay al menos un script y todos terminan con código 0.
Uso:  python verify/run_all.py [--dir CARPETA]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ciclo_num(p: Path) -> int:
    return int(re.search(r"ciclo(\d+)", p.stem).group(1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=HERE, help="carpeta con los cicloN.py")
    args = parser.parse_args(argv)
    carpeta: Path = args.dir.resolve()

    scripts = sorted(
        (p for p in carpeta.glob("ciclo*.py") if re.fullmatch(r"ciclo\d+", p.stem)),
        key=ciclo_num,
    ) + sorted(p for p in carpeta.glob("ciclo_*.py"))   # ciclos con nombre (p. ej. ciclo_correo) al final
    summary = []
    for script in scripts:
        print(f"\n### {script.name}", flush=True)
        proc = subprocess.run([sys.executable, str(script)], cwd=HERE.parent)
        summary.append((script.name, proc.returncode == 0))
    print("\n== run_all ==")
    for name, ok in summary:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = bool(summary) and all(ok for _, ok in summary)
    print(f"run_all: {'PASS' if all_ok else 'FAIL'} ({sum(ok for _, ok in summary)}/{len(summary)})")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
