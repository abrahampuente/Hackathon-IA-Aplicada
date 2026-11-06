"""Modelo interpretable de riesgo de deserción.

Usa SOLO conducta académica (`config.FEATURES_MODELO`): asistencia y notas.
Las variables demográficas nunca entran: `validar_features` lo hace cumplir.

Modelo: regresión logística con escalado estándar, split 70/30 estratificado y
semilla fija. Cada razón es una contribución = coeficiente x valor estandarizado.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src import config

Nivel = Literal["bajo", "medio", "alto"]
COLUMNAS_PREDICCION: list[str] = [
    "id_seudonimo", "prob_riesgo", "nivel", "razon_1", "razon_2", "razon_3",
    "dato_asistencia_poco_confiable",
]


@dataclass
class ModeloRiesgo:
    """Pipeline entrenado (escalado + regresión logística) y sus metadatos."""

    estimador: Pipeline | None = None
    features: tuple[str, ...] = config.FEATURES_MODELO
    metricas: dict[str, float] = field(default_factory=dict)
    ids_test: list[str] = field(default_factory=list)


class Explicacion(TypedDict):
    id_seudonimo: str
    riesgo_pct: float
    nivel: Nivel
    razones: list[str]
    contribuciones: dict[str, float]
    dato_asistencia_poco_confiable: bool


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------
def validar_features(columnas: list[str] | tuple[str, ...]) -> None:
    """Lanza ValueError si alguna columna es demográfica o sustituta prohibida."""
    prohibidas = sorted(set(columnas) & set(config.VARIABLES_PROHIBIDAS))
    if prohibidas:
        raise ValueError(f"Variables prohibidas como entrada del modelo: {prohibidas}")


def suavizar_asistencia(asistencia: np.ndarray) -> np.ndarray:
    """Mediana móvil de 3 semanas (extremos con la regla de Tukey).

    Elimina caídas aisladas de una semana (p. ej. marcas erróneas) sin borrar
    caídas sostenidas.
    """
    a = np.asarray(asistencia, dtype=float)
    s = a.copy()
    s[:, 1:-1] = np.median(np.stack([a[:, :-2], a[:, 1:-1], a[:, 2:]]), axis=0)
    s[:, 0] = np.median(np.stack([a[:, 0], s[:, 1], 3 * s[:, 1] - 2 * s[:, 2]]), axis=0)
    s[:, -1] = np.median(np.stack([a[:, -1], s[:, -2], 3 * s[:, -2] - 2 * s[:, -3]]), axis=0)
    return np.clip(s, 0, 100)


def _tendencia(a: np.ndarray) -> np.ndarray:
    """Promedio de las últimas 3 semanas menos el de las primeras 3 (pp)."""
    return a[:, -3:].mean(axis=1) - a[:, :3].mean(axis=1)


def construir_features(estudiantes: pd.DataFrame) -> pd.DataFrame:
    """Calcula features base y robustas (una fila por estudiante) desde el export.

    Incluye `dato_asistencia_poco_confiable`, bandera informativa para el tutor
    que NO entra al modelo.
    """
    asis = estudiantes[list(config.COLS_ASISTENCIA)].to_numpy(dtype=float)
    p1 = estudiantes[[c for c in config.COLS_NOTAS if c.endswith("_p1")]].to_numpy(dtype=float)
    p2 = estudiantes[[c for c in config.COLS_NOTAS if c.endswith("_p2")]].to_numpy(dtype=float)
    notas = np.concatenate([p1, p2], axis=1)
    suave = suavizar_asistencia(asis)
    caidas = ((suave - asis) >= config.CAIDA_AISLADA_PP).sum(axis=1)

    f = pd.DataFrame({"id_seudonimo": estudiantes["id_seudonimo"].to_numpy()})
    f["asistencia_promedio"] = asis.mean(axis=1)
    f["asistencia_tendencia"] = _tendencia(asis)
    f["semanas_bajo_75"] = (asis < config.UMBRAL_SEMANA_BAJA).sum(axis=1)
    f["asistencia_mediana"] = np.median(suave, axis=1)
    f["asistencia_tendencia_robusta"] = _tendencia(suave)
    f["semanas_bajo_75_robusta"] = (suave < config.UMBRAL_SEMANA_BAJA).sum(axis=1)
    f["nota_promedio"] = notas.mean(axis=1)
    f["notas_rojas"] = (notas < 4.0).sum(axis=1)
    f["cambio_parciales"] = p2.mean(axis=1) - p1.mean(axis=1)
    f["dato_asistencia_poco_confiable"] = caidas >= config.MIN_CAIDAS_POCO_CONFIABLE
    return f


# --------------------------------------------------------------------------
# Entrenamiento y predicción
# --------------------------------------------------------------------------
def _pipeline() -> Pipeline:
    """Escalado estándar + regresión logística determinista."""
    return Pipeline([
        ("escalado", StandardScaler()),
        ("logit", LogisticRegression(max_iter=1000, random_state=config.SEMILLA)),
    ])


def entrenar(
    features: pd.DataFrame,
    etiquetas: pd.Series,
    columnas: tuple[str, ...] = config.FEATURES_MODELO,
    semilla: int = config.SEMILLA,
) -> ModeloRiesgo:
    """Entrena con split 70/30 estratificado y reporta AUC en test."""
    validar_features(columnas)
    X = features[list(columnas)].to_numpy(dtype=float)
    y = np.asarray(etiquetas, dtype=int)
    ids = features["id_seudonimo"].to_numpy()
    X_tr, X_te, y_tr, y_te, _, ids_te = train_test_split(
        X, y, ids, test_size=0.30, stratify=y, random_state=semilla)
    pipe = _pipeline().fit(X_tr, y_tr)
    auc = roc_auc_score(y_te, pipe.predict_proba(X_te)[:, 1])
    metricas = {
        "auc_test": float(auc),
        "auc_train": float(roc_auc_score(y_tr, pipe.predict_proba(X_tr)[:, 1])),
        "n_train": int(len(y_tr)), "n_test": int(len(y_te)),
        "tasa_desercion_train": float(y_tr.mean()), "tasa_desercion_test": float(y_te.mean()),
    }
    return ModeloRiesgo(estimador=pipe, features=tuple(columnas), metricas=metricas,
                        ids_test=[str(i) for i in ids_te])


def probabilidades_fuera_de_muestra(
    features: pd.DataFrame,
    etiquetas: pd.Series,
    columnas: tuple[str, ...] = config.FEATURES_MODELO,
    semilla: int = config.SEMILLA,
) -> np.ndarray:
    """Probabilidades 5-fold estratificadas: cada estudiante es predicho por un modelo que no lo vio.

    Se usan para la auditoría, para medir sesgo sobre las 600 filas sin sobreajuste.
    """
    validar_features(columnas)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=semilla)
    return cross_val_predict(_pipeline(), features[list(columnas)].to_numpy(dtype=float),
                             np.asarray(etiquetas, dtype=int), cv=cv, method="predict_proba")[:, 1]


def nivel(riesgo: float) -> Nivel:
    """Traduce un % de riesgo (0-100) a bajo | medio | alto según config."""
    if riesgo > config.UMBRAL_ALTO:
        return "alto"
    if riesgo >= config.UMBRAL_MEDIO:
        return "medio"
    return "bajo"


def nivel_de_riesgo(prob_pct: float) -> Nivel:
    """Alias de `nivel` (compatibilidad con ciclos anteriores)."""
    return nivel(prob_pct)


def contribuciones(modelo: ModeloRiesgo, features: pd.DataFrame) -> pd.DataFrame:
    """Contribución de cada feature al logit: coeficiente x valor estandarizado."""
    escalado = modelo.estimador.named_steps["escalado"]
    coef = modelo.estimador.named_steps["logit"].coef_[0]
    z = escalado.transform(features[list(modelo.features)].to_numpy(dtype=float))
    return pd.DataFrame(z * coef, columns=list(modelo.features), index=features.index)


def _pct(x: float) -> str:
    return f"{x:.0f}%"


def _dec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _texto_razon(feature: str, fila_feat: pd.Series, fila_est: pd.Series, sube: bool,
                 media: float | None = None) -> str:
    """Redacta una contribución en lenguaje simple para el tutor.

    `media` es el promedio del curso para esa feature (del escalado), usado como referencia.
    """
    efecto = "sube el riesgo" if sube else "baja el riesgo"
    asis = np.array([[fila_est[c] for c in config.COLS_ASISTENCIA]], dtype=float)
    suave = suavizar_asistencia(asis)[0] if "robusta" in feature or feature == "asistencia_mediana" else asis[0]
    if feature in ("asistencia_tendencia", "asistencia_tendencia_robusta"):
        ini, fin = suave[:3].mean(), suave[-3:].mean()
        if fin <= ini - 5:
            bajo = np.nonzero(suave <= ini - 5)[0]
            semana = int(bajo[0]) + 1 if len(bajo) else len(suave)
            txt = f"la asistencia bajó de {_pct(ini)} a {_pct(fin)} desde la semana {semana}"
            if media is not None:
                txt += (f", más que la caída típica del curso ({-media:.0f} puntos)" if sube
                        else f", menos que la caída típica del curso ({-media:.0f} puntos)")
        elif fin >= ini + 5:
            txt = f"la asistencia subió de {_pct(ini)} a {_pct(fin)}"
        else:
            txt = f"la asistencia se mantuvo estable cerca de {_pct((ini + fin) / 2)}"
    elif feature in ("asistencia_promedio", "asistencia_mediana"):
        txt = f"su asistencia típica es {_pct(fila_feat[feature])}"
        if media is not None:
            txt += f" (curso: {_pct(media)})"
    elif feature in ("semanas_bajo_75", "semanas_bajo_75_robusta"):
        n = int(fila_feat[feature])
        txt = (f"tuvo {n} de {config.N_SEMANAS} semanas con asistencia bajo 75%" if n
               else "no tuvo semanas con asistencia bajo 75%")
    elif feature == "nota_promedio":
        txt = f"su promedio de notas es {_dec(fila_feat[feature])}"
        if media is not None:
            txt += f" (curso: {_dec(media)})"
    elif feature == "notas_rojas":
        n = int(fila_feat[feature])
        total = len(config.COLS_NOTAS)
        txt = f"tiene {n} de {total} notas bajo 4,0" if n else "no tiene notas bajo 4,0"
    elif feature == "cambio_parciales":
        d = float(fila_feat[feature])
        if d <= -0.2:
            txt = f"sus notas bajaron {_dec(-d)} puntos entre el parcial 1 y el 2"
        elif d >= 0.2:
            txt = f"sus notas subieron {_dec(d)} puntos entre el parcial 1 y el 2"
        else:
            txt = "sus notas se mantuvieron entre el parcial 1 y el 2"
    else:
        txt = feature.replace("_", " ")
    return f"{txt[0].upper()}{txt[1:]} ({efecto})."


def _razones(modelo: ModeloRiesgo, feats: pd.DataFrame, est: pd.DataFrame) -> list[list[str]]:
    """Las 3 contribuciones de mayor magnitud por estudiante, redactadas."""
    contrib = contribuciones(modelo, feats)
    medias = dict(zip(modelo.features, modelo.estimador.named_steps["escalado"].mean_))
    est_idx = est.set_index("id_seudonimo")
    salida = []
    for i, fila in feats.iterrows():
        c = contrib.loc[i]
        top = c.abs().sort_values(ascending=False, kind="stable").index[:3]
        fe = est_idx.loc[fila["id_seudonimo"]]
        salida.append([_texto_razon(f, fila, fe, c[f] > 0, float(medias[f])) for f in top])
    return salida


def predecir(modelo: ModeloRiesgo, features: pd.DataFrame,
             estudiantes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Devuelve % de riesgo, nivel, las 3 razones principales y la bandera de dato poco confiable."""
    if modelo.estimador is None or features.empty:
        return pd.DataFrame(columns=COLUMNAS_PREDICCION)
    prob = modelo.estimador.predict_proba(features[list(modelo.features)].to_numpy(dtype=float))[:, 1] * 100
    out = pd.DataFrame({"id_seudonimo": features["id_seudonimo"].to_numpy(), "prob_riesgo": np.round(prob, 1)})
    out["nivel"] = [nivel(p) for p in out["prob_riesgo"]]
    if estudiantes is not None:
        razones = _razones(modelo, features, estudiantes)
        for k in range(3):
            out[f"razon_{k + 1}"] = [r[k] for r in razones]
    else:
        for k in range(3):
            out[f"razon_{k + 1}"] = ""
    out["dato_asistencia_poco_confiable"] = features["dato_asistencia_poco_confiable"].to_numpy()
    return out[COLUMNAS_PREDICCION]


