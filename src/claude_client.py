"""Cliente de Claude para el sistema de alerta temprana.

Reglas:
- La API key se lee de ANTHROPIC_API_KEY (.env) y nunca se imprime ni se registra.
- Todo dato pasa por `seudonimizar` antes de salir.
- OFFLINE=1, falta de key o error de la API -> respuesta desde data/cache_claude.json;
  si no hay caché, respuesta local de plantilla (origen "plantilla_local").
- Cada intento de llamada queda en data/log_api.jsonl con el prompt enviado.
- Tope de `config.MAX_LLAMADAS_API` llamadas por ciclo (contadas en el log).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from src import config
from src.apoyos import cargar_catalogo
from src.seudonimizar import MARCADOR_NOMBRE, preparar_payload, redactar_pii

Necesidad = Literal["economica", "academica", "emocional", "logistica", "ninguna"]
Urgencia = Literal["baja", "media", "alta"]
Canal = Literal["correo", "whatsapp"]
Origen = Literal["api", "cache", "plantilla_local"]

NECESIDADES: tuple[str, ...] = ("economica", "academica", "emocional", "logistica", "ninguna")
URGENCIAS: tuple[str, ...] = ("baja", "media", "alta")
ESQUEMA_CHECKIN: dict[str, Any] = {
    "type": "object",
    "properties": {
        "necesidad": {"type": "string", "enum": list(NECESIDADES)},
        "urgencia": {"type": "string", "enum": list(URGENCIAS)},
        "resumen": {"type": "string"},
        "derivar_humano": {"type": "boolean"},
    },
    "required": ["necesidad", "urgencia", "resumen", "derivar_humano"],
    "additionalProperties": False,
}
SISTEMA: str = ("Apoyas a un equipo de acompañamiento estudiantil en Chile. Escribes en español de Chile, "
                "claro y respetuoso. Nunca inventas datos.")
# Modelos que aceptan `output_config.effort` y la cadena de respaldo `fallbacks: "default"`.
_MODELOS_EFFORT = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5", "claude-opus-4-8",
                   "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6")
_MODELOS_FALLBACK = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

# Señales de crisis: se revisan localmente SIEMPRE, también sobre la respuesta de la API.
_CRISIS = ("quitarme la vida", "matarme", "suicid", "no quiero seguir viviendo", "no quiero vivir",
           "hacerme dano", "hacerme daño", "no vale la pena vivir", "desaparecer para siempre",
           "terminar con todo", "me quiero morir", "quiero morir", "me pegan", "me golpea")


class ClasificacionCheckin(TypedDict):
    necesidad: Necesidad
    urgencia: Urgencia
    resumen: str
    derivar_humano: bool


class LimiteLlamadasError(RuntimeError):
    """Se alcanzó el tope de llamadas a la API para este ciclo."""


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar palabras."""
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def cargar_prompt(nombre: str) -> str:
    """Lee `prompts/<nombre>.txt`."""
    return (config.PROMPTS_DIR / f"{nombre}.txt").read_text(encoding="utf-8")


def detectar_crisis(texto: str) -> bool:
    """True si el texto contiene señales de crisis o riesgo para la persona."""
    t = _normalizar(texto)
    return any(_normalizar(s) in t for s in _CRISIS)


# --------------------------------------------------------------------------
# Validadores (públicos para que verify y la app los reutilicen)
# --------------------------------------------------------------------------
def problemas_invitacion(texto: str) -> list[str]:
    """Lista de reglas que la invitación incumple (vacía si es válida)."""
    problemas = []
    t = _normalizar(texto)
    prohibidas = [p for p in config.PALABRAS_PROHIBIDAS_INVITACION if _normalizar(p) in t]
    if prohibidas:
        problemas.append(f"palabras prohibidas: {prohibidas}")
    if len(texto.split()) > config.MAX_PALABRAS_INVITACION:
        problemas.append(f"{len(texto.split())} palabras")
    if MARCADOR_NOMBRE not in texto:
        problemas.append("sin {NOMBRE}")
    if "¿Por qué recibí esto?" not in texto:
        problemas.append("sin línea ¿Por qué recibí esto?")
    if "no recibir mas" not in t:
        problemas.append("sin opción de no recibir más mensajes")
    return problemas


