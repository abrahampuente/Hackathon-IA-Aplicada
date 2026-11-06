"""Plan de estudio determinista (sin Claude) para estudiantes que aceptaron el programa.

`planificar` reparte las subtareas en bloques de 30 a 120 minutos dentro de las
franjas de disponibilidad, termina al menos 1 día antes de la entrega y usa como
máximo el 80% de la capacidad disponible (20% de holgura). Si no cabe, no fuerza
nada: devuelve un aviso con las horas que faltan.

El plan organiza el trabajo; no resuelve la tarea (uso responsable de IA).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
import pandas as pd

from src import config

RUTA_DISPONIBILIDAD: Path = config.DATA_DIR / "disponibilidad.csv"
RUTA_PROGRAMA: Path = config.DATA_DIR / "programa.json"
DIAS: tuple[str, ...] = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
BLOQUE_MIN: int = 30
BLOQUE_MAX: int = 120
HOLGURA: float = 0.20
FECHA_REFERENCIA: date = date(2026, 11, 9)   # lunes; fija para que la demo sea reproducible


class Bloque(TypedDict):
    fecha: str
    dia: str
    inicio: str
    fin: str
    minutos: int
    subtarea: str


class Plan(TypedDict):
    ok: bool
    bloques: list[Bloque]
    minutos_trabajo: int
    minutos_capacidad: int
    holgura_pct: float
    ultimo_dia: str | None
    aviso: str | None
    horas_faltantes: float


def _min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def planificar(subtareas: list[dict[str, Any]], disponibilidad: pd.DataFrame | list[dict[str, str]],
               fecha_entrega: str | date, desde: date = FECHA_REFERENCIA) -> Plan:
    """Calcula el plan. `disponibilidad`: filas con dia (lunes..domingo), hora_inicio, hora_fin (HH:MM)."""
    entrega = date.fromisoformat(fecha_entrega) if isinstance(fecha_entrega, str) else fecha_entrega
    limite = entrega - timedelta(days=1)                        # último día con trabajo
    franjas = pd.DataFrame(disponibilidad)
    # minutos por subtarea, redondeados hacia arriba a múltiplos de 30
    pendientes = [[str(s["nombre"]), int(math.ceil(float(s["horas"]) * 60 / BLOQUE_MIN) * BLOQUE_MIN)]
                  for s in subtareas if float(s["horas"]) > 0]
    trabajo = sum(m for _, m in pendientes)

    # capacidad utilizable: franjas desde `desde` hasta `limite`, en múltiplos de 30 minutos
    huecos: list[tuple[date, int, int]] = []
    d = desde
    while d <= limite:
        dia = DIAS[d.weekday()]
        for _, f in franjas[franjas["dia"] == dia].sort_values("hora_inicio").iterrows():
            ini, fin = _min(f["hora_inicio"]), _min(f["hora_fin"])
            largo = (fin - ini) // BLOQUE_MIN * BLOQUE_MIN
            if largo >= BLOQUE_MIN:
                huecos.append((d, ini, ini + largo))
        d += timedelta(days=1)
    capacidad = sum(f - i for _, i, f in huecos)
    usable = int(capacidad * (1 - HOLGURA))

    if trabajo > usable:
        faltan = round((trabajo - usable) / 60, 1)
        return {"ok": False, "bloques": [], "minutos_trabajo": trabajo, "minutos_capacidad": capacidad,
                "holgura_pct": 0.0, "ultimo_dia": None, "horas_faltantes": faltan,
                "aviso": (f"No alcanza el tiempo: faltan {faltan} h para cubrir el trabajo dejando 20% de "
                          f"holgura antes del {limite.isoformat()}. Sugerencia: conversa con tu docente o "
                          "tu tutor sobre plazos, prioridades o apoyo.")}

    bloques: list[Bloque] = []
    i = 0
    for dia, ini, fin in huecos:
        cursor = ini
        while i < len(pendientes) and fin - cursor >= BLOQUE_MIN:
            nombre, resta = pendientes[i]
            dur = min(BLOQUE_MAX, resta, (fin - cursor) // BLOQUE_MIN * BLOQUE_MIN)
            bloques.append({"fecha": dia.isoformat(), "dia": DIAS[dia.weekday()], "inicio": _hhmm(cursor),
                            "fin": _hhmm(cursor + dur), "minutos": dur, "subtarea": nombre})
            cursor += dur
            pendientes[i][1] -= dur
            if pendientes[i][1] <= 0:
                i += 1
        if i >= len(pendientes):
            break
    return {"ok": True, "bloques": bloques, "minutos_trabajo": trabajo, "minutos_capacidad": capacidad,
            "holgura_pct": round(1 - trabajo / capacidad, 3) if capacidad else 0.0,
            "ultimo_dia": bloques[-1]["fecha"] if bloques else None, "aviso": None, "horas_faltantes": 0.0}


def problemas_plan(plan: Plan, disponibilidad: pd.DataFrame | list[dict[str, str]],
                   fecha_entrega: str | date) -> list[str]:
    """Verifica un plan: dentro de franjas, sin solapes, bloques de 30-120 min y fin >= 1 día antes."""
    entrega = date.fromisoformat(fecha_entrega) if isinstance(fecha_entrega, str) else fecha_entrega
    franjas = pd.DataFrame(disponibilidad)
    p: list[str] = []
    intervalos = []
    for b in plan["bloques"]:
        f = date.fromisoformat(b["fecha"])
        ini, fin = _min(b["inicio"]), _min(b["fin"])
        if not BLOQUE_MIN <= fin - ini <= BLOQUE_MAX:
            p.append(f"bloque de {fin - ini} min")
        dentro = any(_min(r["hora_inicio"]) <= ini and fin <= _min(r["hora_fin"])
                     for _, r in franjas[franjas["dia"] == DIAS[f.weekday()]].iterrows())
        if not dentro:
            p.append(f"fuera de franja {b['fecha']} {b['inicio']}")
        if f > entrega - timedelta(days=1):
            p.append(f"termina tarde {b['fecha']}")
        intervalos.append((datetime.combine(f, datetime.min.time()) + timedelta(minutes=ini),
                           datetime.combine(f, datetime.min.time()) + timedelta(minutes=fin)))
    intervalos.sort()
    p += ["solape" for a, b in zip(intervalos, intervalos[1:]) if b[0] < a[1]]
    return p


# --------------------------------------------------------------------------
# Datos simulados y control de acceso al programa
# --------------------------------------------------------------------------
def generar_disponibilidad(demo: pd.DataFrame, semilla: int = config.SEMILLA) -> pd.DataFrame:
    """Franjas semanales simuladas para los casos demo (vespertinos: noches y fin de semana)."""
    rng = np.random.default_rng(semilla)
    filas = []
    for k, (_, e) in enumerate(demo.iterrows()):
        vesp = e["jornada"] == "vespertina"
        if k == len(demo) - 1:   # caso con muy poca disponibilidad (para probar el aviso)
            opciones = [("domingo", "17:00", "18:00")]
        elif vesp:
            opciones = [("sabado", "10:00", "13:00"), ("domingo", "16:00", "18:30"),
                        ("martes", "07:00", "08:00"), ("jueves", "07:00", "08:30"), ("miercoles", "23:00", "23:45")]
        else:
            opciones = [("lunes", "15:00", "17:00"), ("miercoles", "15:30", "18:00"),
                        ("viernes", "14:00", "16:00"), ("sabado", "11:00", "13:00"), ("martes", "18:00", "19:30")]
        n = len(opciones) if len(opciones) == 1 else int(rng.integers(3, len(opciones) + 1))
        idx = sorted(rng.choice(len(opciones), n, replace=False))
        filas += [{"id_seudonimo": e["id_seudonimo"], "dia": opciones[j][0], "hora_inicio": opciones[j][1],
                   "hora_fin": opciones[j][2]} for j in idx]
    return pd.DataFrame(filas)


def guardar_datos_plan(demo: pd.DataFrame) -> tuple[Path, Path]:
    """Escribe data/disponibilidad.csv y data/programa.json (quiénes aceptaron el programa, simulado)."""
    disp = generar_disponibilidad(demo)
    disp.to_csv(RUTA_DISPONIBILIDAD, index=False, encoding="utf-8", lineterminator="\n")
    ids = demo["id_seudonimo"].tolist()
    aceptaron = [i for k, i in enumerate(ids) if k % 4 != 1]   # 3 de los 12 aún no aceptan
    RUTA_PROGRAMA.write_text(json.dumps({"nota": "Simulado", "aceptaron": aceptaron}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return RUTA_DISPONIBILIDAD, RUTA_PROGRAMA


def acepto_programa(id_seudonimo: str) -> bool:
    """True si el estudiante aceptó el programa de acompañamiento."""
    if not RUTA_PROGRAMA.is_file():
        return False
    return id_seudonimo in json.loads(RUTA_PROGRAMA.read_text(encoding="utf-8"))["aceptaron"]


RUTA_PLANES: Path = config.DATA_DIR / "planes_estudiantes.json"


def _leer_planes(ruta: Path) -> dict[str, Any]:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


def guardar_plan_estudiante(id_seudonimo: str, plan: Plan, tarea: str, compartido: bool,
                            ruta: Path = RUTA_PLANES) -> None:
    """Guarda el plan del estudiante. Es suyo: el tutor solo lo ve si `compartido` es True."""
    planes = _leer_planes(ruta)
    planes[id_seudonimo] = {"plan": plan, "tarea": tarea, "compartido": bool(compartido)}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(planes, ensure_ascii=False, indent=2), encoding="utf-8")


def compartir_plan(id_seudonimo: str, compartido: bool, ruta: Path = RUTA_PLANES) -> None:
    """El estudiante decide si comparte (o deja de compartir) su plan con el tutor."""
    planes = _leer_planes(ruta)
    if id_seudonimo in planes:
        planes[id_seudonimo]["compartido"] = bool(compartido)
        ruta.write_text(json.dumps(planes, ensure_ascii=False, indent=2), encoding="utf-8")


def plan_para_tutor(id_seudonimo: str, ruta: Path = RUTA_PLANES) -> dict[str, Any] | None:
    """Plan visible para el tutor, o None si no existe o el estudiante no lo compartió."""
    p = _leer_planes(ruta).get(id_seudonimo)
    return p if p and p["compartido"] else None


def plan_para_estudiante(id_seudonimo: str, subtareas: list[dict[str, Any]], fecha_entrega: str,
                         desde: date = FECHA_REFERENCIA) -> Plan:
    """Plan para un estudiante; solo si aceptó el programa (PermissionError si no)."""
    if not acepto_programa(id_seudonimo):
        raise PermissionError("El plan de estudio es solo para estudiantes que aceptaron el programa.")
    disp = pd.read_csv(RUTA_DISPONIBILIDAD, encoding="utf-8")
    return planificar(subtareas, disp[disp["id_seudonimo"] == id_seudonimo], fecha_entrega, desde)
