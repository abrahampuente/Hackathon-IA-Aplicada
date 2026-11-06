"""Catálogo de apoyos (contenido DE EJEMPLO) y flujo de propuesta + consentimiento.

Reglas:
- Ningún apoyo se activa solo: toda sugerencia queda como propuesta para el tutor.
- Un apoyo externo además exige consentimiento explícito del estudiante, registrado,
  antes de activarse o de compartir cualquier dato con la organización externa.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from src import config

NOTA_CATALOGO: str = "Contenido de ejemplo: validar con Asuntos Estudiantiles antes de usarlo con estudiantes."
RUTA_APOYOS: Path = config.DATA_DIR / "apoyos.json"
RUTA_PROPUESTAS: Path = config.DATA_DIR / "propuestas_apoyo.json"
RUTA_CONSENTIMIENTOS: Path = config.DATA_DIR / "consentimientos.jsonl"

EstadoPropuesta = Literal["propuesta_tutor", "pendiente_consentimiento", "activo", "rechazado"]


class Apoyo(TypedDict):
    id: str
    nombre: str
    tipo: Literal["interno", "externo"]
    necesidad: Literal["economica", "academica", "emocional", "logistica"]
    descripcion: str
    requisitos: str
    como_postular: str
    requiere_consentimiento: bool
    a_validar: bool


def _apoyo(id_: str, nombre: str, tipo: str, necesidad: str, descripcion: str,
           requisitos: str, como_postular: str) -> Apoyo:
    return {"id": id_, "nombre": nombre, "tipo": tipo, "necesidad": necesidad,  # type: ignore[typeddict-item]
            "descripcion": descripcion, "requisitos": requisitos, "como_postular": como_postular,
            "requiere_consentimiento": tipo == "externo", "a_validar": True}


CATALOGO: list[Apoyo] = [
    _apoyo("AP-EQUIPOS", "Préstamo de equipos por semestre", "interno", "logistica",
           "Préstamo de notebook por el semestre para quienes no tienen computador.",
           "Alumno regular; firmar compromiso de devolución.", "Solicitud en Biblioteca de la sede."),
    _apoyo("AP-TNE", "Orientación Tarjeta Nacional Estudiantil", "interno", "economica",
           "Ayuda para obtener o revalidar la TNE y pagar pasaje rebajado.",
           "Alumno regular.", "Pedir hora en Asuntos Estudiantiles."),
    _apoyo("AP-BIBLIO", "Biblioteca virtual", "interno", "academica",
           "Acceso gratuito a libros y bibliografía digital de los ramos.",
           "Cuenta institucional activa.", "Ingresar con la cuenta institucional al portal de biblioteca."),
    _apoyo("AP-TUTORIA", "Tutoría académica", "interno", "academica",
           "Tutorías grupales o individuales en ramos de primer año, también en horario vespertino.",
           "Ninguno.", "Inscribirse con el tutor o en el portal de tutorías."),
    _apoyo("AP-PSICO", "Apoyo psicológico", "interno", "emocional",
           "Atención psicológica breve y confidencial para estudiantes.",
           "Alumno regular.", "Agendar con Asuntos Estudiantiles; el tutor puede derivar."),
    _apoyo("AP-ARANCEL", "Beneficios de arancel", "interno", "economica",
           "Orientación sobre becas, créditos y convenios de pago del arancel.",
           "Según el beneficio; puede requerir acreditar situación socioeconómica.",
           "Reunión con Financiamiento Estudiantil."),
    _apoyo("AP-HORARIO", "Orientación trabajo y estudio", "interno", "logistica",
           "Ayuda para compatibilizar turnos laborales con el horario académico.",
           "Ninguno.", "Conversar con el tutor o la jefatura de carrera."),
    _apoyo("AP-SALA", "Sala de estudio con horario extendido", "interno", "logistica",
           "Espacio con computadores e internet abierto hasta tarde y sábados.",
           "Credencial estudiantil.", "Uso libre presentando la credencial."),
    _apoyo("AP-FUNDACION", "Fundación aliada (ejemplo)", "externo", "economica",
           "Organización externa que entrega apoyo económico puntual a estudiantes.",
           "Evaluación de la fundación; requiere compartir datos con terceros.",
           "Solo vía tutor, tras consentimiento explícito del estudiante."),
]


def guardar_catalogo(ruta: Path = RUTA_APOYOS) -> Path:
    """Escribe data/apoyos.json con la nota visible de contenido de ejemplo."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"nota": NOTA_CATALOGO, "apoyos": CATALOGO}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return ruta