def problemas_explicacion(texto: str) -> list[str]:
    """Reglas de la explicación al tutor: 3 a 4 líneas no vacías."""
    lineas = [l for l in texto.splitlines() if l.strip()]
    return [] if 3 <= len(lineas) <= 4 else [f"{len(lineas)} líneas"]


def problemas_resumen(texto: str) -> list[str]:
    """Reglas del resumen por sección: no vacío, sin IDs ni correos."""
    problemas = []
    if not texto.strip():
        problemas.append("vacío")
    if re.search(r"EST-\w{4}", texto):
        problemas.append("contiene IDs")
    if "@" in texto:
        problemas.append("contiene correos")
    return problemas


def problemas_clasificacion(c: Any) -> list[str]:
    """Valida el dict de clasificación de check-in."""
    if not isinstance(c, dict):
        return ["no es un objeto"]
    p = []
    if c.get("necesidad") not in NECESIDADES:
        p.append(f"necesidad={c.get('necesidad')}")
    if c.get("urgencia") not in URGENCIAS:
        p.append(f"urgencia={c.get('urgencia')}")
    if not isinstance(c.get("resumen"), str):
        p.append("resumen")
    if not isinstance(c.get("derivar_humano"), bool):
        p.append("derivar_humano")
    return p


# --------------------------------------------------------------------------
# Respuestas locales (sin API)
# --------------------------------------------------------------------------
INVITACION_FIJA: dict[str, str] = {
    "correo": (
        "Hola {NOMBRE}:\n\n"
        "Te escribimos del Equipo de Acompañamiento Estudiantil. Este semestre tenemos espacios para "
        "primer año de {carrera}: tutorías de ramos, apoyo para organizar tus tiempos y conversación con un "
        "tutor. Son voluntarios, sin costo y con horarios pensados también para quienes trabajan.\n\n"
        "Si te interesa, responde este correo y coordinamos un horario que te acomode.\n\n"
        "¿Por qué recibí esto? Porque acompañamos a estudiantes de primer año durante su primer semestre.\n"
        "Si prefieres no recibir más mensajes, responde NO MÁS.\n\n"
        "Equipo de Acompañamiento Estudiantil"
    ),
    "whatsapp": (
        "Hola {NOMBRE} 👋 Somos el Equipo de Acompañamiento Estudiantil. Para primer año de {carrera} "
        "tenemos tutorías, apoyo para organizar tus tiempos y conversación con un tutor, gratis y en "
        "horarios compatibles con el trabajo. ¿Te gustaría que coordinemos un espacio?\n"
        "¿Por qué recibí esto? Porque acompañamos a primer año durante el semestre.\n"
        "Si prefieres no recibir más mensajes, responde NO MÁS."
    ),
}


RECORDATORIO_FIJO: dict[str, str] = {
    "correo": (
        "Hola {NOMBRE}:\n\n"
        "Solo te recordamos que los espacios de acompañamiento para primer año de {carrera} siguen "
        "disponibles cuando los necesites: tutorías y apoyo para organizar tus tiempos.\n\n"
        "¿Por qué recibí esto? Porque acompañamos a estudiantes de primer año durante el semestre.\n"
        "Si prefieres no recibir más mensajes, responde NO MÁS.\n\n"
        "Equipo de Acompañamiento Estudiantil"
    ),
    "whatsapp": (
        "Hola {NOMBRE}, te recordamos que las tutorías y el apoyo para organizar tus tiempos siguen "
        "disponibles para primer año de {carrera}, cuando te acomode.\n"
        "¿Por qué recibí esto? Porque acompañamos a primer año durante el semestre.\n"
        "Si prefieres no recibir más mensajes, responde NO MÁS."
    ),
}


def _explicacion_local(p: dict[str, Any]) -> str:
    r = p.get("razones", [])
    return (f"Qué cambió: {' '.join(r[:2])}\n"
            f"Qué explorar: cómo ha vivido estas semanas y qué le ha costado más organizar; {r[2] if len(r) > 2 else ''}\n"
            "Primer contacto: un mensaje breve ofreciendo 15 minutos de conversación en un horario que le acomode.\n"
            f"Ojo: el riesgo ({p.get('riesgo')}%) es una estimación del modelo; la decisión es del tutor.")


