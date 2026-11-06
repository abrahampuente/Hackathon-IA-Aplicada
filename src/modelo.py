"""Modelo interpretable de riesgo de deserción.

Usa SOLO conducta académica (`config.FEATURES_MODELO`). Las variables
demográficas nunca entran: `validar_features` lo hace cumplir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from src import config

Nivel = Literal["bajo", "medio", "alto"]
COLUMNAS_PREDICCION: list[str] = [
    "id_seudonimo", "prob_riesgo", "nivel", "razon_1", "razon_2", "razon_3",
]


@dataclass
class ModeloRiesgo:
    """Contenedor del estimador entrenado y sus metadatos."""

    estimador: object | None = None
    features: tuple[str, ...] = config.FEATURES_MODELO
    metricas: dict[str, float] = field(default_factory=dict)


def validar_features(columnas: list[str] | tuple[str, ...]) -> None:
    """Lanza ValueError si alguna columna es demográfica o sustituta prohibida."""
    prohibidas = sorted(set(columnas) & set(config.VARIABLES_PROHIBIDAS))
    if prohibidas:
        raise ValueError(f"Variables prohibidas como entrada del modelo: {prohibidas}")


def construir_features(estudiantes: pd.DataFrame) -> pd.DataFrame:
    """Calcula `FEATURES_MODELO` (una fila por estudiante) desde asistencia y notas del export.

    STUB (ciclo 2): devuelve un DataFrame vacío con id + features.
    """
    return pd.DataFrame(columns=["id_seudonimo", *config.FEATURES_MODELO])


def entrenar(features: pd.DataFrame, etiquetas: pd.Series) -> ModeloRiesgo:
    """Entrena un modelo interpretable (p. ej. regresión logística) sobre `features`.

    STUB (ciclo 1): valida las columnas y devuelve un modelo sin estimador.
    """
    validar_features([c for c in features.columns if c != "id_seudonimo"])
    return ModeloRiesgo()


def nivel_de_riesgo(prob_pct: float) -> Nivel:
    """Traduce un % de riesgo (0-100) a nivel según los umbrales de config."""
    if prob_pct > config.UMBRAL_ALTO:
        return "alto"
    if prob_pct >= config.UMBRAL_MEDIO:
        return "medio"
    return "bajo"


def predecir(modelo: ModeloRiesgo, features: pd.DataFrame) -> pd.DataFrame:
    """Devuelve % de riesgo, nivel y las 3 razones principales por estudiante.

    STUB (ciclo 1): devuelve un DataFrame vacío con las columnas definitivas.
    """
    return pd.DataFrame(columns=COLUMNAS_PREDICCION)
