"""Ciclo correo: envío real SOLO para la demo, con lista blanca. Todas las pruebas usan SMTP simulado.

Criterios:
  C1  Con MODO_CORREO_REAL=0 no se abre ninguna conexión SMTP (mock: 0 llamadas), ni en la app
  C2  Un destinatario fuera de la lista blanca se rechaza (y se registra) aunque MODO_CORREO_REAL=1;
      dentro de la lista, se usa smtp.gmail.com:587 con STARTTLS
  C3  El payload enviado a Claude para EST-DEMO no contiene el correo real (log_api.jsonl);
      el mensaje se genera en vivo con modelo y tiempo de respuesta
  C4  La clave SMTP no aparece en ningún archivo del repo ni en los logs
  C5  Con un SMTP simulado que falla o tarda > 10 s, la app muestra el aviso y no lanza excepción
(run_all.py en PASS se verifica ejecutando run_all, que incluye este script.)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ["OFFLINE"] = "1"            # la app de prueba no llama a la API; C3 usa un cliente online explícito
os.environ["MODO_CORREO_REAL"] = "0"   # nada real salvo lo que cada prueba fije, siempre con SMTP simulado
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import smtplib  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import apoyos, config, correo, demo_panel, plan_estudio  # noqa: E402
from src.claude_client import ClienteClaude  # noqa: E402
from src.programador import RUTA_DECISIONES, RUTA_ESTADO, Programador  # noqa: E402

ESTADO_PANEL = [RUTA_ESTADO, RUTA_DECISIONES, config.RUTA_BANDEJA, apoyos.RUTA_PROPUESTAS,
                apoyos.RUTA_CONSENTIMIENTOS, plan_estudio.RUTA_PLANES]
REALES = {k: os.environ.get(k, "") for k in ("CORREOS_PERMITIDOS", "SMTP_USUARIO", "SMTP_CLAVE_APP")}
PRUEBA = {"CORREOS_PERMITIDOS": "permitido@ejemplo.cl", "SMTP_USUARIO": "bot@ejemplo.cl",
          "SMTP_CLAVE_APP": "clave-de-prueba-no-real"}

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


class ContadorSMTP:
    """SMTP simulado que cuenta conexiones y no envía nada."""
    conexiones: list[dict] = []

    def __init__(self, host: str, puerto: int, timeout: float = 0) -> None:
        self.reg = {"host": host, "puerto": puerto, "timeout": timeout, "starttls": False, "login": False, "enviado": 0}
        ContadorSMTP.conexiones.append(self.reg)

    def __enter__(self) -> "ContadorSMTP":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def starttls(self, context: object = None) -> None:
        self.reg["starttls"] = True

    def login(self, u: str, c: str) -> None:
        self.reg["login"] = True

    def send_message(self, msg: object) -> None:
        self.reg["enviado"] += 1


class FallaSMTP(ContadorSMTP):
    def __init__(self, host: str, puerto: int, timeout: float = 0) -> None:
        raise ConnectionRefusedError("simulado")


class LentoSMTP(ContadorSMTP):
    def __init__(self, host: str, puerto: int, timeout: float = 0) -> None:
        time.sleep(12)
        super().__init__(host, puerto, timeout)


def fijar_env(valores: dict[str, str]) -> None:
    for k, v in valores.items():
        os.environ[k] = v


def app_tutor() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()   # vistas en pestañas


def c1() -> None:
    ContadorSMTP.conexiones = []
    correo.SMTP_FACTORY = ContadorSMTP
    fijar_env({**PRUEBA, "MODO_CORREO_REAL": "0"})
    r1 = correo.enviar_correo("permitido@ejemplo.cl", correo.ASUNTO, "hola")
    r2 = correo.probar_conexion()
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        p = Programador(d / "e.json", d / "d.csv", d / "b.jsonl", enviador_real=demo_panel.enviador_real)
        p.registrar_caso("EST-DEMO", "alto", "correo", "Ingeniería en Informática", correo_real=True)
        m = p.crear_mensaje("EST-DEMO", "Hola {NOMBRE}, tutorías.\n¿Por qué recibí esto? Primer año.\n"
                                        "Si prefieres no recibir más mensajes, responde NO MÁS.")
        p.avanzar(horas=24)
        sin_aviso = m["estado"] == "ENVIADO" and "aviso_envio" not in m
    demo_panel.reiniciar(ESTADO_PANEL)
    at = app_tutor()
    at.sidebar.button(key="av24").click().run()
    app_ok = not at.exception
    n = len(ContadorSMTP.conexiones)
    ok = n == 0 and r1["motivo"] == "modo_simulado" and r2["motivo"] == "modo_simulado" and sin_aviso and app_ok
    record("C1 MODO_CORREO_REAL=0: 0 conexiones SMTP", ok,
           f"conexiones={n}, motivos={r1['motivo']}/{r2['motivo']}, flujo 24 h sin aviso={sin_aviso}, app sin excepción={app_ok}")


def c2() -> None:
    ContadorSMTP.conexiones = []
    correo.SMTP_FACTORY = ContadorSMTP
    fijar_env({**PRUEBA, "MODO_CORREO_REAL": "1"})
    antes = correo.RUTA_LOG_CORREO.read_text(encoding="utf-8").count("\n") if correo.RUTA_LOG_CORREO.is_file() else 0
    r = correo.enviar_correo("intruso@otro-dominio.com", correo.ASUNTO, "hola")
    lineas = correo.RUTA_LOG_CORREO.read_text(encoding="utf-8").splitlines()[antes:]
    registrado = any(json.loads(l)["motivo"] == "fuera_de_lista_blanca" for l in lineas)
    rechazado = r["ok"] is False and r["motivo"] == "fuera_de_lista_blanca" and not ContadorSMTP.conexiones
    sin_correo_crudo = all("intruso@otro-dominio.com" not in l for l in lineas)
    ok_envio = correo.enviar_correo("Permitido@Ejemplo.cl", correo.ASUNTO, "hola")
    c = ContadorSMTP.conexiones[0] if ContadorSMTP.conexiones else {}
    canal_ok = (ok_envio["ok"] and c.get("host") == "smtp.gmail.com" and c.get("puerto") == 587
                and c.get("starttls") and c.get("login") and c.get("enviado") == 1)
    record("C2 Fuera de la lista blanca se rechaza aunque MODO=1", rechazado and registrado and sin_correo_crudo and canal_ok,
           f"rechazado sin conexión={rechazado}, registrado (enmascarado)={registrado and sin_correo_crudo}, "
           f"permitido usa smtp.gmail.com:587+STARTTLS={canal_ok}")


def c3() -> None:
    fijar_env(REALES)
    cliente = ClienteClaude(offline=False, preferir_cache=True)
    texto, meta = demo_panel.generar_mensaje_demo(cliente)
    lineas = [json.loads(l) for l in config.RUTA_LOG_API.read_text(encoding="utf-8").splitlines() if l.strip()]
    demo = [e for e in lineas if e.get("caso") == demo_panel.ID_DEMO]
    sensibles = [x for x in correo.permitidos() + [REALES["SMTP_USUARIO"].lower()] if x]
    log_txt = config.RUTA_LOG_API.read_text(encoding="utf-8").lower()
    fugas = [x for x in sensibles if x in log_txt]
    payload_ok = bool(demo) and all(set(e["payload"]) <= {"carrera", "canal"} for e in demo)
    ok = payload_ok and not fugas and bool(sensibles) and meta.get("en_vivo") and "{NOMBRE}" in texto
    record("C3 Payload de EST-DEMO sin el correo real; generado en vivo", ok,
           f"{len(demo)} registros de EST-DEMO, campos={sorted({k for e in demo for k in e['payload']})}, "
           f"fugas={len(fugas)}, en vivo={meta.get('en_vivo')} · {meta.get('modelo')} · {meta.get('segundos')} s")


def c4() -> None:
    clave = REALES["SMTP_CLAVE_APP"].strip()
    variantes = {clave, clave.replace(" ", "")} - {""}
    if not variantes:
        record("C4 La clave no aparece en el repo ni en los logs", False, "no hay SMTP_CLAVE_APP para verificar")
        return
    revisados, hallados = 0, []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".pytest_cache"}]
        for f in filenames:
            p = Path(dirpath) / f
            if p == ROOT / ".env":
                continue
            try:
                contenido = p.read_bytes()
            except OSError:
                continue
            revisados += 1
            if any(v.encode() in contenido for v in variantes):
                hallados.append(str(p.relative_to(ROOT)))
    record("C4 La clave no aparece en el repo ni en los logs", not hallados,
           f"{revisados} archivos revisados (incluye data/ y logs; excluye .env)" + (f"; en {hallados}" if hallados else ""))


def c5() -> None:
    fijar_env({**PRUEBA, "MODO_CORREO_REAL": "1", "CORREOS_PERMITIDOS": "demo@ejemplo.cl"})
    resultados = {}
    for nombre, fabrica in (("falla", FallaSMTP), ("tarda >10 s", LentoSMTP)):
        correo.SMTP_FACTORY = fabrica
        demo_panel.reiniciar(ESTADO_PANEL)
        at = app_tutor()
        t0 = time.monotonic()
        at.sidebar.button(key="av24").click().run()
        dur = time.monotonic() - t0
        aviso = any(correo.AVISO_FALLO in w.value for w in at.sidebar.warning)
        estado = json.loads(RUTA_ESTADO.read_text(encoding="utf-8"))
        m = next(x for x in estado["mensajes"] if x["id_seudonimo"] == demo_panel.ID_DEMO)
        en_bandeja = m["estado"] == "ENVIADO" and m.get("aviso_envio") == correo.AVISO_FALLO
        resultados[nombre] = {"aviso": aviso, "sin_excepcion": not at.exception, "en_bandeja_simulada": en_bandeja,
                              "motivo": m.get("envio_real", {}).get("motivo"), "seg": round(dur, 1)}
    ok = all(r["aviso"] and r["sin_excepcion"] and r["en_bandeja_simulada"] for r in resultados.values())
    record("C5 SMTP que falla o tarda: aviso y sin excepción", ok, str(resultados))


def main() -> int:
    print("== Ciclo correo: envío real solo para la demo (SMTP simulado) ==")
    try:
        c1()
        c2()
        c3()
        c4()
        c5()
    finally:
        correo.SMTP_FACTORY = smtplib.SMTP
        fijar_env(REALES)
        os.environ["MODO_CORREO_REAL"] = "0"
        demo_panel.reiniciar(ESTADO_PANEL)
    c4()  # de nuevo al final: ningún log generado por las pruebas contiene la clave
    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo correo: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