def _clasificacion_local(texto: str) -> ClasificacionCheckin:
    """Clasificador por palabras clave (respaldo sin API)."""
    t = _normalizar(texto)
    reglas = [
        ("emocional", ("ansiedad", "agotad", "no doy mas", "angustia", "triste", "no se si puedo seguir",
                       "congelar", "no se si esta carrera", "problemas para dormir", "cosas en mi familia")),
        ("economica", ("plata", "beca", "arancel", "pagar", "pasaje", "alcanza", "segundo trabajo", "deuda")),
        ("logistica", ("turno", "trabajo", "jefe", "horas extra", "pega", "viaje", "cuidando", "hijo",
                       "cambie de casa", "retail", "noche", "llego tarde")),
        ("academica", ("materia", "prueba", "ramo", "nota", "plataforma", "tutoria", "entender", "ritmo",
                       "entendi", "atrasad")),
    ]
    necesidad: str = "ninguna"
    for cat, claves in reglas:
        if any(k in t for k in claves):
            necesidad = cat
            break
    crisis = detectar_crisis(texto)
    deja = any(k in t for k in ("congelar", "dejar la carrera", "no se si puedo seguir", "retirarme"))
    urgencia = "alta" if crisis else ("media" if deja or necesidad in ("emocional", "economica") else "baja")
    return {
        "necesidad": "emocional" if crisis else necesidad,  # type: ignore[typeddict-item]
        "urgencia": urgencia,  # type: ignore[typeddict-item]
        "resumen": ("Señales de crisis: requiere contacto humano inmediato." if crisis
                    else f"Necesidad {necesidad if necesidad != 'ninguna' else 'no identificada'}."),
        "derivar_humano": crisis or deja,
    }


