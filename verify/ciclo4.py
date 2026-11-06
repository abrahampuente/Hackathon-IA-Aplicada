"""Ciclo 4: integración con la API de Claude.

Criterios:
  C1  Modo online: las 4 funciones dan salida válida para los 12 casos demo y vienen de la API
  C2  Modo OFFLINE=1: las 4 funciones dan salida válida para los 12 casos, sin llamar a la API
  C3  Ninguna invitación contiene palabras prohibidas (riesgo, %, porcentaje, deserción, ...)
  C4  Invitaciones <= 120 palabras, con {NOMBRE}, "¿Por qué recibí esto?" y opción de salida
  C5  Ningún payload del log ni de payload_para_claude contiene nombre_ficticio o correo_ficticio
  C6  clasificar_checkin: el texto de crisis (de 8) sale con derivar_humano=true y urgencia alta
  C7  Menos de 200 llamadas a la API en el ciclo
  C8  payload_para_claude tiene exactamente los 5 campos; {NOMBRE} se completa localmente; la key no está en el log
Ampliación A/B:
  C9  sugerir_apoyos devuelve solo ids de apoyos.json (8 check-ins); catálogo de 8-10 apoyos con nota y a_validar
  C10 Ningún apoyo externo queda activado sin consentimiento registrado (ni nada sin decisión del tutor)
  C11 estimar_horas: JSON válido con horas_min <= horas_max para 5 tareas
  C12 planificar: bloques dentro de franjas, sin solapes, 30-120 min, fin >= 1 día antes, 20% holgura;
      caso imposible -> aviso sin plan; solo para quienes aceptaron el programa
  C13 La ampliación funciona online (API) y con OFFLINE=1 (desde caché)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import apoyos, config, generar_cache, plan_estudio  # noqa: E402
from src.claude_client import (ClienteClaude, problemas_clasificacion, problemas_estimacion,  # noqa: E402
                               problemas_explicacion, problemas_invitacion, problemas_resumen)
from src.seudonimizar import CAMPOS_PAYLOAD, insertar_nombre, payload_para_claude  # noqa: E402

PROHIBIDAS_LITERAL = ("riesgo", "%", "porcentaje", "deserción", "desercion", "desertar", "abandono",
                      "alerta", "predicción", "prediccion")

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def validos(r: dict) -> list[str]:
    """Errores de formato en una corrida completa de generar_cache.ejecutar."""
    errores = []
    for c in r["casos"]:
        for nombre, fn, valor in (("explicacion", problemas_explicacion, c["explicacion"]),
                                  ("invitacion", problemas_invitacion, c["invitacion"]),
                                  ("clasificacion", problemas_clasificacion, c["clasificacion"])):
            p = fn(valor)
            if p:
                errores.append(f"{c['id_seudonimo']}.{nombre}: {p}")
    for s, v in r["secciones"].items():
        if problemas_resumen(v["resumen"]):
            errores.append(f"seccion {s}")
    if len(r["casos"]) != 12:
        errores.append(f"{len(r['casos'])} casos")
    return errores


def origenes(r: dict) -> dict[str, int]:
    o = [c[k] for c in r["casos"] for k in ("origen_explicacion", "origen_invitacion", "origen_clasificacion")]
    o += [v["origen"] for v in r["secciones"].values()]
    return {x: o.count(x) for x in sorted(set(o))}


def log_lineas() -> list[dict]:
    if not config.RUTA_LOG_API.is_file():
        return []
    return [json.loads(l) for l in config.RUTA_LOG_API.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    print("== Ciclo 4: integración con Claude ==")
    hay_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    online = ClienteClaude(offline=False)
    r_on = generar_cache.ejecutar(online)  # también regenera data/cache_claude.json
    err_on, org_on = validos(r_on), origenes(r_on)
    todo_api = set(org_on) == {"api"}
    record("C1 Online: 4 funciones válidas para 12 casos, desde la API", not err_on and todo_api,
           f"key presente={hay_key}, llamadas={online.llamadas}, origen={org_on}"
           + (f", errores={err_on[:3]}" if err_on else ""))

    offline = ClienteClaude(offline=True)
    antes = online.llamadas_del_ciclo()
    r_off = generar_cache.ejecutar(offline)
    err_off = validos(r_off)
    sin_llamadas = offline.llamadas == 0 and offline.llamadas_del_ciclo() == antes
    record("C2 OFFLINE=1: 4 funciones válidas para 12 casos, sin API", not err_off and sin_llamadas,
           f"origen={origenes(r_off)}, llamadas={offline.llamadas}" + (f", errores={err_off[:3]}" if err_off else ""))

    invitaciones = [c["invitacion"] for r in (r_on, r_off) for c in r["casos"]]
    malas = [(i, w) for i, t in enumerate(invitaciones) for w in PROHIBIDAS_LITERAL if w in t.lower()]
    record("C3 Invitaciones sin palabras prohibidas", not malas,
           f"{len(invitaciones)} invitaciones revisadas" + (f"; encontradas {malas[:3]}" if malas else ""))

    formato = [problemas_invitacion(t) for t in invitaciones]
    malas_fmt = [p for p in formato if p]
    max_palabras = max(len(t.split()) for t in invitaciones)
    record("C4 Invitaciones <=120 palabras, {NOMBRE}, ¿Por qué recibí esto? y salida", not malas_fmt,
           f"máx {max_palabras} palabras" + (f"; problemas {malas_fmt[:2]}" if malas_fmt else ""))

    est = pd.read_csv(config.RUTA_ESTUDIANTES, encoding="utf-8")
    sensibles = set(est["nombre_ficticio"]) | set(est["correo_ficticio"])
    # también cada nombre y apellido sueltos no serían concluyentes; buscamos los valores completos
    lineas = log_lineas()
    texto_log = config.RUTA_LOG_API.read_text(encoding="utf-8") if lineas else ""
    en_log = [s for s in sensibles if s in texto_log]
    pred = pd.read_csv(config.RUTA_PREDICCIONES, encoding="utf-8")
    todos = est.merge(pred, on="id_seudonimo").to_dict(orient="records")
    en_payloads = [s for f in todos for s in (f["nombre_ficticio"], f["correo_ficticio"])
                   if s in json.dumps(payload_para_claude(f), ensure_ascii=False)]
    record("C5 Sin nombre_ficticio ni correo_ficticio en log ni payloads", not en_log and not en_payloads,
           f"{len(lineas)} registros en el log, {len(todos)} payloads revisados contra {len(sensibles)} valores")

    crisis_ok = all(
        r["checkins_prueba"][generar_cache.INDICE_CRISIS]["clasificacion"]["derivar_humano"] is True
        and r["checkins_prueba"][generar_cache.INDICE_CRISIS]["clasificacion"]["urgencia"] == "alta"
        for r in (r_on, r_off))
    no_crisis_validos = all(not problemas_clasificacion(x["clasificacion"])
                            for r in (r_on, r_off) for x in r["checkins_prueba"])
    resumen = [(x["clasificacion"]["necesidad"], x["clasificacion"]["urgencia"], x["clasificacion"]["derivar_humano"])
               for x in r_on["checkins_prueba"]]
    record("C6 Check-in de crisis -> derivar_humano=true, urgencia alta", crisis_ok and no_crisis_validos,
           f"8 textos: {resumen}")

    n = online.llamadas_del_ciclo()
    record("C7 < 200 llamadas a la API en el ciclo", n < config.MAX_LLAMADAS_API, f"{n} llamadas registradas")

    p = payload_para_claude(todos[0])
    campos_ok = tuple(p) == CAMPOS_PAYLOAD and len(p["razones"]) == 3
    nombre_ok = insertar_nombre(r_off["casos"][0]["invitacion"], "Ana").count("{NOMBRE}") == 0
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    key_fuera = not key or key not in texto_log
    record("C8 Payload de 5 campos, {NOMBRE} local, key fuera del log", campos_ok and nombre_ok and key_fuera,
           f"campos={list(p)}")

    # ---------------- Ampliación A: catálogo de apoyos ----------------
    ids_validos = apoyos.ids_catalogo()
    cat = json.loads(apoyos.RUTA_APOYOS.read_text(encoding="utf-8"))
    cat_ok = (8 <= len(cat["apoyos"]) <= 10 and "validar con Asuntos Estudiantiles" in cat["nota"]
              and all(a["a_validar"] is True for a in cat["apoyos"])
              and all(a["requiere_consentimiento"] for a in cat["apoyos"] if a["tipo"] == "externo")
              and any(a["tipo"] == "externo" for a in cat["apoyos"]))
    sugeridos = [(x["texto"][:28], [s["id"] for s in x["sugerencias"]]) for r in (r_on, r_off)
                 for x in r["ampliacion"]["sugerencias"]]
    invalidos = [(t, i) for t, ids in sugeridos for i in ids if i not in ids_validos]
    cantidad_ok = all(1 <= len(ids) <= 3 for _, ids in sugeridos) and len(sugeridos) == 16
    record("C9 sugerir_apoyos: solo ids del catálogo (8 check-ins)", cat_ok and not invalidos and cantidad_ok,
           f"catálogo={len(cat['apoyos'])} apoyos; online: {sugeridos[:8]}" + (f"; inválidos {invalidos}" if invalidos else ""))

    with tempfile.TemporaryDirectory() as tmp:
        gestor = apoyos.GestorApoyos(Path(tmp) / "p.json", Path(tmp) / "c.jsonl")
        propuestas = []
        for x in r_on["ampliacion"]["sugerencias"]:
            propuestas += gestor.proponer("EST-0001", x["sugerencias"])
        propuestas += gestor.proponer("EST-0002", [{"id": "AP-FUNDACION", "razon": "prueba de consentimiento"}])
        externas = [p for p in propuestas if p["tipo"] == "externo"]
        nada_activo_al_proponer = all(p["estado"] != "activo" for p in propuestas)
        bloqueadas = 0
        for p in externas:  # sin consentimiento: debe bloquear aunque el tutor apruebe
            try:
                gestor.activar(p["id_propuesta"], aprobado_por_tutor=True)
            except PermissionError:
                bloqueadas += 1
        gestor.registrar_consentimiento(externas[-1]["id_propuesta"], acepta=True)
        gestor.activar(externas[-1]["id_propuesta"], aprobado_por_tutor=True)
        if len(externas) > 1:
            gestor.registrar_consentimiento(externas[0]["id_propuesta"], acepta=False)
        try:
            gestor.activar(propuestas[0]["id_propuesta"], aprobado_por_tutor=False)
            sin_tutor_bloquea = False
        except PermissionError:
            sin_tutor_bloquea = True
        sin_consent = gestor.externos_activos_sin_consentimiento()
    ok = nada_activo_al_proponer and bloqueadas == len(externas) and not sin_consent and sin_tutor_bloquea
    record("C10 Ningún apoyo externo activo sin consentimiento", ok,
           f"{len(externas)} externas, {bloqueadas} bloqueadas sin consentimiento, activas sin sí={sin_consent or 'ninguna'}, "
           f"sin tutor bloquea={sin_tutor_bloquea}")

    # ---------------- Ampliación B: plan de estudio ----------------
    est_all = [(x["tarea"][:30], x["estimacion"]) for r in (r_on, r_off) for x in r["ampliacion"]["estimaciones"]]
    malas_est = [(t, problemas_estimacion(e)) for t, e in est_all if problemas_estimacion(e)]
    rangos = [(e["horas_min"], e["horas_max"]) for _, e in est_all[:5]]
    record("C11 estimar_horas: JSON válido con horas_min <= horas_max (5 tareas)",
           not malas_est and len(est_all) == 10, f"rangos online={rangos}" + (f"; {malas_est}" if malas_est else ""))

    disp = pd.read_csv(plan_estudio.RUTA_DISPONIBILIDAD, encoding="utf-8")
    errores_plan, n_planes, n_avisos = [], 0, 0
    for r in (r_on, r_off):
        for p in r["ampliacion"]["planes"]:
            if not p["acepto_programa"]:
                continue
            plan = p["plan"]
            if plan["ok"]:
                n_planes += 1
                e = plan_estudio.problemas_plan(plan, disp[disp["id_seudonimo"] == p["id_seudonimo"]], p["fecha_entrega"])
                errores_plan += [f"{p['id_seudonimo']}: {x}" for x in e]
                if plan["minutos_trabajo"] > 0.8 * plan["minutos_capacidad"]:
                    errores_plan.append(f"{p['id_seudonimo']}: sin 20% de holgura")
            else:
                n_avisos += 1
                if plan["bloques"] or not plan["aviso"] or plan["horas_faltantes"] <= 0:
                    errores_plan.append(f"{p['id_seudonimo']}: aviso inválido")
    # caso imposible explícito: 1 h semanal y 20 h de trabajo
    imposible = plan_estudio.planificar([{"nombre": "Trabajo largo", "horas": 20}],
                                        [{"dia": "domingo", "hora_inicio": "17:00", "hora_fin": "18:00"}], "2026-11-20")
    imposible_ok = (not imposible["ok"] and not imposible["bloques"] and imposible["horas_faltantes"] > 0
                    and "docente" in imposible["aviso"])
    no_acepto = next(p["id_seudonimo"] for p in r_on["ampliacion"]["planes"] if not p["acepto_programa"])
    try:
        plan_estudio.plan_para_estudiante(no_acepto, [{"nombre": "x", "horas": 1}], "2026-11-20")
        solo_aceptados = False
    except PermissionError:
        solo_aceptados = True
    record("C12 planificar: dentro de franjas, sin solapes, 1 día antes; imposible -> aviso",
           not errores_plan and imposible_ok and solo_aceptados and n_planes > 0,
           f"{n_planes} planes válidos, {n_avisos} avisos, caso imposible: faltan {imposible['horas_faltantes']} h, "
           f"solo aceptados={solo_aceptados}" + (f"; {errores_plan[:3]}" if errores_plan else ""))

    org_amp_on = [x["origen"] for x in r_on["ampliacion"]["sugerencias"] + r_on["ampliacion"]["estimaciones"]]
    org_amp_off = [x["origen"] for x in r_off["ampliacion"]["sugerencias"] + r_off["ampliacion"]["estimaciones"]]
    record("C13 Ampliación online desde la API y OFFLINE=1 desde caché",
           set(org_amp_on) == {"api"} and org_amp_off == org_amp_on and offline.llamadas == 0,
           f"online={ {o: org_amp_on.count(o) for o in set(org_amp_on)} }, offline igual={org_amp_off == org_amp_on}")

    print("\n-- Invitaciones de ejemplo (online) --")
    for c in r_on["casos"][:2]:
        print(f"[{c['id_seudonimo']} · {c['canal']} · {c['origen_invitacion']}]\n{c['invitacion']}\n")

    passed = sum(ok for _, ok, _ in results)
    print(f"== Resumen ciclo 4: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
