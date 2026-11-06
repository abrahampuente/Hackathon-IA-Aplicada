"""Arma el estado inicial del panel con los 12 casos demo y helpers compartidos por app.py y verify.

Todo se sirve desde la caché de Claude cuando OFFLINE=1.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src import apoyos, config, generar_cache, plan_estudio
from src.claude_client import ClienteClaude
from src.programador import Programador
from src.seudonimizar import payload_para_claude


def canal_de(jornada: str) -> str:
    """WhatsApp para vespertina, correo para diurna."""
    return "whatsapp" if jornada == "vespertina" else "correo"


def proveedor_recordatorio(cliente: ClienteClaude) -> Any:
    """Función que redacta el recordatorio de un caso con Claude (o la caché / plantilla)."""
    def _texto(caso: dict[str, Any]) -> str:
        return cliente.redactar_invitacion({"carrera": caso["carrera"]}, caso["canal"], tipo="recordatorio")
    return _texto


N_EXTRA_POCO_CONFIABLE: int = 2


def casos() -> list[dict[str, Any]]:
    """12 casos demo + 2 casos reales (de los 600) medio/alto con dato de asistencia poco confiable.

    Los extra muestran en vivo la excepción "dato poco confiable"; no tienen check-in.
    """
    demo = generar_cache.casos_demo()
    ids = {c["id_seudonimo"] for c in demo}
    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    pred = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    extra = est.merge(pred, on="id_seudonimo")
    extra = extra[extra["dato_asistencia_poco_confiable"] & extra["nivel"].isin(["medio", "alto"])
                  & ~extra["id_seudonimo"].isin(ids)].sort_values("id_seudonimo").head(N_EXTRA_POCO_CONFIABLE)
    filas = extra.to_dict(orient="records")
    for f in filas:
        f["checkin_demo"] = None
    return demo + filas


def sembrar(prog: Programador, cliente: ClienteClaude) -> None:
    """Registra los casos y programa la invitación de cada caso medio o alto."""
    apoyos.guardar_catalogo()
    plan_estudio.guardar_datos_plan(pd.read_csv(config.RUTA_DEMO, encoding="utf-8"))
    for c in casos():
        canal = canal_de(c["jornada"])
        derivar = False
        if c["checkin_demo"]:
            clas = cliente.clasificar_checkin(c["checkin_demo"])
            derivar = bool(clas["derivar_humano"])
            prog.estado.setdefault("checkins", {})[c["id_seudonimo"]] = {
                "texto": c["checkin_demo"], "clasificacion": clas, "hora": prog.estado["reloj"]}
        prog.registrar_caso(c["id_seudonimo"], c["nivel"], canal, c["carrera"],
                            dato_poco_confiable=bool(c["dato_asistencia_poco_confiable"]),
                            derivar_humano=derivar)
        if c["nivel"] in ("medio", "alto"):
            texto = cliente.redactar_invitacion(payload_para_claude(c), canal)
            prog.crear_mensaje(c["id_seudonimo"], texto, tipo="invitacion")


def texto_oferta_apoyo(id_apoyo: str) -> str:
    """Párrafo que se agrega al mensaje al ofrecer un apoyo (sin datos del modelo)."""
    a = {x["id"]: x for x in apoyos.cargar_catalogo()}[id_apoyo]
    if a["tipo"] == "externo":
        return (f"\nTambién podemos ponerte en contacto con {a['nombre']}, una organización externa. "
                "Antes de cualquier derivación te pediremos tu autorización explícita y no compartiremos "
                "ningún dato sin ella.")
    return f"\nTambién te puede servir: {a['nombre']}. {a['como_postular']}"


def ofrecer_apoyo(prog: Programador, gestor: apoyos.GestorApoyos, id_seudonimo: str, id_apoyo: str,
                  razon: str = "") -> dict[str, Any]:
    """Agrega el apoyo al mensaje pendiente (o crea uno) y registra la propuesta.

    Un apoyo externo deja el mensaje en REQUIERE_APROBACION y la propuesta pendiente de consentimiento.
    """
    a = {x["id"]: x for x in apoyos.cargar_catalogo()}[id_apoyo]
    externo = a["tipo"] == "externo"
    gestor.proponer(id_seudonimo, [{"id": id_apoyo, "razon": razon}])
    pendientes = [m for m in prog.mensajes_de(id_seudonimo) if m["estado"] in ("PROGRAMADO", "REQUIERE_APROBACION")]
    extra = texto_oferta_apoyo(id_apoyo)
    if pendientes:
        m = pendientes[0]
        partes = m["texto"].split("\n¿Por qué recibí esto?")
        nuevo = partes[0].rstrip() + "\n" + extra.strip() + ("\n\n¿Por qué recibí esto?" + partes[1] if len(partes) > 1 else "")
        prog.editar(m["id_mensaje"], nuevo)
        if externo:
            m["apoyo_externo"] = True
            m["estado"] = "REQUIERE_APROBACION"
            m["excepciones"] = sorted(set(m["excepciones"]) | {"apoyo_externo"})
            prog.guardar()
        return m
    base = ("Hola {NOMBRE}, te escribe el Equipo de Acompañamiento Estudiantil." + extra +
            "\n¿Por qué recibí esto? Porque acompañamos a estudiantes de primer año durante el semestre."
            "\nSi prefieres no recibir más mensajes, responde NO MÁS.")
    return prog.crear_mensaje(id_seudonimo, base, tipo="apoyo", apoyo_externo=externo)


def registrar_checkin(prog: Programador, cliente: ClienteClaude, id_seudonimo: str, texto: str) -> dict[str, Any]:
    """Check-in del estudiante: se clasifica y, si requiere persona, lo pendiente pasa a aprobación."""
    clas = cliente.clasificar_checkin(texto)
    prog.estado.setdefault("checkins", {})[id_seudonimo] = {"texto": texto, "clasificacion": clas,
                                                            "hora": prog.estado["reloj"]}
    prog.guardar()
    if clas["derivar_humano"]:
        prog.marcar_derivar_humano(id_seudonimo)
    return clas


def reiniciar(rutas: list[Any]) -> None:
    """Borra el estado simulado del panel (solo archivos que crea el propio panel)."""
    for r in rutas:
        if r.is_file():
            r.unlink()