def _resumen_local(agregados: dict[str, Any]) -> str:
    a = agregados
    semanas = a.get("asistencia_por_semana", [])
    tramo = f"de {semanas[0]:.0f}% a {semanas[-1]:.0f}%" if semanas else "sin datos"
    return (f"- Asistencia promedio por semana {tramo}.\n"
            f"- Promedio de notas {a.get('nota_promedio', 0):.1f}; {a.get('pct_notas_rojas', 0):.0f}% de notas bajo 4,0.\n"
            f"- {a.get('pct_alerta', 0):.0f}% de la sección en nivel medio o alto.\n"
            "- Acción sugerida: tutoría grupal en el ramo con más notas bajo 4,0 y revisar horarios de inicio.")


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------
class ClienteClaude:
    """Envoltorio sobre el SDK `anthropic` con validación, caché offline y registro de llamadas."""

    def __init__(self, offline: bool | None = None, modelo: str | None = None,
                 ruta_cache: Path | None = None, ruta_log: Path | None = None,
                 preferir_cache: bool = False) -> None:
        self.offline: bool = config.OFFLINE if offline is None else offline
        # preferir_cache: si ya hay una respuesta de la API en caché, se usa sin volver a llamar (app y panel)
        self.preferir_cache: bool = preferir_cache
        self.modelo: str = modelo or config.ANTHROPIC_MODEL
        self.ruta_cache: Path = ruta_cache or config.RUTA_CACHE_CLAUDE
        self.ruta_log: Path = ruta_log or config.RUTA_LOG_API
        self.llamadas: int = 0
        self.ultimo_origen: Origen = "plantilla_local"
        self.ultimo_desde_cache: bool = False
        self._cache: dict[str, Any] = self._leer_cache()
        self._sdk: Any = None

    # ---- caché y log ------------------------------------------------------
    def _leer_cache(self) -> dict[str, Any]:
        if self.ruta_cache.is_file():
            return json.loads(self.ruta_cache.read_text(encoding="utf-8"))
        return {"version": 1, "entradas": {}}

    def guardar_cache(self) -> Path:
        """Escribe la caché a disco."""
        self.ruta_cache.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_cache.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2, sort_keys=True),
                                   encoding="utf-8")
        return self.ruta_cache

    @staticmethod
    def clave(tarea: str, datos: Any) -> str:
        """Clave de caché estable para (tarea, datos)."""
        bruto = json.dumps(datos, ensure_ascii=False, sort_keys=True)
        return f"{tarea}:{hashlib.sha256(bruto.encode()).hexdigest()[:16]}"

    def _registrar(self, evento: dict[str, Any]) -> None:
        self.ruta_log.parent.mkdir(parents=True, exist_ok=True)
        evento = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "ciclo": config.CICLO_ACTUAL, "modelo": self.modelo, **evento}
        with open(self.ruta_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(evento, ensure_ascii=False) + "\n")

    def llamadas_del_ciclo(self) -> int:
        """Llamadas reales a la API registradas en el log para el ciclo actual."""
        if not self.ruta_log.is_file():
            return 0
        n = 0
        for linea in self.ruta_log.read_text(encoding="utf-8").splitlines():
            e = json.loads(linea)
            n += e.get("ciclo") == config.CICLO_ACTUAL and e.get("tipo") == "llamada_api"
        return n

    # ---- llamada a la API -------------------------------------------------
    def _cliente_sdk(self) -> Any | None:
        if self._sdk is None:
            key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            if not key:
                return None
            import anthropic
            self._sdk = anthropic.Anthropic(api_key=key, timeout=60.0, max_retries=2)
        return self._sdk

    def _llamar(self, tarea: str, prompt: str, datos: Any, max_tokens: int = 4096,
                esquema: dict[str, Any] | None = None) -> str | None:
        """Una llamada a Claude. Devuelve el texto o None si no se pudo (sin lanzar)."""
        base = {"tarea": tarea, "payload": datos, "prompt": prompt}
        if self.offline:
            return None
        sdk = self._cliente_sdk()
        if sdk is None:
            self._registrar({**base, "tipo": "sin_api_key", "resultado": "no_enviado"})
            return None
        if self.llamadas_del_ciclo() >= config.MAX_LLAMADAS_API:
            # Tope alcanzado: no se llama; se sirve desde caché o plantilla local.
            self._registrar({**base, "tipo": "limite_alcanzado", "resultado": "no_enviado"})
            return None
        import anthropic

        kwargs: dict[str, Any] = {
            "model": self.modelo, "max_tokens": max_tokens, "system": SISTEMA,
            "messages": [{"role": "user", "content": prompt}],
        }
        output_config: dict[str, Any] = {}
        if self.modelo.startswith(_MODELOS_EFFORT):
            output_config["effort"] = config.CLAUDE_EFFORT
        if esquema is not None:
            output_config["format"] = {"type": "json_schema", "schema": esquema}
        if output_config:
            kwargs["output_config"] = output_config
        self.llamadas += 1
        try:
            if self.modelo in _MODELOS_FALLBACK:
                resp = sdk.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                fallbacks="default", **kwargs)
            else:
                resp = sdk.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            self._registrar({**base, "tipo": "llamada_api", "resultado": f"error_http_{exc.status_code}"})
            return None
        except anthropic.APIConnectionError:
            self._registrar({**base, "tipo": "llamada_api", "resultado": "error_conexion"})
            return None
        texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        ok = resp.stop_reason not in ("refusal", "max_tokens") and bool(texto)
        self._registrar({**base, "tipo": "llamada_api", "resultado": "ok" if ok else "invalida",
                         "stop_reason": resp.stop_reason, "modelo_respuesta": resp.model,
                         "tokens_entrada": resp.usage.input_tokens, "tokens_salida": resp.usage.output_tokens})
        return texto if ok else None

    def _resolver(self, tarea: str, datos: Any, generar: Callable[[], Any | None],
                  validar: Callable[[Any], list[str]], local: Callable[[], Any]) -> Any:
        """Online -> valida -> caché; si falla o es offline -> caché -> respuesta local."""
        k = self.clave(tarea, datos)
        self.ultimo_desde_cache = False
        previo = self._cache["entradas"].get(k)
        if (self.preferir_cache and previo and previo["origen"] == "api"
                and not validar(previo["respuesta"])):
            self.ultimo_origen, self.ultimo_desde_cache = "api", True
            return previo["respuesta"]
        if not self.offline:
            resultado = generar()
            if resultado is not None and not validar(resultado):
                self._cache["entradas"][k] = {"tarea": tarea, "respuesta": resultado, "origen": "api",
                                              "modelo": self.modelo}
                self.ultimo_origen = "api"
                return resultado
        entrada = self._cache["entradas"].get(k)
        if entrada and not validar(entrada["respuesta"]):
            self.ultimo_origen = entrada["origen"]  # contenido: "api" o "plantilla_local"
            self.ultimo_desde_cache = True
            return entrada["respuesta"]
        resultado = local()
        if k not in self._cache["entradas"]:
            self._cache["entradas"][k] = {"tarea": tarea, "respuesta": resultado, "origen": "plantilla_local",
                                          "modelo": None}
        self.ultimo_origen = "plantilla_local"
        return resultado

    def origen_en_cache(self, tarea: str, datos: Any) -> str | None:
        """Origen ('api' o 'plantilla_local') de la entrada en caché, o None."""
        e = self._cache["entradas"].get(self.clave(tarea, datos))
        return e["origen"] if e else None

    # ---- las 4 tareas -----------------------------------------------------
    def explicar_a_tutor(self, payload: dict[str, Any]) -> str:
        """3 a 4 líneas para el tutor: qué cambió, qué explorar (sin diagnosticar) y primer contacto."""
        datos = preparar_payload(payload)
        prompt = cargar_prompt("explicar_riesgo").format(payload=json.dumps(datos, ensure_ascii=False))

        def generar() -> str | None:
            for _ in range(2):  # 1 reintento si el formato no cumple
                t = self._llamar("explicar_a_tutor", prompt, datos)
                if t is not None and not problemas_explicacion(t):
                    return t
            return None

        return self._resolver("explicar_a_tutor", datos, generar, problemas_explicacion,
                              lambda: _explicacion_local(datos))

    def redactar_invitacion(self, payload: dict[str, Any], canal: Canal = "correo",
                            tipo: Literal["invitacion", "recordatorio"] = "invitacion") -> str:
        """Invitación no estigmatizante (<= 120 palabras, tuteo, {NOMBRE}, ¿Por qué recibí esto?, salida).

        tipo="recordatorio": más breve y sin presión; mismo filtro de palabras prohibidas.
        Solo usa la carrera del payload: riesgo, nivel y razones NO se envían para esta tarea.
        """
        datos = {"carrera": payload["carrera"], "canal": canal}
        if tipo == "recordatorio":
            datos["tipo"] = "recordatorio"   # la invitación conserva su clave de caché original
        datos = preparar_payload(datos)
        plantilla = "recordatorio" if tipo == "recordatorio" else "invitacion"
        prompt = cargar_prompt(plantilla).format(canal=canal, carrera=datos["carrera"])
        fija = RECORDATORIO_FIJO if tipo == "recordatorio" else INVITACION_FIJA

        def generar() -> str | None:
            for _ in range(2):  # si falla el filtro, se regenera 1 vez
                t = self._llamar("redactar_invitacion", prompt, datos, max_tokens=2048)
                if t is not None and not problemas_invitacion(t):
                    return t
            return None

        return self._resolver("redactar_invitacion", datos, generar, problemas_invitacion,
                              lambda: fija[canal].replace("{carrera}", datos["carrera"]))

    def clasificar_checkin(self, texto: str) -> ClasificacionCheckin:
        """Clasifica un check-in. Ante señales de crisis: derivar_humano=True y urgencia alta, siempre."""
        limpio = redactar_pii(texto)
        prompt = cargar_prompt("clasificar_checkin").format(texto=limpio)

        def generar() -> dict | None:
            for _ in range(2):  # 1 reintento si el JSON no se puede leer
                t = self._llamar("clasificar_checkin", prompt, {"texto": limpio}, max_tokens=2048,
                                 esquema=ESQUEMA_CHECKIN)
                if t is None:
                    continue
                try:
                    c = json.loads(t)
                except json.JSONDecodeError:
                    continue
                if not problemas_clasificacion(c):
                    return c
            return None

        c = dict(self._resolver("clasificar_checkin", {"texto": limpio}, generar,
                                problemas_clasificacion, lambda: _clasificacion_local(limpio)))
        if detectar_crisis(limpio):  # regla de seguridad local, por encima de cualquier respuesta
            c["derivar_humano"], c["urgencia"] = True, "alta"
        return c  # type: ignore[return-value]

    def resumir_seccion(self, estadisticas_agregadas: dict[str, Any]) -> str:
        """Patrón de una sección para la jefatura de carrera, solo con datos agregados."""
        datos = preparar_payload(estadisticas_agregadas)
        prompt = cargar_prompt("resumen_seccion").format(agregados=json.dumps(datos, ensure_ascii=False))

        def generar() -> str | None:
            for _ in range(2):
                t = self._llamar("resumir_seccion", prompt, datos, max_tokens=4096)
                if t is not None and not problemas_resumen(t):
                    return t
            return None

        return self._resolver("resumir_seccion", datos, generar, problemas_resumen,
                              lambda: _resumen_local(datos))

    # ---- ampliación: apoyos y plan de estudio --------------------------------
    def sugerir_apoyos(self, necesidad: str, resumen_checkin: str) -> list[dict[str, str]]:
        """Hasta 3 apoyos del catálogo ({id, razon}). Solo ids existentes; nunca inventa beneficios."""
        catalogo = cargar_catalogo()
        ids = sorted(a["id"] for a in catalogo)
        datos = {"necesidad": necesidad, "resumen": redactar_pii(resumen_checkin)}
        campos = ("id", "nombre", "tipo", "necesidad", "descripcion", "requisitos")
        cat_txt = json.dumps([{k: a[k] for k in campos} for a in catalogo], ensure_ascii=False, indent=1)
        prompt = cargar_prompt("sugerir_apoyos").format(necesidad=necesidad, resumen=datos["resumen"],
                                                         catalogo=cat_txt)
        esquema = {
            "type": "object",
            "properties": {"sugerencias": {"type": "array", "items": {
                "type": "object",
                "properties": {"id": {"type": "string", "enum": ids}, "razon": {"type": "string"}},
                "required": ["id", "razon"], "additionalProperties": False}}},
            "required": ["sugerencias"], "additionalProperties": False,
        }
        validar = lambda s: problemas_sugerencias(s, set(ids))  # noqa: E731

        def generar() -> list | None:
            for _ in range(2):
                t = self._llamar("sugerir_apoyos", prompt, datos, max_tokens=2048, esquema=esquema)
                try:
                    s = _depurar_sugerencias(json.loads(t)["sugerencias"]) if t else None
                except (json.JSONDecodeError, KeyError, TypeError):
                    s = None
                if s is not None and not validar(s):
                    return s
            return None

        return self._resolver("sugerir_apoyos", datos, generar, validar,
                              lambda: _sugerencias_local(necesidad, datos["resumen"]))

    def estimar_horas(self, descripcion_tarea: str, asignatura: str, fecha_entrega: str) -> dict[str, Any]:
        """Estimación editable: {horas_min, horas_max, subtareas: [{nombre, horas}], supuestos}.

        Claude solo estima y divide en pasos; no resuelve la tarea.
        """
        datos = {"descripcion": redactar_pii(descripcion_tarea), "asignatura": asignatura,
                 "fecha_entrega": fecha_entrega}
        prompt = cargar_prompt("estimar_horas").format(**datos)

        def generar() -> dict | None:
            for _ in range(2):
                t = self._llamar("estimar_horas", prompt, datos, max_tokens=2048, esquema=ESQUEMA_HORAS)
                try:
                    e = json.loads(t) if t else None
                except json.JSONDecodeError:
                    e = None
                if e is not None and not problemas_estimacion(e):
                    return e
            return None

        return self._resolver("estimar_horas", datos, generar, problemas_estimacion,
                              lambda: _estimacion_local(datos["descripcion"]))


