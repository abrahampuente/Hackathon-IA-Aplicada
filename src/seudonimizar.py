"""Seudonimización: nada identificable sale hacia la API de Claude.

Todo payload enviado a Claude debe pasar por `preparar_payload`.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

COLUMNAS_IDENTIFICADORAS: tuple[str, ...] = (
    "nombre_ficticio", "correo_ficticio", "nombre", "rut", "email", "correo", "telefono",
)


def seudonimo(id_estudiante: str, sal: str) -> str:
    """Devuelve un seudónimo estable y no reversible sin la sal (p. ej. 'EST-3f9a1c').

    STUB (ciclo 1).
    """
    return "EST-000000"


def seudonimizar_df(df: pd.DataFrame, sal: str) -> pd.DataFrame:
    """Reemplaza `id_seudonimo` por un seudónimo con sal y elimina las columnas identificadoras.

    STUB (ciclo 1): devuelve una copia sin cambios.
    """
    return df.copy()


def contiene_pii(texto: str) -> bool:
    """True si el texto parece contener RUT, email, teléfono u otro identificador.

    STUB (ciclo 1).
    """
    return False


def preparar_payload(datos: dict[str, Any]) -> dict[str, Any]:
    """Valida y limpia un dict antes de enviarlo a Claude; lanza ValueError si hay PII.

    STUB (ciclo 1): devuelve una copia sin cambios.
    """
    return dict(datos)
