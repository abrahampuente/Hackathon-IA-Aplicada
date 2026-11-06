"""Envío REAL de correo, solo para la demo y solo a la lista blanca.

Reglas (autorizadas por el equipo, todo lo demás sigue prohibido):
- MODO_CORREO_REAL=0 (por defecto): no se abre ninguna conexión SMTP.
- Solo destinatarios en CORREOS_PERMITIDOS; cualquier otro se rechaza y se registra.
- Gmail SMTP (smtp.gmail.com:587 + STARTTLS) con SMTP_USUARIO y SMTP_CLAVE_APP de .env.
- La clave nunca se imprime ni se registra; los correos se registran enmascarados.
- Si falla o tarda más de 10 s, no se lanza excepción: se devuelve ok=False con el motivo.

Las variables se leen del entorno en cada llamada (así las pruebas pueden fijarlas).
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, TypedDict

from src import config

SMTP_HOST: str = "smtp.gmail.com"
SMTP_PUERTO: int = 587
TIMEOUT_S: float = 10.0
ASUNTO: str = "Un espacio de apoyo para tu primer año"
ASUNTO_PRUEBA: str = "Prueba de conexión del prototipo"
PIE: str = "\n\n--\nMensaje de prueba del prototipo, Hackathon IA Aplicada 2026."
CUERPO_PRUEBA: str = "Este es un correo de prueba fijo para verificar la conexión SMTP del prototipo."
AVISO_FALLO: str = "Envío real falló, se mostró en la bandeja simulada."
RUTA_LOG_CORREO: Path = config.DATA_DIR / "log_correo.jsonl"

# Fábrica de conexiones: las pruebas la reemplazan por un simulador.
SMTP_FACTORY: Callable[..., Any] = smtplib.SMTP


class ResultadoEnvio(TypedDict):
    ok: bool
    motivo: str
    hora: str
    segundos: float
    destinatario: str   # enmascarado


def modo_real() -> bool:
    """True solo si MODO_CORREO_REAL vale 1/true/si en el entorno."""
    return os.getenv("MODO_CORREO_REAL", "0").strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def permitidos() -> list[str]:
    """Lista blanca de destinatarios (minúsculas)."""
    return [x.strip().lower() for x in os.getenv("CORREOS_PERMITIDOS", "").split(",") if x.strip()]


def destinatario_demo() -> str | None:
    """Correo de contacto de EST-DEMO: el primero de la lista blanca (se usa solo al enviar)."""
    p = permitidos()
    return p[0] if p else None


def enmascarar(correo: str) -> str:
    """'ana.perez@gmail.com' -> 'a***@gmail.com' (+ hash corto para distinguir)."""
    if "@" not in correo:
        return "***"
    local, dominio = correo.split("@", 1)
    h = hashlib.sha256(correo.lower().encode()).hexdigest()[:6]
    return f"{local[:1]}***@{dominio}#{h}"


def _log(evento: dict[str, Any]) -> None:
    RUTA_LOG_CORREO.parent.mkdir(parents=True, exist_ok=True)
    with open(RUTA_LOG_CORREO, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **evento},
                            ensure_ascii=False) + "\n")


def _resultado(ok: bool, motivo: str, inicio: float, destinatario: str) -> ResultadoEnvio:
    r: ResultadoEnvio = {"ok": ok, "motivo": motivo, "hora": datetime.now().isoformat(timespec="seconds"),
                         "segundos": round(time.monotonic() - inicio, 2), "destinatario": enmascarar(destinatario)}
    _log({"resultado": "enviado" if ok else "no_enviado", **r})
    return r


def _enviar_smtp(usuario: str, clave: str, msg: EmailMessage) -> None:
    with SMTP_FACTORY(SMTP_HOST, SMTP_PUERTO, timeout=TIMEOUT_S) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(usuario, clave)
        s.send_message(msg)


def enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> ResultadoEnvio:
    """Envía un correo real si el modo está activo y el destinatario está en la lista blanca.

    Nunca lanza excepción; el pie de prueba se agrega siempre.
    """
    inicio = time.monotonic()
    if not modo_real():
        return _resultado(False, "modo_simulado", inicio, destinatario)
    if destinatario.strip().lower() not in permitidos():
        return _resultado(False, "fuera_de_lista_blanca", inicio, destinatario)
    usuario = os.getenv("SMTP_USUARIO", "").strip()
    clave = os.getenv("SMTP_CLAVE_APP", "").strip()
    if not usuario or not clave:
        return _resultado(False, "sin_credenciales", inicio, destinatario)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = usuario, destinatario.strip(), asunto
    msg.set_content(cuerpo + PIE)
    ejecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    futuro = ejecutor.submit(_enviar_smtp, usuario, clave, msg)
    try:
        futuro.result(timeout=TIMEOUT_S)
        return _resultado(True, "enviado", inicio, destinatario)
    except concurrent.futures.TimeoutError:
        return _resultado(False, "timeout", inicio, destinatario)
    except smtplib.SMTPAuthenticationError as exc:
        return _resultado(False, f"autenticacion_{exc.smtp_code}", inicio, destinatario)
    except Exception as exc:  # noqa: BLE001 - nunca propagar; solo el tipo, jamás el mensaje
        return _resultado(False, type(exc).__name__, inicio, destinatario)
    finally:
        ejecutor.shutdown(wait=False, cancel_futures=True)


def probar_conexion() -> ResultadoEnvio:
    """Envía el correo de prueba fijo al primer destinatario de la lista blanca."""
    dest = destinatario_demo()
    if dest is None:
        return _resultado(False, "lista_blanca_vacia", time.monotonic(), "")
    return enviar_correo(dest, ASUNTO_PRUEBA, CUERPO_PRUEBA)