# --------------------------------------------------------------------------
# Ampliación: validadores y respaldos locales
# --------------------------------------------------------------------------
ESQUEMA_HORAS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "horas_min": {"type": "number"},
        "horas_max": {"type": "number"},
        "subtareas": {"type": "array", "items": {
            "type": "object",
            "properties": {"nombre": {"type": "string"}, "horas": {"type": "number"}},
            "required": ["nombre", "horas"], "additionalProperties": False}},
        "supuestos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["horas_min", "horas_max", "subtareas", "supuestos"],
    "additionalProperties": False,
}


def _depurar_sugerencias(s: Any) -> list[dict[str, str]]:
    """Quita duplicados y deja como máximo 3 sugerencias."""
    vistos, out = set(), []
    for x in s if isinstance(s, list) else []:
        if isinstance(x, dict) and x.get("id") not in vistos:
            vistos.add(x.get("id"))
            out.append({"id": x.get("id"), "razon": x.get("razon", "")})
    return out[:3]


def problemas_sugerencias(s: Any, ids_validos: set[str]) -> list[str]:
    """Valida sugerencias: 1 a 3, ids del catálogo, razón de una línea."""
    if not isinstance(s, list) or not 1 <= len(s) <= 3:
        return ["cantidad"]
    p = [f"id inexistente {x.get('id')}" for x in s if x.get("id") not in ids_validos]
    p += [f"razón inválida {x.get('id')}" for x in s
          if not isinstance(x.get("razon"), str) or not x["razon"].strip() or "\n" in x["razon"].strip()]
    return p


