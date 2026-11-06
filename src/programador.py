"""Programador de envíos con reloj simulado. Lógica en código, no en Claude.

Reglas:
1. Todo mensaje de un caso medio o alto nace PROGRAMADO, con envio_programado = creado + 24 h.
2. En esas 24 h el tutor puede: Enviar ahora, Editar (sigue programado), Cancelar (con motivo)
   o Contactar en persona (cancela el envío automático).
3. Si nadie lo revisa, al cumplirse las 24 h pasa a ENVIADO con enviado_sin_revision = True.
4. A los 7 días del primer envío, si no respondió ni pidió no recibir más, se programa UN único
   recordatorio (misma ventana de 24 h). Después, nada automático: el caso queda "sin respuesta".
5. Excepciones que nunca se envían solas (REQUIERE_APROBACION): check-in con derivar_humano,
   mensajes que ofrecen un apoyo externo y casos con dato_asistencia_poco_confiable.
6. "No quiero recibir más" cancela todo lo programado del estudiante, incluido el recordatorio.

Ningún mensaje sale de verdad: "enviar" = dejarlo en la bandeja simulada del estudiante.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from src import config
from src.claude_client import problemas_invitacion

Estado = Literal["PROGRAMADO", "REQUIERE_APROBACION", "ENVIADO", "CANCELADO", "CONTACTO_PRESENCIAL"]
Excepcion = Literal["derivar_humano", "apoyo_externo", "dato_poco_confiable"]
VENTANA: timedelta = timedelta(hours=24)
SEGUIMIENTO: timedelta = timedelta(days=7)
INICIO_DEMO: datetime = datetime(2026, 11, 9, 9, 0)
RUTA_ESTADO: Path = config.DATA_DIR / "programador.json"
RUTA_DECISIONES: Path = config.DATA_DIR / "decisiones.csv"
CAMPOS_DECISION: tuple[str, ...] = ("hora_simulada", "hora_real", "id_mensaje", "id_seudonimo", "actor",
                                    "accion", "motivo")
PENDIENTES: tuple[str, ...] = ("PROGRAMADO", "REQUIERE_APROBACION")


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="minutes")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Programador:
    """Estado persistente de mensajes, casos y reloj simulado (JSON) + registro de decisiones (CSV)."""

    def __init__(self, ruta_estado: Path = RUTA_ESTADO, ruta_decisiones: Path = RUTA_DECISIONES,
                 ruta_bandeja: Path = config.RUTA_BANDEJA,
                 texto_recordatorio: Callable[[dict[str, Any]], str] | None = None) -> None:
        self.ruta_estado = ruta_estado
        self.ruta_decisiones = ruta_decisiones
        self.ruta_bandeja = ruta_bandeja
        self.texto_recordatorio = texto_recordatorio
        if ruta_estado.is_file():
            self.estado: dict[str, Any] = json.loads(ruta_estado.read_text(encoding="utf-8"))
        else:
            self.estado = {"reloj": _iso(INICIO_DEMO), "seq": 0, "mensajes": [], "casos": {}}

    # ---- persistencia y registro -------------------------------------------
    def guardar(self) -> None:
        """Escribe el estado a disco."""
        self.ruta_estado.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_estado.write_text(json.dumps(self.estado, ensure_ascii=False, indent=2), encoding="utf-8")

    def _decision(self, m: dict[str, Any] | None, id_seudonimo: str, actor: str, accion: str,
                  motivo: str = "") -> None:
        self.ruta_decisiones.parent.mkdir(parents=True, exist_ok=True)
        nuevo = not self.ruta_decisiones.is_file()
        with open(self.ruta_decisiones, "a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if nuevo:
                w.writerow(CAMPOS_DECISION)
            w.writerow([self.estado["reloj"], datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        m["id_mensaje"] if m else "", id_seudonimo, actor, accion, motivo])

    # ---- reloj ---------------------------------------------------------------
    @property
    def ahora(self) -> datetime:
        """Hora simulada actual."""
        return _dt(self.estado["reloj"])

    def avanzar(self, horas: float = 0, dias: float = 0) -> list[dict[str, Any]]:
        """Avanza el reloj simulado y procesa envíos/recordatorios. Devuelve los mensajes enviados."""
        self.estado["reloj"] = _iso(self.ahora + timedelta(hours=horas, days=dias))
        enviados = self.procesar()
        self.guardar()
        return enviados

    # ---- casos y mensajes ------------------------------------------------------
    def registrar_caso(self, id_seudonimo: str, nivel: str, canal: str, carrera: str,
                       dato_poco_confiable: bool = False, derivar_humano: bool = False) -> dict[str, Any]:
        """Alta (o actualización) de un caso con sus banderas de excepción."""
        caso = self.estado["casos"].setdefault(id_seudonimo, {
            "id_seudonimo": id_seudonimo, "respondio": False, "no_mas": False, "primer_envio": None,
            "recordatorio_creado": False})
        caso.update({"nivel": nivel, "canal": canal, "carrera": carrera,
                     "dato_poco_confiable": bool(dato_poco_confiable), "derivar_humano": bool(derivar_humano)})
        self.guardar()
        return caso

    def _excepciones(self, caso: dict[str, Any], apoyo_externo: bool) -> list[str]:
        exc = []
        if caso.get("derivar_humano"):
            exc.append("derivar_humano")
        if apoyo_externo:
            exc.append("apoyo_externo")
        if caso.get("dato_poco_confiable"):
            exc.append("dato_poco_confiable")
        return exc

    def crear_mensaje(self, id_seudonimo: str, texto: str, tipo: str = "invitacion",
                      apoyo_externo: bool = False, creado: datetime | None = None) -> dict[str, Any]:
        """Crea un mensaje PROGRAMADO (+24 h) o REQUIERE_APROBACION si aplica una excepción."""
        caso = self.estado["casos"][id_seudonimo]
        if caso["nivel"] not in ("medio", "alto"):
            raise ValueError("Solo los casos medio o alto reciben mensajes.")
        if caso["no_mas"]:
            raise ValueError("El estudiante pidió no recibir más mensajes.")
        problemas = problemas_invitacion(texto)
        if problemas:
            raise ValueError(f"Texto inválido para el estudiante: {problemas}")
        creado = creado or self.ahora
        self.estado["seq"] += 1
        exc = self._excepciones(caso, apoyo_externo)
        m = {
            "id_mensaje": f"MSG-{self.estado['seq']:04d}", "id_seudonimo": id_seudonimo, "tipo": tipo,
            "canal": caso["canal"], "texto": texto, "creado": _iso(creado),
            "envio_programado": _iso(creado + VENTANA),
            "estado": "REQUIERE_APROBACION" if exc else "PROGRAMADO", "excepciones": exc,
            "apoyo_externo": bool(apoyo_externo), "enviado_en": None, "enviado_sin_revision": None,
            "editado": False, "motivo_cancelacion": None,
        }
        self.estado["mensajes"].append(m)
        self._decision(m, id_seudonimo, "sistema", "programar" if not exc else "requiere_aprobacion",
                       ",".join(exc))
        self.guardar()
        return m

    def mensaje(self, id_mensaje: str) -> dict[str, Any]:
        """Busca un mensaje por id."""
        for m in self.estado["mensajes"]:
            if m["id_mensaje"] == id_mensaje:
                return m
        raise KeyError(id_mensaje)

    def mensajes_de(self, id_seudonimo: str) -> list[dict[str, Any]]:
        """Todos los mensajes de un estudiante."""
        return [m for m in self.estado["mensajes"] if m["id_seudonimo"] == id_seudonimo]

    def pendientes(self) -> list[dict[str, Any]]:
        """Bandeja del tutor: programados y por aprobar, ordenados por hora de envío."""
        return sorted((m for m in self.estado["mensajes"] if m["estado"] in PENDIENTES),
                      key=lambda m: m["envio_programado"])

    def bandeja_estudiante(self, id_seudonimo: str) -> list[dict[str, Any]]:
        """Mensajes que ya llegaron a la bandeja simulada del estudiante."""
        return sorted((m for m in self.mensajes_de(id_seudonimo) if m["estado"] == "ENVIADO"),
                      key=lambda m: m["enviado_en"])

    def _pendiente(self, id_mensaje: str) -> dict[str, Any]:
        m = self.mensaje(id_mensaje)
        if m["estado"] not in PENDIENTES:
            raise ValueError(f"{id_mensaje} ya no está pendiente ({m['estado']}).")
        return m

    def _entregar(self, m: dict[str, Any], cuando: datetime, sin_revision: bool) -> None:
        m.update({"estado": "ENVIADO", "enviado_en": _iso(cuando), "enviado_sin_revision": sin_revision})
        caso = self.estado["casos"][m["id_seudonimo"]]
        if caso["primer_envio"] is None:
            caso["primer_envio"] = _iso(cuando)
        self.ruta_bandeja.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ruta_bandeja, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: m[k] for k in ("id_mensaje", "id_seudonimo", "tipo", "canal", "texto",
                                                    "enviado_en", "enviado_sin_revision")},
                                ensure_ascii=False) + "\n")

    # ---- acciones del tutor -------------------------------------------------------
    def enviar_ahora(self, id_mensaje: str, actor: str = "tutor") -> dict[str, Any]:
        """Envía ya (y aprueba, si era una excepción)."""
        m = self._pendiente(id_mensaje)
        accion = "aprobar_y_enviar" if m["estado"] == "REQUIERE_APROBACION" else "enviar_ahora"
        self._entregar(m, self.ahora, sin_revision=False)
        self._decision(m, m["id_seudonimo"], actor, accion)
        self.guardar()
        return m

    def editar(self, id_mensaje: str, texto: str, actor: str = "tutor") -> dict[str, Any]:
        """Cambia el texto; el mensaje sigue en su estado y con la misma hora de envío."""
        m = self._pendiente(id_mensaje)
        problemas = problemas_invitacion(texto)
        if problemas:
            raise ValueError(f"El texto editado no cumple las reglas: {problemas}")
        m.update({"texto": texto, "editado": True})
        self._decision(m, m["id_seudonimo"], actor, "editar")
        self.guardar()
        return m

    def cancelar(self, id_mensaje: str, motivo: str, actor: str = "tutor") -> dict[str, Any]:
        """Cancela el envío; el motivo es obligatorio."""
        if not motivo.strip():
            raise ValueError("Cancelar requiere un motivo.")
        m = self._pendiente(id_mensaje)
        m.update({"estado": "CANCELADO", "motivo_cancelacion": motivo})
        self._decision(m, m["id_seudonimo"], actor, "cancelar", motivo)
        self.guardar()
        return m

    def contactar_en_persona(self, id_mensaje: str, motivo: str = "", actor: str = "tutor") -> dict[str, Any]:
        """El tutor contactará en persona: se cancela el envío automático."""
        m = self._pendiente(id_mensaje)
        m.update({"estado": "CONTACTO_PRESENCIAL", "motivo_cancelacion": motivo or "contacto en persona"})
        self._decision(m, m["id_seudonimo"], actor, "contactar_en_persona", motivo)
        self.guardar()
        return m

    # ---- acciones del estudiante ---------------------------------------------------
    def _cancelar_pendientes(self, id_seudonimo: str, solo_recordatorio: bool, motivo: str) -> int:
        n = 0
        for m in self.mensajes_de(id_seudonimo):
            if m["estado"] in PENDIENTES and (m["tipo"] == "recordatorio" or not solo_recordatorio):
                m.update({"estado": "CANCELADO", "motivo_cancelacion": motivo})
                self._decision(m, id_seudonimo, "sistema", "cancelar", motivo)
                n += 1
        return n

    def registrar_respuesta(self, id_seudonimo: str) -> None:
        """El estudiante respondió: no habrá recordatorio (y se cancela si estaba programado)."""
        caso = self.estado["casos"][id_seudonimo]
        caso["respondio"] = True
        self._cancelar_pendientes(id_seudonimo, solo_recordatorio=True, motivo="el estudiante respondió")
        self._decision(None, id_seudonimo, "estudiante", "responder")
        self.guardar()

    def no_quiero_mas(self, id_seudonimo: str) -> int:
        """Cancela todo lo programado para el estudiante, incluido el recordatorio."""
        caso = self.estado["casos"][id_seudonimo]
        caso["no_mas"] = True
        n = self._cancelar_pendientes(id_seudonimo, solo_recordatorio=False, motivo="pidió no recibir más")
        self._decision(None, id_seudonimo, "estudiante", "no_quiero_recibir_mas")
        self.guardar()
        return n

    def marcar_derivar_humano(self, id_seudonimo: str) -> None:
        """Un check-in pidió revisión humana: lo pendiente pasa a requerir aprobación."""
        caso = self.estado["casos"][id_seudonimo]
        caso["derivar_humano"] = True
        for m in self.mensajes_de(id_seudonimo):
            if m["estado"] == "PROGRAMADO":
                m["estado"] = "REQUIERE_APROBACION"
                m["excepciones"] = sorted(set(m["excepciones"]) | {"derivar_humano"})
        self._decision(None, id_seudonimo, "sistema", "checkin_derivar_humano")
        self.guardar()

    # ---- motor ---------------------------------------------------------------------
    def procesar(self) -> list[dict[str, Any]]:
        """Envía lo vencido sin revisión y programa el único recordatorio. Idempotente."""
        enviados: list[dict[str, Any]] = []
        cambio = True
        while cambio:
            cambio = False
            for m in self.estado["mensajes"]:
                if m["estado"] == "PROGRAMADO" and _dt(m["envio_programado"]) <= self.ahora:
                    self._entregar(m, _dt(m["envio_programado"]), sin_revision=True)
                    self._decision(m, m["id_seudonimo"], "sistema", "enviado_sin_revision")
                    enviados.append(m)
                    cambio = True
            for caso in self.estado["casos"].values():
                if (caso["primer_envio"] and not caso["recordatorio_creado"] and not caso["respondio"]
                        and not caso["no_mas"] and _dt(caso["primer_envio"]) + SEGUIMIENTO <= self.ahora):
                    caso["recordatorio_creado"] = True
                    texto = self.texto_recordatorio(caso) if self.texto_recordatorio else _recordatorio_fijo(caso)
                    self.crear_mensaje(caso["id_seudonimo"], texto, tipo="recordatorio",
                                       creado=_dt(caso["primer_envio"]) + SEGUIMIENTO)
                    cambio = True
        return enviados

    # ---- indicadores ---------------------------------------------------------------
    def sin_respuesta(self) -> list[str]:
        """Casos con recordatorio ya enviado y sin respuesta: el tutor decide si contacta en persona."""
        out = []
        for caso in self.estado["casos"].values():
            recs = [m for m in self.mensajes_de(caso["id_seudonimo"])
                    if m["tipo"] == "recordatorio" and m["estado"] == "ENVIADO"]
            if recs and not caso["respondio"] and not caso["no_mas"]:
                out.append(caso["id_seudonimo"])
        return out

    def pct_enviados_sin_revision(self) -> float:
        """% de mensajes enviados que salieron sin revisión del tutor."""
        env = [m for m in self.estado["mensajes"] if m["estado"] == "ENVIADO"]
        return 100.0 * sum(bool(m["enviado_sin_revision"]) for m in env) / len(env) if env else 0.0


def _recordatorio_fijo(caso: dict[str, Any]) -> str:
    from src.claude_client import RECORDATORIO_FIJO
    return RECORDATORIO_FIJO[caso["canal"]].replace("{carrera}", caso["carrera"])
