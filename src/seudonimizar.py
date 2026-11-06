"""Seudonimización: nada identificable sale hacia la API de Claude.

- `payload_para_claude` arma el ÚNICO payload por estudiante que puede salir:
  id_seudonimo, nivel, riesgo, las 3 razones y la carrera.
- El nombre nunca sale: los textos traen el marcador {NOMBRE} y se completa
  localmente con `insertar_nombre`.
- Los textos libres (check-ins) pasan por `redactar_pii` antes de salir.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Any

import pandas as pd

COLUMNAS_IDENTIFICADORAS: tuple[str, ...] = (
    "nombre_ficticio", "correo_ficticio", "nombre", "rut", "email", "correo", "telefono",
)
CAMPOS_PAYLOAD: tuple[str, ...] = ("id_seudonimo", "nivel", "riesgo", "razones", "carrera")
MARCADOR_NOMBRE: str = "{NOMBRE}"

_RE_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]\b")
_RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RE_TELEFONO = re.compile(r"(?:\+?56\s?)?\b9\s?\d{4}\s?\d{4}\b")


def seudonimo(id_estudiante: str, sal: str) -> str:
    """Seudónimo estable y no reversible sin la sal (p. ej. 'EST-3f9a1c')."""
    digest = hmac.new(sal.encode(), str(id_estudiante).encode(), hashlib.sha256).hexdigest()
    return f"EST-{digest[:6]}"


def seudonimizar_df(df: pd.DataFrame, sal: str) -> pd.DataFrame:
    """Reemplaza `id_seudonimo` por un seudónimo con sal y elimina las columnas identificadoras."""
    out = df.drop(columns=[c for c in COLUMNAS_IDENTIFICADORAS if c in df.columns]).copy()
    if "id_seudonimo" in out:
        out["id_seudonimo"] = [seudonimo(i, sal) for i in out["id_seudonimo"]]
    return out


def contiene_pii(texto: str) -> bool:
    """True si el texto parece contener RUT, correo o teléfono."""
    return bool(_RE_RUT.search(texto) or _RE_CORREO.search(texto) or _RE_TELEFONO.search(texto))


def redactar_pii(texto: str) -> str:
    """Reemplaza RUT, correos y teléfonos por [dato oculto]."""
    for patron in (_RE_CORREO, _RE_RUT, _RE_TELEFONO):
        texto = patron.sub("[dato oculto]", texto)
    return texto


def payload_para_claude(estudiante: Mapping[str, Any]) -> dict[str, Any]:
    """Payload mínimo por estudiante: id_seudonimo, nivel, riesgo (0-100), 3 razones y carrera.

    Acepta una fila con `prob_riesgo` o `riesgo`, y `razon_1..3` o `razones`.
    Cualquier otro campo (nombre, correo, demografía, notas crudas) se descarta.
    """
    razones = estudiante.get("razones")
    if razones is None:
        razones = [estudiante.get(f"razon_{k}", "") for k in (1, 2, 3)]
    riesgo = estudiante.get("riesgo", estudiante.get("prob_riesgo"))
    payload = {
        "id_seudonimo": str(estudiante["id_seudonimo"]),
        "nivel": str(estudiante["nivel"]),
        "riesgo": round(float(riesgo), 1),
        "razones": [str(r) for r in list(razones)[:3]],
        "carrera": str(estudiante["carrera"]),
    }
    return preparar_payload(payload)


def preparar_payload(datos: dict[str, Any]) -> dict[str, Any]:
    """Valida un dict antes de enviarlo a Claude; lanza ValueError si hay PII o columnas identificadoras."""
    prohibidas = [k for k in datos if k in COLUMNAS_IDENTIFICADORAS]
    if prohibidas:
        raise ValueError(f"Campos identificadores en el payload: {prohibidas}")
    texto = repr(datos)
    if contiene_pii(texto):
        raise ValueError("El payload contiene datos personales (RUT, correo o teléfono).")
    return dict(datos)


def insertar_nombre(texto: str, nombre: str) -> str:
    """Completa localmente el marcador {NOMBRE}; nunca se hace antes de llamar a Claude."""
    return texto.replace(MARCADOR_NOMBRE, nombre)