def problemas_estimacion(e: Any) -> list[str]:
    """Valida la estimación de horas."""
    if not isinstance(e, dict):
        return ["no es objeto"]
    p = []
    hmin, hmax = e.get("horas_min"), e.get("horas_max")
    if not all(isinstance(h, (int, float)) and h > 0 for h in (hmin, hmax)):
        p.append("horas no positivas")
    elif hmin > hmax:
        p.append("horas_min > horas_max")
    sub = e.get("subtareas")
    if not isinstance(sub, list) or not sub or not all(
            isinstance(x, dict) and isinstance(x.get("nombre"), str) and isinstance(x.get("horas"), (int, float))
            and x["horas"] > 0 for x in sub):
        p.append("subtareas")
    if not isinstance(e.get("supuestos"), list):
        p.append("supuestos")
    return p


_REGLAS_APOYO: list[tuple[tuple[str, ...], str, str]] = [
    (("computador", "notebook", "internet"), "AP-EQUIPOS", "Préstamo de equipo para el semestre."),
    (("pasaje", "transporte", "locomocion"), "AP-TNE", "Puede rebajar el costo de los pasajes."),
    (("libro", "bibliografia"), "AP-BIBLIO", "Acceso gratuito a la bibliografía del ramo."),
    (("arancel", "beca", "pagar", "economic", "plata", "deuda"), "AP-ARANCEL", "Orientación sobre becas y pagos."),
    (("turno", "trabajo", "jefe", "horario"), "AP-HORARIO", "Ayuda para compatibilizar trabajo y estudio."),
    (("materia", "prueba", "ramo", "entend", "atrasad"), "AP-TUTORIA", "Tutoría en los ramos que le cuestan."),
    (("ansiedad", "agotad", "angustia", "dormir", "triste"), "AP-PSICO", "Apoyo psicológico confidencial."),
]
_POR_NECESIDAD: dict[str, str] = {"economica": "AP-ARANCEL", "academica": "AP-TUTORIA",
                                  "emocional": "AP-PSICO", "logistica": "AP-HORARIO"}


