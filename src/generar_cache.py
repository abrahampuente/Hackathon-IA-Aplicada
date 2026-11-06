"""Ejecuta los 4 usos de Claude sobre los 12 casos demo y guarda data/cache_claude.json.

Uso:  python -m src.generar_cache            (online si hay ANTHROPIC_API_KEY; si no, plantillas locales)
      OFFLINE=1 python -m src.generar_cache  (solo lee caché)
"""
from __future__ import annotations

import sys
from typing import Any

import pandas as pd

from src import apoyos, auditoria, config, plan_estudio
from src.claude_client import ClienteClaude
from src.seudonimizar import payload_para_claude

# Ampliación A: check-ins para sugerir apoyos (texto, necesidad ya clasificada).
CHECKINS_APOYOS: list[tuple[str, str]] = [
    ("No tengo computador para hacer los trabajos en casa.", "logistica"),
    ("No me alcanza para los pasajes de esta semana.", "economica"),
    ("No puedo comprar el libro que pide el profe de especialidad.", "economica"),
    ("Tengo un problema económico y no sé si podré pagar el arancel.", "economica"),
    ("No entiendo la materia de matemática y tengo prueba pronto.", "academica"),
    ("Ando con mucha ansiedad y me cuesta dormir antes de las pruebas.", "emocional"),
    ("Me cambiaron el turno en el trabajo y choca con mis clases.", "logistica"),
    ("En mi casa estamos complicados con la plata y necesito algún apoyo económico.", "economica"),
]
# Ampliación B: tareas de ejemplo para estimar horas (entregas relativas a plan_estudio.FECHA_REFERENCIA).
TAREAS_EJEMPLO: list[tuple[str, str, str]] = [
    ("Informe escrito de 5 páginas analizando el caso de una pyme", "Administración de Empresas", "2026-11-20"),
    ("Estudiar para la prueba 2 de funciones lineales", "Matemática", "2026-11-18"),
    ("Presentación grupal de 10 minutos sobre atención primaria", "Técnico en Enfermería", "2026-11-23"),
    ("Guía de 15 ejercicios de asientos contables", "Contabilidad General", "2026-11-17"),
    ("Programa en Python que lea un archivo CSV y calcule promedios", "Ingeniería en Informática", "2026-11-24"),
]


def ejecutar_ampliacion(cliente: ClienteClaude) -> dict[str, Any]:
    """Sugerencias de apoyo para 8 check-ins, estimaciones de 5 tareas y planes deterministas."""
    apoyos.guardar_catalogo()
    demo = pd.read_csv(config.RUTA_DEMO, encoding="utf-8")
    plan_estudio.guardar_datos_plan(demo)
    out: dict[str, Any] = {"sugerencias": [], "estimaciones": [], "planes": []}
    for texto, necesidad in CHECKINS_APOYOS:
        s = cliente.sugerir_apoyos(necesidad, texto)
        out["sugerencias"].append({"texto": texto, "necesidad": necesidad, "sugerencias": s,
                                   "origen": cliente.ultimo_origen})
    for desc, asig, fecha in TAREAS_EJEMPLO:
        e = cliente.estimar_horas(desc, asig, fecha)
        out["estimaciones"].append({"tarea": desc, "asignatura": asig, "fecha_entrega": fecha,
                                    "estimacion": e, "origen": cliente.ultimo_origen})
    for k, id_ in enumerate(demo["id_seudonimo"]):
        if not plan_estudio.acepto_programa(id_):
            out["planes"].append({"id_seudonimo": id_, "acepto_programa": False})
            continue
        est = out["estimaciones"][k % len(TAREAS_EJEMPLO)]
        plan = plan_estudio.plan_para_estudiante(id_, est["estimacion"]["subtareas"], est["fecha_entrega"])
        out["planes"].append({"id_seudonimo": id_, "acepto_programa": True, "tarea": est["tarea"],
                              "fecha_entrega": est["fecha_entrega"], "plan": plan})
    return out

# 8 check-ins de prueba; el último es de crisis (derivar_humano debe ser True).
CHECKINS_PRUEBA: list[str] = [
    "Me cambiaron el turno en el trabajo y no alcanzo a llegar a la primera clase.",
    "No entendí la materia de matemática y la prueba es la próxima semana.",
    "No me salió la beca y estoy viendo si me alcanza para el pasaje.",
    "Todo bien por ahora, me gusta la carrera.",
    "Estoy cuidando a mi mamá y se me ha hecho difícil venir.",
    "Ando con mucha ansiedad antes de las pruebas y duermo poco.",
    "Estoy pensando en congelar el semestre, no sé si puedo seguir así.",
    "Ya no aguanto más, siento que no vale la pena vivir y he pensado en hacerme daño.",
]
INDICE_CRISIS: int = 7

# Check-in de respaldo para casos demo sin texto propio (no contienen datos personales).
_CHECKIN_RESPALDO: list[str] = [
    "Voy bien, aunque matemática me cuesta un poco.",
    "Salgo del trabajo a las 18:30 y llego tarde a la primera hora.",
    "Me organicé con un horario y me está resultando.",
    "Siento que voy atrasado con los contenidos de especialidad.",
]


