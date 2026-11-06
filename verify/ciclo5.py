"""Ciclo 5: panel del tutor, envíos programados y decisión humana (todo con OFFLINE=1).

Criterios:
  C1  Las 4 vistas cargan sin excepciones (AppTest)
  C2  La vista Jefe de carrera no muestra ningún nombre_ficticio ni id_seudonimo
  C3  Un programado no llega antes de 24 h; tras 24 h sin revisión llega con enviado_sin_revision
  C4  Editar dentro de la ventana cambia el texto que llega; Cancelar evita el envío
  C5  Las 3 excepciones nunca se envían sin aprobación, aunque pasen las 24 h (ni 30 días)
  C6  Recordatorio una sola vez a los 7 días; avanzar 30 días no genera más envíos
  C7  Responder o "No quiero recibir más" cancela el recordatorio
  C8  Cada acción queda en decisiones.csv con hora, acción y motivo
  C9  Recordatorios redactados con tipo=recordatorio, filtrados y presentes en el caché offline
  C10 Todo funciona con OFFLINE=1 (0 llamadas a la API durante la verificación)
Ampliación B:
  C11 Un apoyo externo no aparece como derivado sin un Acepto registrado
  C12 El tutor no ve el plan de un estudiante que no lo compartió
  C13 Mi plan genera un plan para un estudiante demo y muestra el aviso en el caso imposible
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["OFFLINE"] = "1"   # antes de importar config
os.environ["MODO_CORREO_REAL"] = "0"   # las pruebas nunca envían correos reales
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from src import apoyos, config, demo_panel, plan_estudio  # noqa: E402
from src.claude_client import ClienteClaude, problemas_invitacion  # noqa: E402
from src.programador import RUTA_DECISIONES, RUTA_ESTADO, Programador  # noqa: E402

APP = str(ROOT / "app.py")
TEXTO = ("Hola {NOMBRE}, te invitamos a las tutorías de primer año.\n"
         "¿Por qué recibí esto? Porque acompañamos a primer año.\n"
         "Si prefieres no recibir más mensajes, responde NO MÁS.")
ESTADO_PANEL = [RUTA_ESTADO, RUTA_DECISIONES, config.RUTA_BANDEJA, apoyos.RUTA_PROPUESTAS,
                apoyos.RUTA_CONSENTIMIENTOS, plan_estudio.RUTA_PLANES]

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def prog_tmp(d: Path, **flags: bool) -> Programador:
    p = Programador(d / "estado.json", d / "decisiones.csv", d / "bandeja.jsonl")
    p.registrar_caso("EST-0001", "alto", "correo", "Contabilidad General", **flags)
    return p


def llamadas_api() -> int:
    if not config.RUTA_LOG_API.is_file():
        return 0
    return sum(json.loads(l).get("tipo") == "llamada_api"
               for l in config.RUTA_LOG_API.read_text(encoding="utf-8").splitlines() if l.strip())


VISTAS = ("Jefe de carrera", "Tutor", "Estudiante", "Auditoría")


def app(vista: str) -> AppTest:
    """Carga la app; las vistas son pestañas (todas se renderizan), `vista` solo documenta la intención."""
    return AppTest.from_file(APP, default_timeout=180).run()


def pestana(at: AppTest, vista: str):  # noqa: ANN201
    """Bloque de la pestaña de una vista (para revisar solo su contenido)."""
    return next(t for t in at.tabs if t.label == vista)


def textos(at: AppTest) -> str:
    partes = []
    for tipo in ("title", "header", "subheader", "markdown", "caption", "text", "info", "warning", "error",
                 "success", "metric", "selectbox", "text_area", "text_input"):
        for el in getattr(at, tipo):
            partes.append(str(getattr(el, "value", "")))
            partes.append(str(getattr(el, "label", "")))
            partes += [str(o) for o in getattr(el, "options", []) or []]
    for el in list(at.dataframe) + list(at.table):
        partes.append(el.value.to_csv() if hasattr(el.value, "to_csv") else str(el.value))
    return "\n".join(partes)


# ---------------------------------------------------------------- unitarias
def unitarias() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        p = prog_tmp(d)
        m = p.crear_mensaje("EST-0001", TEXTO)
        p.avanzar(horas=23)
        antes = len(p.bandeja_estudiante("EST-0001"))
        p.avanzar(horas=1)
        b = p.bandeja_estudiante("EST-0001")
        ok3 = antes == 0 and len(b) == 1 and b[0]["enviado_sin_revision"] is True and m["estado"] == "ENVIADO"
    record("C3 No llega antes de 24 h; después llega marcado sin revisión", ok3,
           f"a las 23 h: {antes} mensajes; a las 24 h: {len(b)}, enviado_sin_revision={b[0]['enviado_sin_revision'] if b else None}")

    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        p = prog_tmp(d)
        m = p.crear_mensaje("EST-0001", TEXTO)
        nuevo = TEXTO.replace("las tutorías", "las tutorías vespertinas")
        p.avanzar(horas=10)
        p.editar(m["id_mensaje"], nuevo)
        sigue = m["estado"] == "PROGRAMADO"
        p.avanzar(horas=14)
        llego = p.bandeja_estudiante("EST-0001")
        try:
            p2_ok = False
            q = prog_tmp(d / "x") if (d / "x").mkdir() is None else None
            mc = q.crear_mensaje("EST-0001", TEXTO)
            q.cancelar(mc["id_mensaje"], "lo conversé en clases")
            q.avanzar(dias=30)
            p2_ok = not q.bandeja_estudiante("EST-0001") and len(q.estado["mensajes"]) == 1
        except Exception as exc:  # noqa: BLE001
            print("   error cancelar:", exc)
        try:
            p.crear_mensaje("EST-0001", TEXTO.replace("tutorías", "tutorías por tu riesgo"))
            filtro = False
        except ValueError:
            filtro = True
        ok4 = sigue and len(llego) == 1 and llego[0]["texto"] == nuevo and p2_ok and filtro
    record("C4 Editar cambia el texto que llega; Cancelar evita el envío", ok4,
           f"sigue programado tras editar={sigue}, llegó texto editado={bool(llego) and llego[0]['texto'] == nuevo}, "
           f"cancelado no llega={p2_ok}, filtro de palabras en textos={filtro}")

    resultados5 = {}
    for flag in ("dato_poco_confiable", "derivar_humano", "apoyo_externo"):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            p = prog_tmp(d, **({flag: True} if flag != "apoyo_externo" else {}))
            m = p.crear_mensaje("EST-0001", TEXTO, apoyo_externo=flag == "apoyo_externo")
            p.avanzar(horas=25)
            p.avanzar(dias=30)
            no_salio = not p.bandeja_estudiante("EST-0001") and m["estado"] == "REQUIERE_APROBACION"
            p.enviar_ahora(m["id_mensaje"])
            aprobado = m["estado"] == "ENVIADO" and m["enviado_sin_revision"] is False
            resultados5[flag] = no_salio and aprobado
    with tempfile.TemporaryDirectory() as t:   # check-in que llega con un mensaje ya programado
        p = prog_tmp(Path(t))
        m = p.crear_mensaje("EST-0001", TEXTO)
        p.avanzar(horas=5)
        p.marcar_derivar_humano("EST-0001")
        p.avanzar(dias=30)
        resultados5["derivar_humano_posterior"] = not p.bandeja_estudiante("EST-0001")
    record("C5 Las 3 excepciones nunca salen sin aprobación", all(resultados5.values()), str(resultados5))

    with tempfile.TemporaryDirectory() as t:
        p = prog_tmp(Path(t))
        p.crear_mensaje("EST-0001", TEXTO)
        p.avanzar(horas=24)
        p.avanzar(dias=6)
        sin_rec_6d = not any(m["tipo"] == "recordatorio" for m in p.estado["mensajes"])
        p.avanzar(dias=1)
        rec = [m for m in p.estado["mensajes"] if m["tipo"] == "recordatorio"]
        rec_prog = len(rec) == 1 and rec[0]["estado"] == "PROGRAMADO"
        p.avanzar(horas=24)
        p.avanzar(dias=30)
        p.avanzar(dias=30)
        enviados = [m for m in p.estado["mensajes"] if m["estado"] == "ENVIADO"]
        sin_resp = p.sin_respuesta() == ["EST-0001"]
    with tempfile.TemporaryDirectory() as t:   # salto directo de 30 días
        q = prog_tmp(Path(t))
        q.crear_mensaje("EST-0001", TEXTO)
        q.avanzar(dias=30)
        q.avanzar(dias=30)
        n_salto = len(q.bandeja_estudiante("EST-0001"))
    ok6 = sin_rec_6d and rec_prog and len(enviados) == 2 and sin_resp and n_salto == 2
    record("C6 Un único recordatorio a los 7 días; 30 días no generan más", ok6,
           f"sin recordatorio al día 6={sin_rec_6d}, programado al día 7={rec_prog}, enviados tras +60 días={len(enviados)}, "
           f"salto de 30 días={n_salto}, queda 'sin respuesta'={sin_resp}")

    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a = prog_tmp(d / "a" if (d / "a").mkdir() is None else d)
        a.crear_mensaje("EST-0001", TEXTO)
        a.avanzar(horas=24)
        a.avanzar(dias=3)
        a.registrar_respuesta("EST-0001")
        a.avanzar(dias=30)
        r1 = not any(m["tipo"] == "recordatorio" for m in a.estado["mensajes"])
        b = prog_tmp(d / "b" if (d / "b").mkdir() is None else d)
        b.crear_mensaje("EST-0001", TEXTO)
        b.avanzar(horas=24)
        b.avanzar(dias=7)
        b.registrar_respuesta("EST-0001")
        b.avanzar(dias=30)
        r2 = [m["estado"] for m in b.estado["mensajes"] if m["tipo"] == "recordatorio"] == ["CANCELADO"]
        c = prog_tmp(d / "c" if (d / "c").mkdir() is None else d)
        c.crear_mensaje("EST-0001", TEXTO)
        c.avanzar(horas=24)
        c.avanzar(dias=7)
        cancelados = c.no_quiero_mas("EST-0001")
        c.avanzar(dias=30)
        r3 = (cancelados == 1 and len(c.bandeja_estudiante("EST-0001")) == 1
              and all(m["estado"] != "PROGRAMADO" for m in c.estado["mensajes"]))
        try:
            c.crear_mensaje("EST-0001", TEXTO)
            r4 = False
        except ValueError:
            r4 = True
        dec = list(csv.DictReader(open(c.ruta_decisiones, encoding="utf-8")))
    record("C7 Responder o No quiero recibir más cancela el recordatorio", r1 and r2 and r3 and r4,
           f"respondió antes={r1}, respondió con recordatorio programado={r2}, no_quiero_mas cancela={r3}, "
           f"bloquea nuevos={r4}")

    with tempfile.TemporaryDirectory() as t:
        p = prog_tmp(Path(t))
        m1 = p.crear_mensaje("EST-0001", TEXTO)
        p.editar(m1["id_mensaje"], TEXTO + " ")
        p.cancelar(m1["id_mensaje"], "lo conversé en clases")
        m2 = p.crear_mensaje("EST-0001", TEXTO)
        p.contactar_en_persona(m2["id_mensaje"], "prefiero hablar en persona")
        m3 = p.crear_mensaje("EST-0001", TEXTO)
        p.enviar_ahora(m3["id_mensaje"])
        filas = list(csv.DictReader(open(p.ruta_decisiones, encoding="utf-8")))
    acciones = [f["accion"] for f in filas]
    ok8 = ({"editar", "cancelar", "contactar_en_persona", "enviar_ahora", "programar"} <= set(acciones)
           and all(f["hora_simulada"] and f["hora_real"] for f in filas)
           and any(f["accion"] == "cancelar" and f["motivo"] == "lo conversé en clases" for f in filas)
           and len(dec) > 0)
    try:
        Programador(Path(tempfile.mkdtemp()) / "e.json").cancelar("MSG-9999", "")
        motivo_obligatorio = False
    except ValueError:
        motivo_obligatorio = True
    record("C8 decisiones.csv con hora, acción y motivo", ok8 and motivo_obligatorio,
           f"acciones={sorted(set(acciones))}, cancelar sin motivo rechazado={motivo_obligatorio}")


# ---------------------------------------------------------------- ampliación (unitarias)
def ampliacion_unitarias() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        p = Programador(d / "e.json", d / "d.csv", d / "b.jsonl")
        p.registrar_caso("EST-0097", "medio", "whatsapp", "Contabilidad General")
        p.crear_mensaje("EST-0097", TEXTO)
        g = apoyos.GestorApoyos(d / "p.json", d / "c.csv")
        m = demo_panel.ofrecer_apoyo(p, g, "EST-0097", "AP-FUNDACION", "prueba")
        prop = g.propuestas_de("EST-0097")[0]
        pide_aut = "autorización" in m["texto"] and m["estado"] == "REQUIERE_APROBACION" and not problemas_invitacion(m["texto"])
        def derivado() -> bool:
            return g.etiqueta_estado(prop).startswith("Derivado")
        bloqueos = 0
        for paso in ("sin respuesta", "no acepto"):
            if paso == "no acepto":
                g.registrar_consentimiento(prop["id_propuesta"], acepta=False)
            try:
                g.activar(prop["id_propuesta"], aprobado_por_tutor=True)
            except PermissionError:
                bloqueos += 1
        sin_derivar = not derivado()
        prop2 = g.proponer("EST-0097", [{"id": "AP-FUNDACION", "razon": "segunda oferta"}])[0]
        g.registrar_consentimiento(prop2["id_propuesta"], acepta=True)
        g.activar(prop2["id_propuesta"], aprobado_por_tutor=True)
        filas = list(csv.DictReader(open(d / "c.csv", encoding="utf-8")))
        con_acepto = any(f["id_propuesta"] == prop2["id_propuesta"] and f["respuesta"] == "acepto" for f in filas)
        ok = (pide_aut and bloqueos == 2 and sin_derivar and g.etiqueta_estado(prop2).startswith("Derivado")
              and con_acepto and not g.externos_activos_sin_consentimiento())
    record("C11 Apoyo externo no aparece derivado sin Acepto registrado", ok,
           f"mensaje pide autorización y requiere aprobación={pide_aut}, bloqueos sin Acepto={bloqueos}/2, "
           f"derivado solo tras Acepto={con_acepto}")


# ---------------------------------------------------------------- AppTest
def con_app() -> None:
    demo_panel.reiniciar(ESTADO_PANEL)
    at = app("todas")
    errores = {"global": [str(e.value)[:200] for e in at.exception]}
    for v in VISTAS:
        bloque = pestana(at, v)
        errores[v] = [str(e.value)[:200] for e in bloque.exception] + ([] if len(bloque.children) else ["vacía"])
    record("C1 Las 4 vistas cargan sin excepciones", not any(errores.values()), str(errores))

    txt = textos(pestana(at, "Jefe de carrera"))
    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    nombres = [n for n in est["nombre_ficticio"] if n in txt]
    ids = re.findall(r"EST-\d{4}", txt)
    record("C2 Jefe de carrera sin nombres ni IDs", not nombres and not ids and len(txt) > 200,
           f"{len(txt)} caracteres revisados; nombres={nombres[:3]}, ids={ids[:3]}")

    # Mi plan: estudiante demo con plan posible y caso imposible
    def mi_plan(id_: str) -> AppTest:
        at = app("Estudiante")
        at.selectbox(key="est_sel").set_value(id_).run()
        at.button(key=f"btn_estimar_{id_}").click().run()
        at.button(key=f"btn_plan_{id_}").click().run()
        return at

    at_ok = mi_plan("EST-0197")
    tabla = [d.value for d in pestana(at_ok, "Estudiante").dataframe if "subtarea" in getattr(d.value, "columns", [])]
    plan_ok = bool(tabla) and len(tabla[0]) > 0 and not at_ok.exception
    at_no = mi_plan("EST-0389")
    est_no = pestana(at_no, "Estudiante")
    aviso = [w.value for w in est_no.warning if "No alcanza" in w.value]
    aviso_ok = bool(aviso) and not any("subtarea" in getattr(d.value, "columns", []) for d in est_no.dataframe)
    record("C13 Mi plan: plan para estudiante demo y aviso en el caso imposible", plan_ok and aviso_ok,
           f"EST-0197: {len(tabla[0]) if tabla else 0} bloques; EST-0389: {aviso[0][:70] if aviso else 'sin aviso'}…")

    # Plan no compartido -> el tutor no lo ve; compartido -> sí
    at_ok.button(key="guardar_plan_EST-0197").click().run()
    tutor = app("Tutor")
    tutor.selectbox(key="caso_tutor").set_value("EST-0197").run()
    tt = pestana(tutor, "Tutor")
    oculto = (any("no ha compartido" in c.value for c in tt.caption)
              and not any("subtarea" in getattr(d.value, "columns", []) for d in tt.dataframe))
    at_ok.checkbox(key="compartir_EST-0197").check().run()
    at_ok.button(key="guardar_plan_EST-0197").click().run()
    tutor2 = app("Tutor")
    tutor2.selectbox(key="caso_tutor").set_value("EST-0197").run()
    visible = any("subtarea" in getattr(d.value, "columns", []) for d in pestana(tutor2, "Tutor").dataframe)
    record("C12 El tutor no ve el plan si el estudiante no lo compartió", oculto and visible,
           f"no compartido oculto={oculto}, compartido visible={visible}")

    # Flujo completo en la app con el reloj simulado: programado -> 24 h -> llega; 7 días -> recordatorio
    demo_panel.reiniciar(ESTADO_PANEL)
    at = app("Estudiante")
    at.selectbox(key="est_sel").set_value("EST-0075").run()
    vacio = any("No tienes mensajes" in i.value for i in pestana(at, "Estudiante").info)
    at.sidebar.button(key="av24").click().run()
    llego = not any("No tienes mensajes" in i.value for i in pestana(at, "Estudiante").info)
    at.sidebar.button(key="av7").click().run()
    estado = json.loads(RUTA_ESTADO.read_text(encoding="utf-8"))
    rec = [m for m in estado["mensajes"] if m["id_seudonimo"] == "EST-0075" and m["tipo"] == "recordatorio"]
    print(f"      app: antes de 24 h vacío={vacio}, tras 24 h llegó={llego}, recordatorio={[m['estado'] for m in rec]}")
    if not (vacio and llego and len(rec) == 1):
        record("C3 (app) Flujo con reloj simulado", False, "el flujo en la app no coincide con la lógica")
    demo_panel.reiniciar(ESTADO_PANEL)


def recordatorios_cache() -> None:
    cliente = ClienteClaude(offline=True)
    combos = {(c["carrera"], demo_panel.canal_de(c["jornada"])) for c in demo_panel.casos() if c["nivel"] in ("medio", "alto")}
    origenes, malos = [], []
    for carrera, canal in sorted(combos):
        t = cliente.redactar_invitacion({"carrera": carrera}, canal, tipo="recordatorio")
        origenes.append(cliente.origen_en_cache("redactar_invitacion", {"carrera": carrera, "canal": canal, "tipo": "recordatorio"}))
        if problemas_invitacion(t):
            malos.append((carrera, canal, problemas_invitacion(t)))
    ok = not malos and all(o == "api" for o in origenes)
    record("C9 Recordatorios (tipo=recordatorio) filtrados y en caché offline", ok,
           f"{len(combos)} combinaciones carrera/canal, origen en caché={ {o: origenes.count(o) for o in set(origenes)} }"
           + (f"; problemas {malos}" if malos else ""))


def main() -> int:
    print("== Ciclo 5: panel, envíos programados y decisión humana (OFFLINE=1) ==")
    antes = llamadas_api()
    unitarias()
    ampliacion_unitarias()
    recordatorios_cache()
    con_app()
    despues = llamadas_api()
    record("C10 Todo funciona con OFFLINE=1", config.OFFLINE and despues == antes,
           f"OFFLINE={config.OFFLINE}, llamadas a la API durante la verificación={despues - antes}")
    results.sort(key=lambda r: int(re.match(r"C(\d+)", r[0]).group(1)))
    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo 5: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