def _sugerencias_local(necesidad: str, resumen: str) -> list[dict[str, str]]:
    """Respaldo sin API: reglas por palabras clave, solo con ids del catálogo."""
    t = _normalizar(resumen)
    out = [{"id": i, "razon": r} for claves, i, r in _REGLAS_APOYO if any(k in t for k in claves)]
    if necesidad in _POR_NECESIDAD and all(x["id"] != _POR_NECESIDAD[necesidad] for x in out):
        out.append({"id": _POR_NECESIDAD[necesidad], "razon": "Corresponde a la necesidad detectada."})
    return _depurar_sugerencias(out) or [{"id": "AP-TUTORIA", "razon": "Primer espacio de acompañamiento."}]


def _estimacion_local(descripcion: str) -> dict[str, Any]:
    """Respaldo sin API: rangos típicos según el tipo de tarea."""
    t = _normalizar(descripcion)
    if "informe" in t or "ensayo" in t:
        rango, pasos = (6, 10), ["Leer enunciado y rúbrica", "Buscar y leer fuentes", "Ordenar ideas en un esquema",
                                 "Escribir borrador", "Revisar y corregir"]
    elif "presentacion" in t or "exposicion" in t:
        rango, pasos = (4, 7), ["Leer enunciado", "Preparar contenido", "Armar diapositivas", "Ensayar"]
    elif "prueba" in t or "estudiar" in t or "examen" in t:
        rango, pasos = (5, 9), ["Ordenar la materia", "Repasar apuntes", "Hacer ejercicios de práctica",
                                "Repasar errores"]
    else:
        rango, pasos = (3, 6), ["Leer enunciado", "Resolver la primera parte", "Resolver el resto", "Revisar"]
    h = round(sum(rango) / 2 / len(pasos), 1)
    return {"horas_min": rango[0], "horas_max": rango[1],
            "subtareas": [{"nombre": p, "horas": h} for p in pasos],
            "supuestos": ["Estimación genérica sin API; ajústala a tu ritmo."]}
