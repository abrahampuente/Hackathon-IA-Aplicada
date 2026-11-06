"""Regenera datos, entrena, predice, audita y deja todo listo para `streamlit run app.py`.

Uso:  python run_demo.py
"""
from __future__ import annotations

import json
import sys
from typing import Any

import pandas as pd

from src import auditoria, config, generar_datos, modelo


def ejecutar_pipeline() -> dict[str, Any]:
    """Pipeline completo. Devuelve métricas globales y el bloque de auditoría."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/5] Generando datos sintéticos...", flush=True)
    ds = generar_datos.generar_todo()
    est = ds.estudiantes
    y = est["deserto"]

    print("[2/5] Construyendo features y entrenando (base y robusto)...", flush=True)
    feats = modelo.construir_features(est)
    m_base = modelo.entrenar(feats, y, config.FEATURES_BASE)
    m_rob = modelo.entrenar(feats, y, config.FEATURES_ROBUSTAS)

    print("[3/5] Auditando sesgos antes y después de mitigar...", flush=True)
    oof_base = modelo.probabilidades_fuera_de_muestra(feats, y, config.FEATURES_BASE) * 100
    oof_rob = modelo.probabilidades_fuera_de_muestra(feats, y, config.FEATURES_ROBUSTAS) * 100
    flag = feats["dato_asistencia_poco_confiable"].to_numpy()
    sub = (auditoria.agregar_subgrupo(est)[auditoria.SUBGRUPO] == "mujer+vespertina").to_numpy()
    reporte = {
        "descripcion": ("Métricas por grupo con predicciones fuera de muestra (5-fold estratificado). "
                        "Alerta = riesgo >= UMBRAL_MEDIO. Antes: features sobre asistencia registrada. "
                        "Después: asistencia suavizada con mediana móvil de 3 semanas."),
        "umbral_alerta_pct": config.UMBRAL_MEDIO,
        "umbral_disparidad_fp_pp": config.UMBRAL_DISPARIDAD_FP_PP,
        "min_negativos_grupo": config.MIN_NEGATIVOS_GRUPO,
        "antes": {"features": list(config.FEATURES_BASE), **auditoria.resumen_etapa(oof_base, est)},
        "despues": {"features": list(config.FEATURES_ROBUSTAS), **auditoria.resumen_etapa(oof_rob, est)},
        "referencia_sintetica": {
            "nota": ("Usa el riesgo REAL del generador (no disponible en la práctica). Indica qué parte "
                     "de la brecha es conducta real y no sesgo de registro."),
            **auditoria.resumen_etapa(ds.latentes["prob_real"].to_numpy() * 100, est),
        },
        "bandera_dato_poco_confiable": {
            "tasa_mujer_vespertina": float(flag[sub].mean()),
            "tasa_resto": float(flag[~sub].mean()),
            "entra_al_modelo": False,
        },
    }
    auditoria.guardar_json(reporte, config.RUTA_AUDITORIA_JSON)
    tabla = pd.concat([
        auditoria.metricas_por_grupo(oof_base, est).assign(etapa="antes"),
        auditoria.metricas_por_grupo(oof_rob, est).assign(etapa="después"),
    ])
    generar_datos.guardar_csv(tabla, config.RUTA_AUDITORIA)

    print("[4/5] Prediciendo riesgo con el modelo robusto...", flush=True)
    pred = modelo.predecir(m_rob, feats, est)
    generar_datos.guardar_csv(pred, config.RUTA_PREDICCIONES)
    modelo.guardar_modelo(m_rob)

    print("[5/5] Guardando métricas...", flush=True)
    metricas = {
        "modelo_produccion": "robusto",
        "features": list(m_rob.features),
        "robusto": m_rob.metricas,
        "base": m_base.metricas,
        "coeficientes_robusto": dict(zip(m_rob.features,
                                         map(float, m_rob.estimador.named_steps["logit"].coef_[0]))),
        "distribucion_niveles": pred["nivel"].value_counts().to_dict(),
    }
    config.RUTA_METRICAS.write_text(json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8")
    config.RUTA_BANDEJA.touch(exist_ok=True)
    return {"metricas": metricas, "auditoria": reporte}


def main() -> int:
    r = ejecutar_pipeline()
    m, a = r["metricas"], r["auditoria"]
    print(f"Listo. AUC test robusto {m['robusto']['auc_test']:.3f} (base {m['base']['auc_test']:.3f}). "
          f"Brecha FP mujer+vespertina: {a['antes']['brecha_fp_subgrupo_pp']:.1f} -> "
          f"{a['despues']['brecha_fp_subgrupo_pp']:.1f} pp. Niveles: {m['distribucion_niveles']}")
    print("Siguiente paso: streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