# --------------------------------------------------------------------------
# Persistencia y explicación individual
# --------------------------------------------------------------------------
def guardar_modelo(modelo: ModeloRiesgo, ruta: Path = config.RUTA_MODELO) -> Path:
    """Serializa el modelo con pickle."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "wb") as fh:
        pickle.dump(modelo, fh)
    return ruta


def cargar_modelo(ruta: Path = config.RUTA_MODELO) -> ModeloRiesgo:
    """Carga un modelo guardado por `guardar_modelo` (solo archivos generados por este proyecto)."""
    with open(ruta, "rb") as fh:
        return pickle.load(fh)


def explicar(id_seudonimo: str, modelo: ModeloRiesgo | None = None,
             estudiantes: pd.DataFrame | None = None) -> Explicacion:
    """Riesgo en % (0-100), nivel y las 3 contribuciones principales en lenguaje simple.

    Si no se entregan, carga `data/modelo.pkl` y `data/estudiantes.csv`.
    """
    modelo = modelo or cargar_modelo()
    if estudiantes is None:
        estudiantes = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    fila = estudiantes[estudiantes["id_seudonimo"] == id_seudonimo]
    if fila.empty:
        raise KeyError(f"No existe {id_seudonimo}")
    feats = construir_features(fila.reset_index(drop=True))
    pred = predecir(modelo, feats, fila)
    contrib = contribuciones(modelo, feats).iloc[0]
    return {
        "id_seudonimo": id_seudonimo,
        "riesgo_pct": float(pred.loc[0, "prob_riesgo"]),
        "nivel": pred.loc[0, "nivel"],
        "razones": [pred.loc[0, f"razon_{k}"] for k in (1, 2, 3)],
        "contribuciones": {k: round(float(v), 4) for k, v in contrib.items()},
        "dato_asistencia_poco_confiable": bool(feats.loc[0, "dato_asistencia_poco_confiable"]),
    }
