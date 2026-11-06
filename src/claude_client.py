"""Cliente de Claude para el sistema de alerta temprana.

Reglas:
- La API key se lee de ANTHROPIC_API_KEY (.env) y nunca se imprime ni se registra.
- Todo dato pasa por `seudonimizar.preparar_payload` antes de salir.
- Con `config.OFFLINE` no se llama a la API: se devuelven textos de plantilla.
- Cuenta llamadas y se detiene al llegar a `config.MAX_LLAMADAS_API`.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from src import config

CategoriaCheckin = Literal["academico", "laboral", "personal", "economico", "bienestar", "sin_alerta"]


class ClasificacionCheckin(TypedDict):
    categoria: CategoriaCheckin
    requiere_tutor: bool
    resumen: str


class LimiteLlamadasError(RuntimeError):
    """Se alcanzó el tope de llamadas a la API para este ciclo."""


def cargar_prompt(nombre: str) -> str:
    """Lee `prompts/<nombre>.txt`."""
    return (config.PROMPTS_DIR / f"{nombre}.txt").read_text(encoding="utf-8")


class ClienteClaude:
    """Envoltorio sobre el SDK `anthropic` con modo offline y contador de llamadas."""

    def __init__(self, offline: bool | None = None, modelo: str | None = None) -> None:
        self.offline: bool = config.OFFLINE if offline is None else offline
        self.modelo: str = modelo or config.ANTHROPIC_MODEL
        self.llamadas: int = 0

    def explicar_riesgo(self, caso: dict[str, Any]) -> str:
        """Explica al tutor el % de riesgo y sus 3 razones en lenguaje claro.

        STUB (ciclo 1).
        """
        return "Explicación pendiente (stub)."

    def redactar_invitacion(self, caso: dict[str, Any]) -> str:
        """Redacta una invitación no estigmatizante; nunca menciona riesgo ni porcentajes.

        STUB (ciclo 1).
        """
        return "Invitación pendiente (stub)."

    def clasificar_checkin(self, texto: str) -> ClasificacionCheckin:
        """Clasifica un check-in del estudiante y decide si requiere tutor.

        STUB (ciclo 1).
        """
        return {"categoria": "sin_alerta", "requiere_tutor": False, "resumen": ""}

    def resumir_seccion(self, agregados: dict[str, Any]) -> str:
        """Resume patrones de una sección a partir de datos agregados (sin individuos).

        STUB (ciclo 1).
        """
        return "Resumen pendiente (stub)."
