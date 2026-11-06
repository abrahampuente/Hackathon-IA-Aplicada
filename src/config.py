"""Configuración central del sistema de alerta temprana.

Todo umbral, ruta o parámetro que otro módulo necesite se lee desde aquí.
La API key NO se expone en este módulo: solo `claude_client` la lee del entorno.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT: Path = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

# --- Rutas -----------------------------------------------------------------
DATA_DIR: Path = ROOT / "data"
PROMPTS_DIR: Path = ROOT / "prompts"
RUTA_ESTUDIANTES: Path = DATA_DIR / "estudiantes.csv"          # export simulado VIVO (perfil)
RUTA_REGISTROS: Path = DATA_DIR / "registros_academicos.csv"   # asistencia y notas por semana
RUTA_PREDICCIONES: Path = DATA_DIR / "predicciones.csv"
RUTA_AUDITORIA: Path = DATA_DIR / "auditoria.csv"
RUTA_BANDEJA: Path = DATA_DIR / "bandeja_simulada.jsonl"       # mensajes que NUNCA se envían
RUTA_MODELO: Path = DATA_DIR / "modelo.pkl"

# --- Umbrales de riesgo (en %). Cambiarlos requiere autorización del equipo. ---
UMBRAL_MEDIO: int = 40   # >= 40 y <= 70 -> medio: invitación automática a bandeja simulada
UMBRAL_ALTO: int = 70    # > 70 -> alto: un tutor revisa y decide

# --- Variables -------------------------------------------------------------
# Únicas entradas permitidas al modelo: conducta académica.
FEATURES_MODELO: tuple[str, ...] = (
    "asistencia_promedio",
    "asistencia_tendencia",
    "nota_promedio",
    "nota_tendencia",
    "evaluaciones_rojas",
    "semanas_sin_asistir",
)
# Solo para auditar sesgos. Prohibidas como entrada del modelo (y sus sustitutos).
VARIABLES_AUDITORIA: tuple[str, ...] = ("genero", "sede", "jornada", "trabaja", "origen")
VARIABLES_PROHIBIDAS: tuple[str, ...] = VARIABLES_AUDITORIA + (
    "comuna", "edad", "nacionalidad", "colegio_origen", "situacion_pago",
)

# --- Datos sintéticos --------------------------------------------------------
N_ESTUDIANTES: int = 600
N_SEMANAS: int = 12
SEMILLA: int = 2026


# --- Claude ------------------------------------------------------------------
def _flag(nombre: str, por_defecto: bool = False) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-opus-5-5"
OFFLINE: bool = _flag("OFFLINE")            # True -> claude_client devuelve textos de plantilla sin llamar a la API
MAX_LLAMADAS_API: int = 200                 # tope por ciclo; superarlo requiere autorización
