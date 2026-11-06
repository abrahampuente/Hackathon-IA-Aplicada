"""Generación de datos sintéticos que imitan un export de VIVO Duoc.

Ningún dato corresponde a personas reales. Los IDs son correlativos ficticios.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config

COLUMNAS_ESTUDIANTES: list[str] = [
    "id_estudiante", "seccion", *config.VARIABLES_AUDITORIA, "deserta",
]
COLUMNAS_REGISTROS: list[str] = ["id_estudiante", "semana", "asistencia", "nota"]


def generar_estudiantes(n: int = config.N_ESTUDIANTES, semilla: int = config.SEMILLA) -> pd.DataFrame:
    """Genera el perfil de `n` estudiantes de primer año.

    Incluye variables demográficas (solo para auditoría) y la etiqueta `deserta`.
    STUB (ciclo 1): devuelve un DataFrame vacío con las columnas definitivas.
    """
    return pd.DataFrame(columns=COLUMNAS_ESTUDIANTES)


def generar_registros_academicos(
    estudiantes: pd.DataFrame,
    n_semanas: int = config.N_SEMANAS,
    semilla: int = config.SEMILLA,
) -> pd.DataFrame:
    """Genera asistencia (0-1) y notas (1.0-7.0) semanales por estudiante.

    STUB (ciclo 1): devuelve un DataFrame vacío con las columnas definitivas.
    """
    return pd.DataFrame(columns=COLUMNAS_REGISTROS)


def guardar_csv(df: pd.DataFrame, ruta: Path) -> Path:
    """Escribe `df` como CSV (formato tipo export VIVO) y devuelve la ruta."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8")
    return ruta


def generar_todo(semilla: int = config.SEMILLA) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Genera y guarda estudiantes y registros en `config.DATA_DIR`."""
    estudiantes = generar_estudiantes(semilla=semilla)
    registros = generar_registros_academicos(estudiantes, semilla=semilla)
    guardar_csv(estudiantes, config.RUTA_ESTUDIANTES)
    guardar_csv(registros, config.RUTA_REGISTROS)
    return estudiantes, registros
