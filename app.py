"""Panel del tutor (Streamlit).

Uso:  streamlit run app.py   (antes: python run_demo.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import auditoria, config  # noqa: E402


def cargar_csv(ruta: Path) -> pd.DataFrame:
    """Lee un CSV de data/ o devuelve un DataFrame vacío si aún no existe."""
    if not ruta.is_file() or ruta.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(ruta)


def cargar_bandeja(ruta: Path) -> list[dict]:
    """Lee la bandeja simulada (JSONL). Ningún mensaje se envía de verdad."""
    if not ruta.is_file():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


st.set_page_config(page_title="Alerta temprana - Panel del tutor", layout="wide")
st.title("Alerta temprana y acompañamiento")
st.caption("Datos sintéticos. Ningún mensaje se envía de verdad. "
           f"Umbrales: medio ≥ {config.UMBRAL_MEDIO}%, alto > {config.UMBRAL_ALTO}%."
           + (" · Modo OFFLINE" if config.OFFLINE else ""))

predicciones = cargar_csv(config.RUTA_PREDICCIONES)
tab_tutor, tab_bandeja, tab_auditoria = st.tabs(["Panel del tutor", "Bandeja simulada", "Auditoría de sesgos"])

with tab_tutor:
    if predicciones.empty:
        st.info("Aún no hay predicciones. Ejecuta `python run_demo.py`.")
    else:
        altos = predicciones[predicciones["nivel"] == "alto"]
        st.subheader(f"Casos de nivel alto para revisión ({len(altos)})")
        st.dataframe(altos, use_container_width=True)

with tab_bandeja:
    mensajes = cargar_bandeja(config.RUTA_BANDEJA)
    st.write(f"{len(mensajes)} invitaciones simuladas (nivel medio).")
    for m in mensajes:
        st.text(m.get("texto", ""))

with tab_auditoria:
    st.write(auditoria.resumen_texto(cargar_csv(config.RUTA_AUDITORIA)))
