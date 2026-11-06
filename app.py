"""Panel de alerta temprana y acompañamiento (Streamlit). Datos sintéticos; ningún mensaje sale de verdad.

Uso:  python run_demo.py   y luego   streamlit run app.py
Vistas: Jefe de carrera · Tutor · Estudiante (simulada) · Auditoría
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import apoyos, auditoria, config, correo, demo_panel, plan_estudio  # noqa: E402
from src.claude_client import ClienteClaude  # noqa: E402
from src.programador import RUTA_DECISIONES, RUTA_ESTADO, Programador  # noqa: E402
from src.seudonimizar import insertar_nombre, payload_para_claude  # noqa: E402

VISTAS = ["Jefe de carrera", "Tutor", "Estudiante", "Auditoría"]
NOMBRE_ESTADO = {"PROGRAMADO": "Programado", "REQUIERE_APROBACION": "Requiere tu aprobación",
                 "ENVIADO": "Enviado", "CANCELADO": "Cancelado", "CONTACTO_PRESENCIAL": "Contacto en persona"}
NOMBRE_EXC = {"derivar_humano": "check-in pide revisión de una persona", "apoyo_externo": "ofrece un apoyo externo",
              "dato_poco_confiable": "dato de asistencia poco confiable"}

st.set_page_config(page_title="Alerta temprana", page_icon="🎓", layout="wide")
# Presentación (proyector): 3 colores (azul principal, ámbar, rojo) + grises; contraste WCAG AA >= 4,5:1.
# Los niveles y estados siempre llevan texto y símbolo, nunca solo color.
st.markdown("""<style>
.block-container { padding-top: 1.2rem; max-width: 1340px; }
.badge { display:inline-block; padding:3px 12px; border-radius:999px; font-weight:700; font-size:0.95rem;
         border:2px solid currentColor; line-height:1.5; white-space:nowrap; }
