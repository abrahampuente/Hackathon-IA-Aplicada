"""Regenera datos, entrena, predice, audita y deja todo listo para `streamlit run app.py`.

Uso:  python run_demo.py
"""
from __future__ import annotations

import sys

from src import auditoria, config, generar_datos, modelo


def main() -> int:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] Generando datos sintéticos...")
    estudiantes, registros = generar_datos.generar_todo()

    print("[2/4] Construyendo features y entrenando...")
    features = modelo.construir_features(registros)
    etiquetas = estudiantes.get("deserta")
    m = modelo.entrenar(features, etiquetas)

    print("[3/4] Prediciendo riesgo...")
    predicciones = modelo.predecir(m, features)
    generar_datos.guardar_csv(predicciones, config.RUTA_PREDICCIONES)

    print("[4/4] Auditando sesgos...")
    tabla = auditoria.auditar_sesgos(predicciones, estudiantes)
    generar_datos.guardar_csv(tabla, config.RUTA_AUDITORIA)
    config.RUTA_BANDEJA.touch(exist_ok=True)

    print(f"Listo: {len(estudiantes)} estudiantes, {len(predicciones)} predicciones en {config.DATA_DIR}")
    print("Siguiente paso: streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
