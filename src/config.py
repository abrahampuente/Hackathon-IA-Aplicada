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
RUTA_ESTUDIANTES: Path = DATA_DIR / "estudiantes.csv"          # export simulado VIVO
RUTA_DEMO: Path = DATA_DIR / "estudiantes_demo.csv"            # 12 casos curados para el pitch
RUTA_README_DATOS: Path = DATA_DIR / "README_datos.md"         # documentación del dataset y del sesgo
RUTA_PREDICCIONES: Path = DATA_DIR / "predicciones.csv"
RUTA_AUDITORIA: Path = DATA_DIR / "auditoria.csv"
RUTA_BANDEJA: Path = DATA_DIR / "bandeja_simulada.jsonl"       # mensajes que NUNCA se envían
RUTA_MODELO: Path = DATA_DIR / "modelo.pkl"
RUTA_METRICAS: Path = DATA_DIR / "metricas.json"
RUTA_AUDITORIA_JSON: Path = DATA_DIR / "auditoria.json"

# --- Umbrales de riesgo (en %). Cambiarlos requiere autorización del equipo. ---
UMBRAL_MEDIO: int = 40   # >= 40 y <= 70 -> medio: invitación automática a bandeja simulada
UMBRAL_ALTO: int = 70    # > 70 -> alto: un tutor revisa y decide

# --- Variables -------------------------------------------------------------
# Únicas entradas permitidas al modelo: conducta académica.
# Versión base ("antes"): calculada sobre la asistencia registrada tal cual.
FEATURES_BASE: tuple[str, ...] = (
    "asistencia_promedio",
    "asistencia_tendencia",
    "semanas_bajo_75",
    "nota_promedio",
    "notas_rojas",
    "cambio_parciales",
)
# Versión robusta ("después", mitigación de sesgo): la asistencia se suaviza con
# mediana móvil de 3 semanas antes de calcular nivel, tendencia y semanas bajo 75%.
FEATURES_ROBUSTAS: tuple[str, ...] = (
    "asistencia_mediana",
    "asistencia_tendencia_robusta",
    "semanas_bajo_75_robusta",
    "nota_promedio",
    "notas_rojas",
    "cambio_parciales",
)
FEATURES_MODELO: tuple[str, ...] = FEATURES_ROBUSTAS   # las que usa el modelo en producción
UMBRAL_SEMANA_BAJA: float = 75.0
# Bandera informativa (NO entra al modelo): >= N semanas con caída aislada >= X pp bajo la mediana móvil.
CAIDA_AISLADA_PP: float = 10.0
MIN_CAIDAS_POCO_CONFIABLE: int = 2
# Auditoría
UMBRAL_DISPARIDAD_FP_PP: float = 10.0   # brecha de falsos positivos entre grupos que marca disparidad
MIN_NEGATIVOS_GRUPO: int = 20           # grupos más chicos se reportan pero no cuentan para la brecha
# Solo para auditar sesgos. Prohibidas como entrada del modelo (y sus sustitutos).
VARIABLES_AUDITORIA: tuple[str, ...] = ("genero", "sede", "jornada", "trabaja", "origen")
VARIABLES_PROHIBIDAS: tuple[str, ...] = VARIABLES_AUDITORIA + (
    "comuna", "edad", "nacionalidad", "colegio_origen", "situacion_pago",
    "carrera", "seccion",  # sustitutos: la sección codifica sede y jornada
    "nombre_ficticio", "correo_ficticio", "checkin_texto",
)

# --- Datos sintéticos --------------------------------------------------------
N_ESTUDIANTES: int = 600
N_SEMANAS: int = 8
SEMILLA: int = 2026
RAMOS: tuple[str, ...] = ("matematica", "comunicacion", "especialidad")
COLS_ASISTENCIA: tuple[str, ...] = tuple(f"asistencia_s{i}" for i in range(1, N_SEMANAS + 1))
COLS_NOTAS: tuple[str, ...] = tuple(f"nota_{r}_p{p}" for r in RAMOS for p in (1, 2))
DOMINIO_CORREO_FICTICIO: str = "ejemplo.cl"


# --- Claude ------------------------------------------------------------------
def _flag(nombre: str, por_defecto: bool = False) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-opus-5-5"
OFFLINE: bool = _flag("OFFLINE")            # True -> claude_client responde desde data/cache_claude.json
MAX_LLAMADAS_API: int = 200                 # tope por ciclo; superarlo requiere autorización
CICLO_ACTUAL: int = int(os.getenv("CICLO_ACTUAL", "6"))   # 6 = ciclo de correo real   # para contar llamadas del ciclo en el log
CLAUDE_EFFORT: str = os.getenv("CLAUDE_EFFORT", "low").strip() or "low"   # tareas cortas: esfuerzo bajo
RUTA_CACHE_CLAUDE: Path = DATA_DIR / "cache_claude.json"
RUTA_LOG_API: Path = DATA_DIR / "log_api.jsonl"

# Invitaciones al estudiante: nunca mencionan riesgo ni nada derivado del modelo.
MAX_PALABRAS_INVITACION: int = 120
# Raíces sin tildes, comparadas en minúsculas y sin tildes.
PALABRAS_PROHIBIDAS_INVITACION: tuple[str, ...] = (
    "riesg", "%", "porcentaj", "por ciento", "desert", "deserc", "abandon",
    "alerta", "predic", "probabil",
)