def casos_demo() -> list[dict[str, Any]]:
    """Los 12 casos demo unidos a la predicción del modelo (nivel, riesgo, razones)."""
    demo = pd.read_csv(config.RUTA_DEMO, encoding="utf-8")
    pred = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    df = demo.drop(columns=["nivel_esperado"]).merge(pred, on="id_seudonimo", how="left")
    casos = df.to_dict(orient="records")
    for i, c in enumerate(casos):
        texto = c.get("checkin_texto")
        c["checkin_demo"] = texto if isinstance(texto, str) and texto.strip() else _CHECKIN_RESPALDO[i % 4]
    return casos


def ejecutar(cliente: ClienteClaude) -> dict[str, Any]:
    """Corre las 4 tareas para los 12 casos demo + los 8 check-ins de prueba."""
    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    pred = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    agregados = auditoria.agregados_por_seccion(est, pred)
    salida: dict[str, Any] = {"casos": [], "checkins_prueba": [], "secciones": {}}
    for c in casos_demo():
        p = payload_para_claude(c)
        canal = "whatsapp" if c["jornada"] == "vespertina" else "correo"
        caso = {"id_seudonimo": c["id_seudonimo"], "payload": p, "canal": canal}
        caso["explicacion"] = cliente.explicar_a_tutor(p)
        caso["origen_explicacion"] = cliente.ultimo_origen
        caso["invitacion"] = cliente.redactar_invitacion(p, canal)
        caso["origen_invitacion"] = cliente.ultimo_origen
        caso["checkin"] = c["checkin_demo"]
        caso["clasificacion"] = cliente.clasificar_checkin(c["checkin_demo"])
        caso["origen_clasificacion"] = cliente.ultimo_origen
        if c["seccion"] not in salida["secciones"]:
            salida["secciones"][c["seccion"]] = {
                "resumen": cliente.resumir_seccion(agregados[c["seccion"]]),
                "origen": cliente.ultimo_origen,
            }
        caso["seccion"] = c["seccion"]
        salida["casos"].append(caso)
    for t in CHECKINS_PRUEBA:
        salida["checkins_prueba"].append({"texto": t, "clasificacion": cliente.clasificar_checkin(t),
                                          "origen": cliente.ultimo_origen})
    salida["ampliacion"] = ejecutar_ampliacion(cliente)
    cliente.guardar_cache()
    return salida


def ejecutar_panel(cliente: ClienteClaude) -> dict[str, Any]:
    """Ciclo 5: lo que el panel necesita en caché (recordatorios, apoyos de check-ins demo,
    explicaciones e invitaciones de los casos extra y resúmenes de todas las secciones)."""
    from src import demo_panel  # import local: demo_panel importa este módulo

    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    pred = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    out: dict[str, Any] = {"recordatorios": {}, "sugerencias": {}, "explicaciones": 0, "secciones": 0}
    casos = demo_panel.casos()
    for c in casos:
        if c["nivel"] not in ("medio", "alto"):
            continue
        canal = demo_panel.canal_de(c["jornada"])
        p = payload_para_claude(c)
        cliente.explicar_a_tutor(p)
        cliente.redactar_invitacion(p, canal)
        out["explicaciones"] += 1
        clave = f"{c['carrera']}|{canal}"
        if clave not in out["recordatorios"]:
            out["recordatorios"][clave] = cliente.redactar_invitacion({"carrera": c["carrera"]}, canal,
                                                                     tipo="recordatorio")
    for c in casos:
        if c["checkin_demo"]:
            clas = cliente.clasificar_checkin(c["checkin_demo"])
            if clas["necesidad"] != "ninguna":
                out["sugerencias"][c["id_seudonimo"]] = cliente.sugerir_apoyos(clas["necesidad"], c["checkin_demo"])
    for agregados in auditoria.agregados_por_seccion(est, pred).values():
        cliente.resumir_seccion(agregados)
        out["secciones"] += 1
    cliente.guardar_cache()
    return out


def main() -> int:
    if "--panel" in sys.argv:
        cliente = ClienteClaude(preferir_cache=True)   # solo llama por lo que falta en caché
        r = ejecutar_panel(cliente)
        print(f"Caché del panel lista: {len(r['recordatorios'])} recordatorios, {len(r['sugerencias'])} casos con "
              f"apoyos, {r['secciones']} secciones. Llamadas a la API: {cliente.llamadas}.")
        return 0
    cliente = ClienteClaude()
    r = ejecutar(cliente)
    origenes = [c["origen_invitacion"] for c in r["casos"]]
    print(f"Caché guardada en {config.RUTA_CACHE_CLAUDE} ({len(r['casos'])} casos). "
          f"Llamadas a la API en esta corrida: {cliente.llamadas}. Origen invitaciones: "
          f"{ {o: origenes.count(o) for o in set(origenes)} }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
