"""Auditoría de sesgos: compara el comportamiento del modelo entre grupos.

Las variables demográficas se cruzan con las predicciones DESPUÉS de predecir;
nunca se entregan al modelo.
"""
from __future__ import annotations

import pandas as pd

from src import config

COLUMNAS_AUDITORIA: list[str] = [
    "variable", "grupo", "n", "tasa_alto", "tasa_medio", "prob_media",
    "tasa_verdaderos_positivos", "tasa_falsos_positivos",
]


def auditar_sesgos(
    predicciones: pd.DataFrame,
    estudiantes: pd.DataFrame,
    variables: tuple[str, ...] = config.VARIABLES_AUDITORIA,
) -> pd.DataFrame:
    """Calcula métricas por grupo para cada variable de auditoría.

    STUB (ciclo 1): devuelve un DataFrame vacío con las columnas definitivas.
    """
    return pd.DataFrame(columns=COLUMNAS_AUDITORIA)


def brechas(auditoria: pd.DataFrame, metrica: str = "tasa_alto") -> dict[str, float]:
    """Diferencia máxima entre grupos de cada variable para `metrica`.

    STUB (ciclo 1): devuelve un dict vacío.
    """
    return {}


def resumen_texto(auditoria: pd.DataFrame) -> str:
    """Resumen legible de la auditoría para el panel.

    STUB (ciclo 1).
    """
    return "Auditoría pendiente (ciclo 1: stub)."
