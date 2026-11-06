"""Auditoría de sesgos: compara el comportamiento del modelo entre grupos.

Las variables demográficas se cruzan con las predicciones DESPUÉS de predecir;
nunca se entregan al modelo.

Alerta = nivel medio o alto (riesgo >= UMBRAL_MEDIO).
Tasa de falsos positivos (FP) = alertas entre quienes NO desertaron.
Recall = alertas entre quienes SÍ desertaron.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src import config

VARIABLES: tuple[str, ...] = ("genero", "jornada", "sede", "trabaja")
SUBGRUPO: str = "mujer_vespertina"   # subgrupo con sesgo de registro inyectado
COLUMNAS_AUDITORIA: list[str] = [
    "variable", "grupo", "n", "n_negativos", "n_positivos",
    "tasa_alerta", "tasa_fp", "recall", "riesgo_medio_negativos",
]


def agregar_subgrupo(estudiantes: pd.DataFrame) -> pd.DataFrame:
    """Copia de `estudiantes` con la columna `mujer_vespertina` (solo para auditar)."""
    df = estudiantes.copy()
    es = (df["genero"] == "F") & (df["jornada"] == "vespertina")
    df[SUBGRUPO] = np.where(es, "mujer+vespertina", "resto")
    return df


def metricas_por_grupo(
    prob_riesgo_pct: np.ndarray | pd.Series,
    estudiantes: pd.DataFrame,
    variables: tuple[str, ...] = VARIABLES + (SUBGRUPO,),
) -> pd.DataFrame:
    """Tasa de alerta, tasa de FP, recall y riesgo medio de no desertores por grupo."""
    df = agregar_subgrupo(estudiantes)
    prob = np.asarray(prob_riesgo_pct, dtype=float)
    alerta = prob >= config.UMBRAL_MEDIO
    y = df["deserto"].to_numpy(dtype=int)
    filas = []
    for var in variables:
        for grupo in sorted(df[var].astype(str).unique()):
            m = (df[var].astype(str) == grupo).to_numpy()
            neg, pos = m & (y == 0), m & (y == 1)
            filas.append({
                "variable": var, "grupo": grupo, "n": int(m.sum()),
                "n_negativos": int(neg.sum()), "n_positivos": int(pos.sum()),
                "tasa_alerta": float(alerta[m].mean()),
                "tasa_fp": float(alerta[neg].mean()) if neg.any() else float("nan"),
                "recall": float(alerta[pos].mean()) if pos.any() else float("nan"),
                "riesgo_medio_negativos": float(prob[neg].mean()) if neg.any() else float("nan"),
            })
    return pd.DataFrame(filas, columns=COLUMNAS_AUDITORIA)


def disparidades(
    tabla: pd.DataFrame,
    umbral_pp: float = config.UMBRAL_DISPARIDAD_FP_PP,
    min_negativos: int = config.MIN_NEGATIVOS_GRUPO,
) -> dict[str, dict[str, Any]]:
    """Por variable: brecha máxima de FP (pp) entre grupos con muestra suficiente y si supera el umbral."""
    salida: dict[str, dict[str, Any]] = {}
    for var, t in tabla.groupby("variable", sort=False):
        validos = t[t["n_negativos"] >= min_negativos]
        excluidos = t.loc[t["n_negativos"] < min_negativos, "grupo"].tolist()
        if len(validos) < 2:
            salida[var] = {"brecha_fp_pp": None, "disparidad": False, "excluidos_por_n": excluidos}
            continue
        brecha = (validos["tasa_fp"].max() - validos["tasa_fp"].min()) * 100
        salida[var] = {
            "brecha_fp_pp": round(float(brecha), 2),
            "disparidad": bool(brecha > umbral_pp),
            "grupo_mayor_fp": str(validos.loc[validos["tasa_fp"].idxmax(), "grupo"]),
            "excluidos_por_n": excluidos,
        }
    return salida


def brecha_subgrupo(tabla: pd.DataFrame) -> float:
    """FP(mujer+vespertina) - FP(resto), en puntos porcentuales."""
    t = tabla[tabla["variable"] == SUBGRUPO].set_index("grupo")
    return float((t.loc["mujer+vespertina", "tasa_fp"] - t.loc["resto", "tasa_fp"]) * 100)


def brecha_subgrupo_vs_vespertina(prob_riesgo_pct: np.ndarray, estudiantes: pd.DataFrame) -> float:
    """FP(mujer+vespertina) - FP(resto de vespertina), en pp: aísla el sesgo del efecto jornada."""
    df = agregar_subgrupo(estudiantes)
    alerta = np.asarray(prob_riesgo_pct, dtype=float) >= config.UMBRAL_MEDIO
    neg = df["deserto"].to_numpy() == 0
    vesp = (df["jornada"] == "vespertina").to_numpy()
    sub = (df[SUBGRUPO] == "mujer+vespertina").to_numpy()
    return float((alerta[sub & neg].mean() - alerta[vesp & ~sub & neg].mean()) * 100)


def auditar_sesgos(
    predicciones: pd.DataFrame,
    estudiantes: pd.DataFrame,
    variables: tuple[str, ...] = VARIABLES + (SUBGRUPO,),
) -> pd.DataFrame:
    """Une predicciones (id_seudonimo, prob_riesgo) con el perfil y calcula métricas por grupo."""
    df = estudiantes.merge(predicciones[["id_seudonimo", "prob_riesgo"]], on="id_seudonimo", how="inner")
    return metricas_por_grupo(df["prob_riesgo"].to_numpy(), df, variables)


def resumen_etapa(prob_riesgo_pct: np.ndarray, estudiantes: pd.DataFrame) -> dict[str, Any]:
    """Bloque de auditoría completo para una etapa (antes o después de mitigar)."""
    tabla = metricas_por_grupo(prob_riesgo_pct, estudiantes)
    return {
        "por_grupo": json.loads(tabla.to_json(orient="records")),
        "disparidades": disparidades(tabla),
        "brecha_fp_subgrupo_pp": round(brecha_subgrupo(tabla), 2),
        "brecha_fp_subgrupo_vs_vespertina_pp": round(brecha_subgrupo_vs_vespertina(prob_riesgo_pct, estudiantes), 2),
    }


def guardar_json(datos: dict[str, Any], ruta: Path = config.RUTA_AUDITORIA_JSON) -> Path:
    """Escribe un dict como JSON UTF-8 legible."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def brechas(auditoria: pd.DataFrame, metrica: str = "tasa_fp") -> dict[str, float]:
    """Diferencia máxima (pp) entre grupos de cada variable para `metrica`."""
    if auditoria.empty:
        return {}
    return {v: round(float((t[metrica].max() - t[metrica].min()) * 100), 2)
            for v, t in auditoria.groupby("variable", sort=False)}


def resumen_texto(auditoria: pd.DataFrame) -> str:
    """Resumen legible de la auditoría para el panel (tabla con columna `etapa`)."""
    if auditoria.empty:
        return "Aún no hay auditoría. Ejecuta `python run_demo.py`."
    lineas = []
    for etapa, t in auditoria.groupby("etapa", sort=False) if "etapa" in auditoria else [("", auditoria)]:
        b = brechas(t)
        sub = t[(t["variable"] == SUBGRUPO)].set_index("grupo")["tasa_fp"]
        brecha_sub = (sub.get("mujer+vespertina", np.nan) - sub.get("resto", np.nan)) * 100
        lineas.append(f"**{etapa or 'Auditoría'}**: brecha de falsos positivos mujer+vespertina vs resto = "
                      f"{brecha_sub:.1f} pp; brechas por variable: "
                      + ", ".join(f"{k} {v:.1f} pp" for k, v in b.items() if k != SUBGRUPO))
    return "\n\n".join(lineas)