def cargar_catalogo(ruta: Path = RUTA_APOYOS) -> list[Apoyo]:
    """Lee el catálogo; si no existe, lo genera."""
    if not ruta.is_file():
        guardar_catalogo(ruta)
    return json.loads(ruta.read_text(encoding="utf-8"))["apoyos"]


def ids_catalogo() -> set[str]:
    """IDs válidos del catálogo."""
    return {a["id"] for a in cargar_catalogo()}


# --------------------------------------------------------------------------
# Propuestas y consentimiento
# --------------------------------------------------------------------------
class GestorApoyos:
    """Registro de propuestas al tutor y consentimientos del estudiante (persistido en data/)."""

    def __init__(self, ruta_propuestas: Path = RUTA_PROPUESTAS,
                 ruta_consentimientos: Path = RUTA_CONSENTIMIENTOS) -> None:
        self.ruta_propuestas = ruta_propuestas
        self.ruta_consentimientos = ruta_consentimientos
        self.catalogo: dict[str, Apoyo] = {a["id"]: a for a in cargar_catalogo()}
        self.propuestas: list[dict[str, Any]] = (
            json.loads(ruta_propuestas.read_text(encoding="utf-8")) if ruta_propuestas.is_file() else [])

    def _guardar(self) -> None:
        self.ruta_propuestas.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_propuestas.write_text(json.dumps(self.propuestas, ensure_ascii=False, indent=2), encoding="utf-8")

    def proponer(self, id_seudonimo: str, sugerencias: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Crea propuestas para el tutor. Externas quedan pendientes de consentimiento; nada se activa."""
        nuevas = []
        for s in sugerencias:
            apoyo = self.catalogo.get(s["id"])
            if apoyo is None:
                raise ValueError(f"Apoyo inexistente en el catálogo: {s['id']}")
            p = {
                "id_propuesta": f"PR-{len(self.propuestas) + 1:04d}",
                "id_seudonimo": id_seudonimo, "id_apoyo": apoyo["id"], "tipo": apoyo["tipo"],
                "razon": s.get("razon", ""),
                "estado": "pendiente_consentimiento" if apoyo["requiere_consentimiento"] else "propuesta_tutor",
                "datos_compartidos_externo": False,
            }
            self.propuestas.append(p)
            nuevas.append(p)
        self._guardar()
        return nuevas

    def registrar_consentimiento(self, id_propuesta: str, acepta: bool, medio: str = "formulario_simulado") -> None:
        """Registra la respuesta explícita del estudiante (simulada en la demo)."""
        self.ruta_consentimientos.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ruta_consentimientos, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "id_propuesta": id_propuesta, "acepta": bool(acepta), "medio": medio},
                                ensure_ascii=False) + "\n")
        if not acepta:
            self._propuesta(id_propuesta)["estado"] = "rechazado"
            self._guardar()

    def consentimiento_vigente(self, id_propuesta: str) -> bool:
        """True si la última respuesta registrada para la propuesta es un sí."""
        if not self.ruta_consentimientos.is_file():
            return False
        ultimo = None
        for l in self.ruta_consentimientos.read_text(encoding="utf-8").splitlines():
            e = json.loads(l)
            if e["id_propuesta"] == id_propuesta:
                ultimo = e["acepta"]
        return ultimo is True

    def activar(self, id_propuesta: str, aprobado_por_tutor: bool) -> dict[str, Any]:
        """Activa una propuesta si el tutor la aprueba y, si es externa, hay consentimiento vigente.

        Lanza PermissionError en cualquier otro caso.
        """
        p = self._propuesta(id_propuesta)
        if not aprobado_por_tutor:
            raise PermissionError("Toda activación requiere la decisión del tutor.")
        if p["tipo"] == "externo" and not self.consentimiento_vigente(id_propuesta):
            raise PermissionError("Apoyo externo sin consentimiento registrado del estudiante.")
        p["estado"] = "activo"
        self._guardar()
        return p

    def _propuesta(self, id_propuesta: str) -> dict[str, Any]:
        for p in self.propuestas:
            if p["id_propuesta"] == id_propuesta:
                return p
        raise KeyError(id_propuesta)

    def externos_activos_sin_consentimiento(self) -> list[str]:
        """Auditoría: propuestas externas activas sin un sí registrado (debe ser vacía)."""
        return [p["id_propuesta"] for p in self.propuestas
                if p["tipo"] == "externo" and p["estado"] == "activo"
                and not self.consentimiento_vigente(p["id_propuesta"])]