.b-alto   { color:#A4161A; background:#FDE8E8; }
.b-medio  { color:#7A4B00; background:#FFF1D6; }
.b-bajo   { color:#3D4752; background:#E9EDF2; }
.b-aprob  { color:#A4161A; background:#FDE8E8; font-size:1.05rem; }
.b-prog   { color:#1F4E79; background:#FFFFFF; }
.b-ok     { color:#1F4E79; background:#E8EFF7; }
.cuenta   { font-size:1.5rem; font-weight:700; color:#1F4E79; }
.cuenta.aprob { color:#A4161A; }
.sub      { color:#4A5562; font-size:0.95rem; }
.encabezado { border-bottom:3px solid #1F4E79; padding-bottom:0.4rem; margin-bottom:0.6rem; }
.encabezado h1 { margin:0; color:#1F4E79; }
.encabezado p { margin:0.2rem 0 0; color:#4A5562; font-size:1.15rem; }
.stTabs [role="tab"] p, .stTabs [role="tab"] { font-size:1.2rem !important; font-weight:650; }
.stTabs [role="tab"] { padding: 0.35rem 0.9rem; }
/* Vista tutor: el caso abierto queda fijo a la derecha mientras se recorre la bandeja */
div[data-testid="stColumn"]:has(#detalle-caso) {
  position: sticky; top: 3.2rem; align-self: flex-start;
  max-height: calc(100vh - 4rem); overflow-y: auto; padding-right: 0.4rem; }
</style>""", unsafe_allow_html=True)

NIVEL_BADGE = {"alto": ("b-alto", "■ Alto"), "medio": ("b-medio", "▲ Medio"), "bajo": ("b-bajo", "● Bajo")}


def badge_nivel(nivel: str) -> str:
    """Etiqueta de nivel con color, símbolo y texto."""
    clase, texto = NIVEL_BADGE.get(str(nivel), ("b-bajo", str(nivel)))
    return f'<span class="badge {clase}">{texto}</span>'


def badge_estado(estado: str) -> str:
    """Etiqueta de estado de un mensaje (Requiere tu aprobación destacada)."""
    if estado == "REQUIERE_APROBACION":
        return '<span class="badge b-aprob">⚠ Requiere tu aprobación</span>'
    if estado == "PROGRAMADO":
        return '<span class="badge b-prog">⏱ Programado</span>'
    return f'<span class="badge b-ok">✓ {NOMBRE_ESTADO.get(estado, estado)}</span>'


def html(texto: str) -> None:
    """Markdown con HTML para etiquetas."""
    st.markdown(texto, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Datos y estado
# --------------------------------------------------------------------------
@st.cache_data
def leer_csv(ruta: str) -> pd.DataFrame:
    """Lee un CSV de data/ (vacío si no existe)."""
    p = Path(ruta)
    return pd.read_csv(p, encoding="utf-8") if p.is_file() and p.stat().st_size else pd.DataFrame()


def cargar() -> tuple[Programador, ClienteClaude, apoyos.GestorApoyos]:
    """Programador (con reloj simulado), cliente de Claude y gestor de apoyos; siembra la demo si hace falta."""
    cliente = ClienteClaude(preferir_cache=True)   # usa la caché si ya existe respuesta de la API
    prog = Programador(texto_recordatorio=demo_panel.proveedor_recordatorio(cliente),
                       enviador_real=demo_panel.enviador_real)
    if not prog.estado["casos"]:
        demo_panel.sembrar(prog, cliente)
        cliente.guardar_cache()
    return prog, cliente, apoyos.GestorApoyos()


def faltan(m: dict, prog: Programador) -> str:
    """Cuenta regresiva hasta el envío programado."""
    if m["estado"] == "REQUIERE_APROBACION":
        return "no se envía solo"
    seg = (pd.Timestamp(m["envio_programado"]) - pd.Timestamp(prog.ahora)).total_seconds()
    if seg <= 0:
        return "vencido"
    return f"{int(seg // 3600)} h {int(seg % 3600 // 60)} min"


prog, cliente, gestor = cargar()
est = leer_csv(str(config.RUTA_ESTUDIANTES))
pred = leer_csv(str(config.RUTA_PREDICCIONES))
perfil = est.merge(pred, on="id_seudonimo").set_index("id_seudonimo") if not est.empty else pd.DataFrame()
if not perfil.empty:
    perfil = pd.concat([perfil, pd.DataFrame([demo_panel.fila_est_demo()]).set_index("id_seudonimo")])


def informar_envios(enviados: list[dict]) -> None:
    """Resultado de los correos reales (solo EST-DEMO) tras avanzar el reloj."""
    for m in enviados:
        r = m.get("envio_real")
        if not r:
            continue
        if r.get("ok"):
            st.sidebar.success(f"Correo real enviado ({m['id_seudonimo']}) a las {r['hora']}.")
        elif m.get("aviso_envio"):
            st.sidebar.warning(m["aviso_envio"] + f" Motivo: {r.get('motivo')}.")

# --------------------------------------------------------------------------
# Barra lateral: vista y reloj simulado
# --------------------------------------------------------------------------
st.sidebar.title("Controles de la demo")
st.sidebar.markdown(f"**Reloj simulado**  \n<span class='cuenta'>{prog.ahora:%d-%m-%Y %H:%M}</span>",
                    unsafe_allow_html=True)
c1, c2 = st.sidebar.columns(2)
if c1.button("Avanzar 24 h", key="av24"):
    enviados = prog.avanzar(horas=24)
    cliente.guardar_cache()
    st.sidebar.success(f"{len(enviados)} mensaje(s) enviados a la bandeja simulada.")
    informar_envios(enviados)
if c2.button("Avanzar 7 días", key="av7"):
    enviados = prog.avanzar(dias=7)
    cliente.guardar_cache()
    st.sidebar.success(f"{len(enviados)} mensaje(s) enviados a la bandeja simulada.")
    informar_envios(enviados)
st.sidebar.caption("Correo real: " + ("ACTIVO, solo a la lista blanca" if correo.modo_real() else "desactivado"))
if st.sidebar.button("Probar conexión de correo", key="probar_correo"):
    r = correo.probar_conexion()
    if r["ok"]:
        st.sidebar.success(f"Correo de prueba enviado a las {r['hora']} ({r['segundos']} s).")
    else:
        st.sidebar.warning(f"No se envió el correo de prueba. Motivo: {r['motivo']}.")
if st.sidebar.button("Reiniciar demo", key="reset"):
    demo_panel.reiniciar([RUTA_ESTADO, RUTA_DECISIONES, config.RUTA_BANDEJA, apoyos.RUTA_PROPUESTAS,
                          apoyos.RUTA_CONSENTIMIENTOS, plan_estudio.RUTA_PLANES])
    prog, cliente, gestor = cargar()
st.sidebar.caption("Datos sintéticos. Ningún mensaje se envía de verdad."
                   + (" · Modo OFFLINE" if config.OFFLINE else ""))

html("<div class='encabezado'><h1>Alerta temprana y acompañamiento</h1>"
     "<p>Detectar a tiempo, acompañar con personas: primer año Duoc UC, con foco en quienes estudian y trabajan.</p>"
     "</div>")


# --------------------------------------------------------------------------
# Vista 1: Jefe de carrera (solo agregados)
# --------------------------------------------------------------------------
def vista_jefe() -> None:
    st.caption("Solo datos agregados por sección. Sin nombres ni identificadores.")
    if est.empty or pred.empty:
        st.info("Ejecuta `python run_demo.py` para generar los datos.")
        return
    df = est.merge(pred[["id_seudonimo", "nivel"]], on="id_seudonimo")
    offline = ClienteClaude(offline=True)   # clasificación masiva siempre desde caché o reglas locales
    nec = {}
    for _, f in df[df["checkin_texto"].fillna("").str.len() > 0].iterrows():
        n = offline.clasificar_checkin(f["checkin_texto"])["necesidad"]
        if n != "ninguna":
            nec.setdefault(f["seccion"], []).append(n)
    filas = []
    for sec, t in df.groupby("seccion"):
        cuenta = t["nivel"].value_counts()
        top = pd.Series(nec.get(sec, [])).value_counts().head(2)
        filas.append({"Sección": sec, "Carrera": t["carrera"].iloc[0], "Estudiantes": len(t),
                      "● Bajo": int(cuenta.get("bajo", 0)), "▲ Medio": int(cuenta.get("medio", 0)),
                      "■ Alto": int(cuenta.get("alto", 0)),
                      "Necesidades más frecuentes": ", ".join(f"{k} ({v})" for k, v in top.items()) or "—"})
    tot = df["nivel"].value_counts()
    k1, k2, k3, k4 = st.columns(4)
    for col, nivel in ((k1, "bajo"), (k2, "medio"), (k3, "alto")):
        with col.container(border=True):
            html(badge_nivel(nivel))
            st.metric(f"Estudiantes en nivel {nivel}", int(tot.get(nivel, 0)), label_visibility="collapsed")
    with k4.container(border=True):
        html("<span class='sub'>Indicador de seguimiento</span>")
        st.metric("Enviados sin revisión", f"{prog.pct_enviados_sin_revision():.0f}%",
                  help="% de mensajes que salieron sin que un tutor los revisara.")
    st.subheader("Secciones")
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
    agregados = auditoria.agregados_por_seccion(est, pred)
    st.subheader("Resumen por sección")
    sec = st.selectbox("Sección", sorted(agregados), key="sec_jefe")
    with st.container(border=True):
        html("<span class='sub'>Redactado por Claude a partir de datos agregados</span>")
        st.markdown(cliente.resumir_seccion(agregados[sec]))
    cliente.guardar_cache()


# --------------------------------------------------------------------------
# Vista 2: Tutor
# --------------------------------------------------------------------------
def abrir_caso(id_: str) -> None:
    """Callback de las tarjetas: abre el caso en el detalle."""
    st.session_state["caso_tutor"] = id_


def vista_tutor() -> None:
    pend = prog.pendientes()
    a, b, c = st.columns(3)
    a.metric("⏱ Programados", sum(m["estado"] == "PROGRAMADO" for m in pend))
    b.metric("⚠ Requieren tu aprobación", sum(m["estado"] == "REQUIERE_APROBACION" for m in pend))
    c.metric("Sin respuesta tras recordatorio", len(prog.sin_respuesta()))
    seleccionado = st.session_state.get("caso_tutor")
    col_b, col_d = st.columns([2, 3], gap="large")
    with col_b:
        st.subheader("Bandeja de mensajes")
        st.caption("Primero los que requieren tu aprobación; luego los programados por hora de envío. "
                   "Si no los revisas, los programados salen solos al cumplirse 24 h.")
        if not pend:
            st.info("No hay mensajes pendientes.")
        orden = ([m for m in pend if m["estado"] == "REQUIERE_APROBACION"]
                 + [m for m in pend if m["estado"] != "REQUIERE_APROBACION"])
        for m in orden:
            nivel = prog.estado["casos"][m["id_seudonimo"]]["nivel"]
            aprob = m["estado"] == "REQUIERE_APROBACION"
            abierto = m["id_seudonimo"] == seleccionado
            with st.container(border=True):
                html(f"{badge_estado(m['estado'])} {badge_nivel(nivel)}"
                     + (" <span class='badge b-ok'>▶ Abierto</span>" if abierto else ""))
                html(f"<div class='cuenta{' aprob' if aprob else ''}'>"
                     f"{'No se envía solo' if aprob else 'Sale en ' + faltan(m, prog)}</div>"
                     f"<div class='sub'>{m['id_seudonimo']} · {m['tipo']} · {m['canal']} · "
                     f"envío {m['envio_programado'].replace('T', ' ')}</div>")
                if aprob:
                    html("<div class='sub'>Motivo: " + ", ".join(NOMBRE_EXC[e] for e in m["excepciones"]) + "</div>")
                st.button("Abrir caso", key=f"abrir_{m['id_mensaje']}", on_click=abrir_caso,
                          args=(m["id_seudonimo"],), type="primary" if abierto else "secondary")
        if prog.sin_respuesta():
            st.warning("Sin respuesta tras el recordatorio (decide si contactar en persona): "
                       + ", ".join(prog.sin_respuesta()))

    with col_d:
        html("<div id='detalle-caso'></div>")
        ids = list(prog.estado["casos"])
        id_ = st.selectbox("Caso abierto", ids, key="caso_tutor")
        caso = prog.estado["casos"][id_]
        fila = perfil.loc[id_] if id_ in perfil.index else None
        st.subheader(f"Caso {id_}" + (f" · {fila['nombre_ficticio']}" if fila is not None else ""))
        if fila is not None:
            with st.container(border=True):
                html(f"{badge_nivel(fila['nivel'])} &nbsp; <b>Riesgo estimado: {fila['prob_riesgo']:.0f}%</b>"
                     " <span class='sub'>(estimación del modelo; decide el tutor)</span>")
                st.markdown("**Razones del modelo**\n" + "\n".join(f"- {fila[f'razon_{k}']}" for k in (1, 2, 3)))
                p = payload_para_claude({**fila.to_dict(), "id_seudonimo": id_})
                st.markdown("**Explicación de Claude**")
                st.text(cliente.explicar_a_tutor(p))
        if caso["dato_poco_confiable"]:
            st.warning("⚠ Dato de asistencia poco confiable: hay caídas aisladas que podrían ser marcas erróneas "
                       "(por ejemplo, atrasos). Considéralo antes de decidir.")

        # check-in y apoyos
        chk = prog.estado.get("checkins", {}).get(id_)
        if chk:
            cl = chk["clasificacion"]
            st.markdown(f"**Check-in:** “{chk['texto']}”  \nNecesidad: {cl['necesidad']} · urgencia: {cl['urgencia']}"
                        + (" · **requiere una persona**" if cl["derivar_humano"] else ""))
            if cl["necesidad"] != "ninguna":
                cat = {x["id"]: x for x in apoyos.cargar_catalogo()}
                st.markdown("**Apoyos sugeridos** (catálogo de ejemplo: validar con Asuntos Estudiantiles)")
                for s in cliente.sugerir_apoyos(cl["necesidad"], chk["texto"]):
                    ap = cat[s["id"]]
                    col1, col2 = st.columns([4, 1])
                    col1.markdown(f"**{ap['nombre']}** ({'externo' if ap['tipo'] == 'externo' else 'interno'}) — "
                                  f"{s['razon']}  \nCómo postular: {ap['como_postular']}")
                    if col2.button("Ofrecer apoyo", key=f"ofrecer_{id_}_{ap['id']}"):
                        try:
                            demo_panel.ofrecer_apoyo(prog, gestor, id_, ap["id"], s["razon"])
                        except ValueError as exc:
                            st.error(f"No se pudo ofrecer el apoyo: {exc}")
                        else:
                            st.success("Apoyo ofrecido en el mensaje." + (" Al ser externo, requiere tu aprobación "
                                       "y la autorización del estudiante." if ap["tipo"] == "externo" else ""))
                cliente.guardar_cache()
        props = gestor.propuestas_de(id_)
        if props:
            st.markdown("**Apoyos propuestos**")
            for p in props:
                etiqueta = gestor.etiqueta_estado(p)
                if p["tipo"] == "externo" and p["estado"] == "pendiente_consentimiento" and gestor.consentimiento_vigente(p["id_propuesta"]):
                    etiqueta = "Autorizado por el estudiante: puedes derivar"
                col1, col2 = st.columns([4, 1])
                col1.markdown(f"- {p['id_apoyo']}: {etiqueta}")
                if p["tipo"] == "externo" and p["estado"] != "activo" and col2.button("Derivar", key=f"derivar_{p['id_propuesta']}"):
                    try:
                        gestor.activar(p["id_propuesta"], aprobado_por_tutor=True)
                        st.success("Derivado con autorización registrada.")
                    except PermissionError as exc:
                        st.error(str(exc))

        # mensaje pendiente
        pendientes = [m for m in prog.mensajes_de(id_) if m["estado"] in ("PROGRAMADO", "REQUIERE_APROBACION")]
        for m in pendientes:
            with st.container(border=True):
                aprob = m["estado"] == "REQUIERE_APROBACION"
                html(f"{badge_estado(m['estado'])} &nbsp; <b>Mensaje {m['id_mensaje']}</b> "
                     f"<span class='sub'>({m['tipo']}, {m['canal']}) · envío programado "
                     f"{m['envio_programado'].replace('T', ' ')}</span>")
                html(f"<div class='cuenta{' aprob' if aprob else ''}'>"
                     f"{'No se enviará solo: necesita tu aprobación' if aprob else 'Sale en ' + faltan(m, prog)}</div>")
                if aprob:
                    st.error("Requiere tu aprobación: " + ", ".join(NOMBRE_EXC[e] for e in m["excepciones"])
                             + ". No se enviará solo.")
                meta = m.get("meta") or {}
                if meta.get("en_vivo"):
                    st.success(f"Generado en vivo por Claude · {meta.get('modelo')} · {meta.get('segundos')} s")
                elif id_ == demo_panel.ID_DEMO:
                    st.info(f"Generado desde {meta.get('origen', 'caché')} (modo OFFLINE o API no disponible).")
                if caso.get("correo_real"):
                    st.caption("Este caso recibe un correo REAL (solo a la lista blanca) cuando el mensaje se envía."
                               if correo.modo_real() else "Correo real desactivado: irá solo a la bandeja simulada.")
                    if st.button("Regenerar en vivo con Claude", key=f"regenerar_{m['id_mensaje']}"):
                        nuevo, meta_n = demo_panel.generar_mensaje_demo(cliente)
                        prog.editar(m["id_mensaje"], nuevo)
                        m["meta"] = meta_n
                        prog.guardar()
                        cliente.guardar_cache()
                        st.rerun()
                texto = st.text_area("Mensaje (editable)", m["texto"], height=220, key=f"txt_{m['id_mensaje']}")
                motivo = st.text_input("Motivo (obligatorio para cancelar)", key=f"motivo_{m['id_mensaje']}")
                b1, b2, b3, b4 = st.columns(4)
                try:
                    if b1.button("Guardar edición", key=f"editar_{m['id_mensaje']}"):
                        prog.editar(m["id_mensaje"], texto)
                        st.success("Editado: sigue programado con el texto nuevo.")
                    etiqueta = "Aprobar y enviar" if m["estado"] == "REQUIERE_APROBACION" else "Enviar ahora"
                    if b2.button(etiqueta, key=f"enviar_{m['id_mensaje']}"):
                        if texto != m["texto"]:
                            prog.editar(m["id_mensaje"], texto)
                        prog.enviar_ahora(m["id_mensaje"])
                        st.success("Enviado a la bandeja simulada.")
                    if b3.button("Cancelar", key=f"cancelar_{m['id_mensaje']}"):
                        prog.cancelar(m["id_mensaje"], motivo)
                        st.success("Envío cancelado.")
                    if b4.button("Contactar en persona", key=f"persona_{m['id_mensaje']}"):
                        prog.contactar_en_persona(m["id_mensaje"], motivo)
                        st.success("Envío automático cancelado: contacto en persona.")
                except ValueError as exc:
                    st.error(str(exc))

        st.markdown("**Plan de estudio**")
        plan = plan_estudio.plan_para_tutor(id_)
        if plan is None:
            st.caption("El estudiante no ha compartido su plan de estudio.")
        else:
            st.markdown(f"Tarea: {plan['tarea']}")
            st.dataframe(pd.DataFrame(plan["plan"]["bloques"]), hide_index=True, width="stretch")

        if RUTA_DECISIONES.is_file():
            hist = pd.read_csv(RUTA_DECISIONES, encoding="utf-8")
            hist = hist[hist["id_seudonimo"] == id_]
            with st.expander("Historial de decisiones del caso"):
                st.dataframe(hist[["hora_simulada", "actor", "accion", "motivo"]], hide_index=True, width="stretch")


# --------------------------------------------------------------------------
# Vista 3: Estudiante (simulada)
# --------------------------------------------------------------------------
def vista_estudiante() -> None:
    st.caption("Vista simulada de lo que ve un estudiante.")
    ids = list(prog.estado["casos"])
    nombre = lambda i: perfil.loc[i, "nombre_ficticio"] if i in perfil.index else i  # noqa: E731
    id_ = st.selectbox("Estudiante", ids, format_func=lambda i: f"{nombre(i)} ({i})", key="est_sel")
    caso = prog.estado["casos"][id_]
    t_bandeja, t_por_que, t_checkin, t_plan, t_aut = st.tabs(
        ["Bandeja", "¿Por qué recibí esto?", "Check-in", "Mi plan", "Autorizaciones"])

    with t_bandeja:
        recibidos = prog.bandeja_estudiante(id_)
        if not recibidos:
            st.info("No tienes mensajes nuevos.")
        for m in recibidos:
            with st.container(border=True):
                html(f"<b>{m['enviado_en'].replace('T', ' ')}</b> <span class='sub'>· {m['canal']}</span>")
                if m.get("aviso_envio"):
                    st.warning(m["aviso_envio"])
                elif (m.get("envio_real") or {}).get("ok"):
                    st.caption(f"También enviado como correo real a las {m['envio_real']['hora']}.")
                st.text(insertar_nombre(m["texto"], str(nombre(id_)).split()[0]))
        if caso["no_mas"]:
            st.success("Pediste no recibir más mensajes. No te enviaremos nada más.")
        elif recibidos:
            b1, b2 = st.columns(2)
            if b1.button("Responder: me interesa", key=f"resp_{id_}"):
                prog.registrar_respuesta(id_)
                st.success("¡Gracias! Un tutor te contactará para coordinar.")
            if b2.button("No quiero recibir más", key=f"nomas_{id_}"):
                n = prog.no_quiero_mas(id_)
                st.success(f"Listo. Cancelamos {n} mensaje(s) programado(s) y no te escribiremos más.")

    with t_por_que:
        st.markdown(
            "### ¿Por qué recibí esto?\n"
            "El Equipo de Acompañamiento Estudiantil acompaña a estudiantes de **primer año** durante su "
            "primer semestre. Revisamos de forma general cómo va el curso (por ejemplo, la asistencia y las "
            "evaluaciones) para ofrecer apoyo **a tiempo** a quien le pueda servir.\n\n"
            "- Participar es **voluntario** y no afecta tus notas.\n"
            "- Una persona del equipo revisa los mensajes y puede escribirte o conversar contigo.\n"
            "- Tus datos no se comparten con terceros sin tu autorización.\n"
            "- Puedes pedir **no recibir más mensajes** cuando quieras.")

    with t_checkin:
        st.button("Usar ejemplo de demo (necesidad económica)", key=f"ejemplo_checkin_{id_}",
                  on_click=lambda k=f"checkin_txt_{id_}": st.session_state.__setitem__(k, demo_panel.CHECKIN_ECONOMICO))
        texto = st.text_area("¿Cómo vas? Cuéntanos en pocas palabras", key=f"checkin_txt_{id_}")
        if st.button("Enviar check-in", key=f"checkin_btn_{id_}") and texto.strip():
            clas = demo_panel.registrar_checkin(prog, cliente, id_, texto)
            cliente.guardar_cache()
            st.success("Gracias por contarnos. El equipo lo revisará.")
            if clas["urgencia"] == "alta":
                # Recursos de ayuda en Chile: validar con Asuntos Estudiantiles antes de usar con estudiantes.
                st.error("Si sientes que estás en peligro ahora, busca ayuda inmediata: *4141 (línea de "
                         "prevención del suicidio, gratuita) o 131 (SAMU). Una persona del equipo te contactará.")

    with t_plan:
        vista_mi_plan(id_)

    with t_aut:
        pend = gestor.externas_pendientes(id_)
        if not pend:
            st.info("No tienes autorizaciones pendientes.")
        for p in pend:
            info = apoyos.DATOS_A_COMPARTIR.get(p["id_apoyo"], {})
            st.markdown(f"### Autorización para {p['id_apoyo']}\n"
                        f"- **Qué dato se compartiría:** {info.get('datos', '—')}\n"
                        f"- **Con quién:** {info.get('con_quien', '—')}\n"
                        f"- **Para qué:** {info.get('para_que', '—')}\n\n"
                        "Si no aceptas, no se comparte nada y puedes seguir usando los apoyos internos.")
            b1, b2 = st.columns(2)
            if gestor.consentimiento_vigente(p["id_propuesta"]):
                st.success("Ya autorizaste. El tutor puede realizar la derivación.")
            else:
                if b1.button("Acepto", key=f"acepto_{p['id_propuesta']}"):
                    gestor.registrar_consentimiento(p["id_propuesta"], acepta=True)
                    st.success("Autorización registrada.")
                if b2.button("No acepto", key=f"noacepto_{p['id_propuesta']}"):
                    gestor.registrar_consentimiento(p["id_propuesta"], acepta=False)
                    st.info("Registrado. No se compartirá ningún dato.")


def vista_mi_plan(id_: str) -> None:
    """Pestaña Mi plan: franjas, tarea, estimación editable y plan semanal. El plan es del estudiante."""
    if not plan_estudio.acepto_programa(id_):
        st.info("El plan de estudio está disponible para quienes participan del programa de acompañamiento.")
        if st.button("Quiero participar", key=f"aceptar_prog_{id_}"):
            datos = json.loads(plan_estudio.RUTA_PROGRAMA.read_text(encoding="utf-8"))
            datos["aceptaron"].append(id_)
            plan_estudio.RUTA_PROGRAMA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
            st.success("¡Bienvenido/a! Vuelve a abrir esta pestaña para armar tu plan.")
        return
    st.markdown("**1. Tus horarios libres en la semana**")
    disp = leer_csv(str(plan_estudio.RUTA_DISPONIBILIDAD))
    base = disp[disp["id_seudonimo"] == id_][["dia", "hora_inicio", "hora_fin"]].reset_index(drop=True) \
        if not disp.empty else pd.DataFrame(columns=["dia", "hora_inicio", "hora_fin"])
    franjas = st.data_editor(base, num_rows="dynamic", key=f"franjas_{id_}", hide_index=True,
                             column_config={"dia": st.column_config.SelectboxColumn("Día", options=list(plan_estudio.DIAS)),
                                            "hora_inicio": "Desde (HH:MM)", "hora_fin": "Hasta (HH:MM)"})
    st.markdown("**2. Tu tarea**")
    desc = st.text_input("Descripción", "Programa en Python que lea un archivo CSV y calcule promedios",
                         key=f"tarea_desc_{id_}")
    asig = st.text_input("Asignatura", "Ingeniería en Informática", key=f"tarea_asig_{id_}")
    fecha = st.date_input("Fecha de entrega", date(2026, 11, 24), key=f"tarea_fecha_{id_}")
    k_est, k_plan = f"estimacion_{id_}", f"plan_{id_}"
    if st.button("Estimar horas", key=f"btn_estimar_{id_}"):
        st.session_state[k_est] = cliente.estimar_horas(desc, asig, fecha.isoformat())
        st.session_state.pop(k_plan, None)
        cliente.guardar_cache()
    e = st.session_state.get(k_est)
    if e:
        st.markdown(f"**3. Estimación (puedes editarla):** entre {e['horas_min']} y {e['horas_max']} horas. "
                    "Es una guía para organizarte; la tarea la haces tú.")
        st.caption("Supuestos: " + " · ".join(e["supuestos"]))
        sub = st.data_editor(pd.DataFrame(e["subtareas"]), num_rows="dynamic", key=f"sub_{id_}", hide_index=True)
        if st.button("Generar plan", key=f"btn_plan_{id_}"):
            try:
                st.session_state[k_plan] = plan_estudio.planificar(
                    sub.to_dict(orient="records"), franjas.dropna().to_dict(orient="records"), fecha,
                    desde=prog.ahora.date())
            except (ValueError, KeyError) as exc:
                st.error(f"Revisa los horarios (formato HH:MM): {exc}")
    plan = st.session_state.get(k_plan)
    if plan:
        if plan["ok"]:
            st.markdown(f"**4. Tu plan** · {plan['minutos_trabajo'] // 60} h de trabajo · holgura "
                        f"{plan['holgura_pct'] * 100:.0f}% · terminas el {plan['ultimo_dia']}")
            st.dataframe(pd.DataFrame(plan["bloques"])[["fecha", "dia", "inicio", "fin", "subtarea"]],
                         hide_index=True, width="stretch")
            compartir = st.checkbox("Compartir mi plan con mi tutor", key=f"compartir_{id_}")
            if st.button("Guardar plan", key=f"guardar_plan_{id_}"):
                plan_estudio.guardar_plan_estudiante(id_, plan, desc, compartir)
                st.success("Plan guardado" + (" y compartido con tu tutor." if compartir else ". Solo tú lo ves."))
        else:
            st.warning(plan["aviso"])


# --------------------------------------------------------------------------
# Vista 4: Auditoría
# --------------------------------------------------------------------------
def vista_auditoria() -> None:
    if not config.RUTA_AUDITORIA_JSON.is_file():
        st.info("Ejecuta `python run_demo.py` para generar la auditoría.")
        return
    a = json.loads(config.RUTA_AUDITORIA_JSON.read_text(encoding="utf-8"))
    despues = {(r["variable"], r["grupo"]): r["tasa_fp"] for r in a["despues"]["por_grupo"]}
    etiquetas = {"F": "Mujer", "M": "Hombre", "otro": "Otro género", "diurna": "Diurna", "vespertina": "Vespertina",
                 "mujer+vespertina": "Mujer + vespertina", "resto": "Resto", "sí": "Trabaja", "no": "No trabaja"}
    filas = [{"Grupo": etiquetas.get(r["grupo"], r["grupo"]), "Antes": round(r["tasa_fp"] * 100, 1),
              "Después": round(despues[(r["variable"], r["grupo"])] * 100, 1)}
             for r in a["antes"]["por_grupo"] if r["n_negativos"] >= config.MIN_NEGATIVOS_GRUPO]
    df = pd.DataFrame(filas).set_index("Grupo")
    st.markdown("**Tasa de falsos positivos por grupo (%)**: alertas a estudiantes que no desertaron.")
    import altair as alt  # dependencia de streamlit; permite letra grande para proyector
    largo = df.reset_index().melt("Grupo", var_name="Etapa", value_name="FP")
    grafico = alt.Chart(largo).mark_bar().encode(
        y=alt.Y("Grupo:N", sort=list(df.index), title=None, axis=alt.Axis(labelFontSize=16, labelLimit=260)),
        yOffset=alt.YOffset("Etapa:N", sort=["Antes", "Después"]),
        x=alt.X("FP:Q", title="% de falsos positivos", axis=alt.Axis(labelFontSize=14, titleFontSize=15)),
        color=alt.Color("Etapa:N", scale=alt.Scale(domain=["Antes", "Después"], range=["#6B7684", "#1F4E79"]),
                        legend=alt.Legend(title=None, orient="top", labelFontSize=16)),
        tooltip=["Grupo", "Etapa", "FP"],
    ).properties(height=520)
    st.altair_chart(grafico, width="stretch")
    st.markdown(f"Brecha mujer + vespertina vs resto: **{a['antes']['brecha_fp_subgrupo_pp']:.1f} → "
                f"{a['despues']['brecha_fp_subgrupo_pp']:.1f} pp** (con el riesgo real del generador: "
                f"{a['referencia_sintetica']['brecha_fp_subgrupo_pp']:.1f} pp). Grupos con menos de "
                f"{config.MIN_NEGATIVOS_GRUPO} no desertores no se grafican.")


for _pestana, _vista in zip(st.tabs(VISTAS), (vista_jefe, vista_tutor, vista_estudiante, vista_auditoria)):
    with _pestana:
        _vista()
