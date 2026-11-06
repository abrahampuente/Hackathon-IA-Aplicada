"""Generación de datos sintéticos que imitan un export de VIVO Duoc.

Ningún dato corresponde a personas reales: nombres y correos son ficticios
(dominio @ejemplo.cl) y no se genera RUT.

Mecanismo (documentado también en data/README_datos.md):
- La deserción depende SOLO de la conducta real: nivel y caída de asistencia,
  notas bajo 4,0 y tendencia de notas. La jornada no entra en esa fórmula; la
  vespertina deserta más porque su asistencia cae más (trabajo).
- Sesgo inyectado: en mujer + vespertina el REGISTRO de asistencia tiene ruido
  extra (marcas de ausencia erróneas por llegar tarde), sin cambiar su
  asistencia real ni su deserción.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.modelo import nivel_de_riesgo

CARRERAS: dict[str, str] = {
    "Ingeniería en Informática": "INF",
    "Técnico en Enfermería": "ENF",
    "Contabilidad General": "CON",
    "Administración de Empresas": "ADM",
}
SEDES: dict[str, str] = {"Sede Norte": "N", "Sede Sur": "S"}

COLUMNAS_ESTUDIANTES: list[str] = [
    "id_seudonimo", "nombre_ficticio", "correo_ficticio", "carrera", "seccion",
    "jornada", "sede", "genero", "trabaja",
    *config.COLS_ASISTENCIA, *config.COLS_NOTAS, "checkin_texto", "deserto",
]
COLUMNAS_OBLIGATORIAS: list[str] = [c for c in COLUMNAS_ESTUDIANTES if c != "checkin_texto"]
COLUMNAS_DEMO: list[str] = [
    *COLUMNAS_ESTUDIANTES, "nivel_esperado", "nivel_ingenuo", "caso_sesgo", "nota_demo",
]
DISTRIBUCION_DEMO: dict[str, int] = {"bajo": 3, "medio": 4, "alto": 5}
TASA_OBJETIVO: float = 0.25

# Parámetros del ruido de registro de asistencia (puntos porcentuales).
RUIDO_BASE_SD: float = 2.5
PROB_MARCA_ERRONEA: float = 0.30         # solo mujer + vespertina, por semana
MARCA_ERRONEA_RANGO: tuple[float, float] = (12.0, 28.0)

_NOMBRES = {
    "F": ["Camila", "Valentina", "Javiera", "Fernanda", "Catalina", "Constanza", "Daniela",
          "Francisca", "Antonia", "Sofía", "Paula", "Carolina", "Macarena", "Isidora", "Josefa"],
    "M": ["Matías", "Benjamín", "Sebastián", "Felipe", "Diego", "Nicolás", "Tomás", "Joaquín",
          "Vicente", "Cristóbal", "Ignacio", "Martín", "Gabriel", "Lucas", "Bastián"],
    "otro": ["Alex", "Dani", "Cris", "Sam", "Ariel", "Noa", "Robin", "Fran"],
}
_APELLIDOS = ["González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva",
              "Martínez", "Sepúlveda", "Morales", "Rodríguez", "López", "Fuentes", "Hernández",
              "Torres", "Araya", "Flores", "Espinoza", "Valenzuela", "Castillo", "Tapia",
              "Reyes", "Gutiérrez", "Castro", "Pizarro", "Álvarez", "Vásquez", "Sánchez", "Fernández"]

_CHECKIN: dict[str, list[str]] = {
    "laboral": [
        "Me cambiaron el turno en la pega y estoy llegando tarde a casi todas las clases.",
        "Salgo del trabajo a las 18:30 y no alcanzo a llegar a la primera hora.",
        "Esta semana hice horas extra y no pude conectarme a la clase online.",
        "En el trabajo me pidieron cubrir fines de semana, así que no estoy pudiendo estudiar.",
        "Trabajo en retail y con las ofertas del mes no he tenido tiempo para nada.",
        "Mi jefe no me da permiso para salir antes los días de prueba.",
        "Estoy trabajando de noche y me cuesta mucho concentrarme en clases.",
    ],
    "academico": [
        "No entendí nada de la última materia de matemática y me da vergüenza preguntar.",
        "Me fue mal en la primera prueba y siento que voy atrasado con los contenidos.",
        "No sé cómo usar bien la plataforma para entregar los trabajos.",
        "El ramo de especialidad tiene mucha materia y no sé por dónde partir.",
        "Me gustaría tener tutorías, sobre todo para comunicación.",
        "Siento que el ritmo es muy rápido comparado con el liceo.",
        "No me quedó claro cómo se calcula la nota final del ramo.",
    ],
    "personal": [
        "Estoy cuidando a mi mamá que está enferma y se me ha hecho difícil venir.",
        "Me cambié de casa y ahora el viaje es de casi dos horas.",
        "Tengo un hijo pequeño y cuando se enferma no tengo con quién dejarlo.",
        "Han pasado cosas en mi familia y me cuesta enfocarme.",
        "Estoy con problemas para dormir y llego muy cansado a clases.",
    ],
    "economico": [
        "Estoy viendo si me alcanza para seguir pagando el pasaje todos los días.",
        "No me salió la beca que esperaba y estoy preocupado por el arancel.",
        "Tuve que comprar materiales y me quedé corto de plata este mes.",
        "Estoy buscando un segundo trabajo porque no me alcanza.",
    ],
    "bienestar": [
        "Me siento muy agotado, entre el trabajo y el estudio no doy más.",
        "Últimamente ando con mucha ansiedad antes de las pruebas.",
        "No sé si esta carrera es lo mío, lo estoy pensando seriamente.",
        "Estoy pensando en congelar el semestre, no sé si puedo seguir así.",
    ],
    "sin_alerta": [
        "Todo bien por ahora, me gusta la carrera.",
        "Voy bien, aunque matemática me cuesta un poco.",
        "Contento con los profes, se explican bien.",
        "Me organicé mejor con un horario y me está resultando.",
        "Me uní a un grupo de estudio con compañeros del curso.",
    ],
}
_APERTURAS = ["", "", "Hola, ", "Profe, ", "Bueno, ", "Les cuento que "]
_CIERRES = ["", "", "", " Gracias.", " Igual voy a intentar ponerme al día.",
            " ¿Hay tutorías los sábados?", " Ojalá se pueda hacer algo."]


@dataclass
class Dataset:
    """Dataset generado: export visible + variables latentes solo para verificación."""

    estudiantes: pd.DataFrame
    latentes: pd.DataFrame  # id, asistencia real, ruido de registro, prob. real e ingenua
    intercepto: float


def _sin_tildes(texto: str) -> str:
    """Quita tildes y ñ para construir correos ficticios."""
    norm = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in norm if not unicodedata.combining(c))


def _prob_desercion(asistencia: np.ndarray, notas_p1: np.ndarray, notas_p2: np.ndarray,
                    intercepto: float) -> np.ndarray:
    """Probabilidad de deserción a partir de la conducta (sin variables demográficas).

    asistencia: (n, semanas) en %; notas_p1/notas_p2: (n, ramos) en escala 1-7.
    """
    asist_prom = asistencia.mean(axis=1)
    tendencia = asistencia[:, -3:].mean(axis=1) - asistencia[:, :3].mean(axis=1)
    notas = np.concatenate([notas_p1, notas_p2], axis=1)
    rojas = (notas < 4.0).sum(axis=1)
    nota_prom = notas.mean(axis=1)
    tend_notas = notas_p2.mean(axis=1) - notas_p1.mean(axis=1)
    logit = (intercepto
             + 0.09 * (80.0 - asist_prom)
             + 0.05 * (-tendencia)
             + 0.40 * rojas
             + 0.90 * (4.5 - nota_prom)
             + 0.80 * (-tend_notas))
    return 1.0 / (1.0 + np.exp(-logit))


def _calibrar_intercepto(asistencia: np.ndarray, p1: np.ndarray, p2: np.ndarray,
                         tasa: float = TASA_OBJETIVO) -> float:
    """Busca (bisección) el intercepto que da una probabilidad media igual a `tasa`."""
    lo, hi = -15.0, 15.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _prob_desercion(asistencia, p1, p2, mid).mean() > tasa:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _checkin(rng: np.random.Generator, vesp_trabaja: bool, prob: float) -> str:
    """Texto libre de check-in, con categoría coherente con la situación del estudiante."""
    cats = list(_CHECKIN)
    pesos = np.array([1.0, 1.2, 0.8, 0.6, 0.5, 2.0])  # orden de `cats`
    if vesp_trabaja:
        pesos[0] += 2.0
    pesos[1:5] *= 1.0 + 3.0 * prob   # más probabilidad de dificultades si el riesgo real es alto
    pesos[5] *= 1.0 - 0.8 * prob
    cat = cats[rng.choice(len(cats), p=pesos / pesos.sum())]
    frase = _CHECKIN[cat][rng.integers(len(_CHECKIN[cat]))]
    apertura = _APERTURAS[rng.integers(len(_APERTURAS))]
    if apertura:
        frase = frase[0].lower() + frase[1:]
    return apertura + frase + _CIERRES[rng.integers(len(_CIERRES))]


def generar_dataset(n: int = config.N_ESTUDIANTES, semilla: int = config.SEMILLA) -> Dataset:
    """Genera `n` estudiantes de primer año con conducta, deserción y sesgo de registro.

    Reproducible: misma semilla -> mismo resultado exacto.
    """
    rng = np.random.default_rng(semilla)
    sem = config.N_SEMANAS

    genero = rng.choice(["F", "M", "otro"], size=n, p=[0.48, 0.48, 0.04])
    jornada = rng.choice(["diurna", "vespertina"], size=n, p=[0.58, 0.42])
    sede = rng.choice(list(SEDES), size=n, p=[0.55, 0.45])
    carrera = rng.choice(list(CARRERAS), size=n)
    vesp = jornada == "vespertina"
    trabaja_b = rng.random(n) < np.where(vesp, 0.78, 0.22)

    # --- Asistencia REAL ---------------------------------------------------
    compromiso = rng.normal(0, 1, n)
    base = np.clip(86 + 7 * compromiso + rng.normal(0, 3, n), 45, 100)
    caida = (rng.gamma(1.2, 0.9, n)
             + np.where(vesp & trabaja_b, 1.6, 0.0)
             + np.where(~vesp & trabaja_b, 0.5, 0.0)
             + np.where(vesp & ~trabaja_b, 0.6, 0.0))
    con_shock = rng.random(n) < (0.10 + 0.12 * trabaja_b)
    semana_shock = rng.integers(3, sem, n)            # índice 0-based de la semana del quiebre
    magnitud_shock = rng.uniform(15, 40, n) * con_shock
    semanas = np.arange(sem)
    real = (base[:, None] - caida[:, None] * semanas[None, :]
            - magnitud_shock[:, None] * (semanas[None, :] >= semana_shock[:, None])
            + rng.normal(0, 2, (n, sem)))
    real = np.clip(real, 0, 100)

    # --- Asistencia REGISTRADA (con sesgo inyectado) -----------------------
    subgrupo = (genero == "F") & vesp
    ruido = rng.normal(0, RUIDO_BASE_SD, (n, sem))
    marcas = (rng.random((n, sem)) < PROB_MARCA_ERRONEA) & subgrupo[:, None]
    ruido -= marcas * rng.uniform(*MARCA_ERRONEA_RANGO, (n, sem))
    registrada = np.round(np.clip(real + ruido, 0, 100), 1)
    ruido_efectivo = registrada - real

    # --- Notas (no sesgadas) -------------------------------------------------
    tendencia_real = real[:, -3:].mean(axis=1) - real[:, :3].mean(axis=1)
    habilidad = 4.5 + 0.55 * compromiso[:, None] + rng.normal(0, 0.45, (n, len(config.RAMOS)))
    p1 = np.round(np.clip(habilidad + rng.normal(0, 0.35, habilidad.shape), 1.0, 7.0), 1)
    delta = 0.012 * tendencia_real[:, None] + rng.normal(0, 0.35, habilidad.shape)
    p2 = np.round(np.clip(p1 + delta, 1.0, 7.0), 1)

    # --- Deserción: depende solo de conducta REAL ---------------------------
    intercepto = _calibrar_intercepto(real, p1, p2)
    prob_real = _prob_desercion(real, p1, p2, intercepto)
    prob_ingenua = _prob_desercion(registrada, p1, p2, intercepto)  # lo que vería un modelo sobre el registro
    deserto = (rng.random(n) < prob_real).astype(int)

    # --- Identidad ficticia y check-ins -------------------------------------
    ids = [f"EST-{i:04d}" for i in range(1, n + 1)]
    nombres, correos = [], []
    for i in range(n):
        nombre = _NOMBRES[genero[i]][rng.integers(len(_NOMBRES[genero[i]]))]
        ap1, ap2 = (_APELLIDOS[k] for k in rng.choice(len(_APELLIDOS), 2, replace=False))
        nombres.append(f"{nombre} {ap1} {ap2}")
        local = _sin_tildes(f"{nombre}.{ap1}").lower().replace(" ", "")
        correos.append(f"{local}{i + 1}@{config.DOMINIO_CORREO_FICTICIO}")
    con_checkin = rng.random(n) < 0.30
    checkins = [_checkin(rng, bool(vesp[i] and trabaja_b[i]), float(prob_real[i])) if con_checkin[i] else ""
                for i in range(n)]

    seccion = [f"{CARRERAS[c]}-{'V' if v else 'D'}{SEDES[s]}" for c, v, s in zip(carrera, vesp, sede)]
    est = pd.DataFrame({
        "id_seudonimo": ids, "nombre_ficticio": nombres, "correo_ficticio": correos,
        "carrera": carrera, "seccion": seccion, "jornada": jornada, "sede": sede,
        "genero": genero, "trabaja": np.where(trabaja_b, "sí", "no"),
    })
    for j, col in enumerate(config.COLS_ASISTENCIA):
        est[col] = registrada[:, j]
    for r, ramo in enumerate(config.RAMOS):
        est[f"nota_{ramo}_p1"] = p1[:, r]
        est[f"nota_{ramo}_p2"] = p2[:, r]
    est["checkin_texto"] = checkins
    est["deserto"] = deserto
    est = est[COLUMNAS_ESTUDIANTES]

    lat = pd.DataFrame({
        "id_seudonimo": ids,
        "subgrupo_sesgo": subgrupo,
        "asistencia_real_prom": real.mean(axis=1),
        "asistencia_registrada_prom": registrada.mean(axis=1),
        "ruido_sd": ruido_efectivo.std(axis=1),
        "con_shock": con_shock,
        "prob_real": prob_real,
        "prob_ingenua": prob_ingenua,
    })
    lat.attrs["ruido_efectivo"] = ruido_efectivo
    return Dataset(estudiantes=est, latentes=lat, intercepto=intercepto)


# --------------------------------------------------------------------------
# Casos demo
# --------------------------------------------------------------------------
_ORDEN_NIVEL = {"bajo": 0, "medio": 1, "alto": 2}
_CENTRO_NIVEL = {"bajo": 0.15, "medio": 0.55, "alto": 0.85}


def _fmt(x: float) -> str:
    """Número con coma decimal (formato chileno)."""
    return f"{x:.1f}".replace(".", ",")


def _historia(fila: pd.Series, lat: pd.Series, nivel: str, sesgo: bool, nivel_ingenuo: str) -> str:
    """Historia breve del caso para el pitch, basada en sus datos."""
    a = [fila[c] for c in config.COLS_ASISTENCIA]
    notas = [fila[c] for c in config.COLS_NOTAS]
    rojas = sum(n < 4.0 for n in notas)
    perfil = f"{fila['jornada'].capitalize()}, {'trabaja' if fila['trabaja'] == 'sí' else 'no trabaja'}"
    if sesgo:
        notas_txt = "sus notas se sostienen" if rojas == 0 else f"tiene {rojas} nota(s) bajo 4,0"
        return (f"{perfil}. Su registro muestra asistencia de {_fmt(lat['asistencia_registrada_prom'])}% "
                f"por marcas de ausencia erróneas al llegar tarde, pero su asistencia real ronda "
                f"{_fmt(lat['asistencia_real_prom'])}% y {notas_txt}. Un modelo ingenuo la "
                f"marcaría en nivel {nivel_ingenuo}; su riesgo real es {nivel}"
                f"{' y no desertó' if fila['deserto'] == 0 else ''}. Caso para mostrar la auditoría de sesgo.")
    tramo = f"asistencia de {_fmt(a[0])}% (s1) a {_fmt(a[-1])}% (s8)"
    notas_txt = f"{rojas} nota(s) bajo 4,0" if rojas else "sin notas rojas"
    if nivel == "bajo":
        motivo = "sin señales fuertes en conjunto; no requiere acción individual"
    elif nivel == "medio":
        motivo = "señales tempranas; recibe invitación automática a acompañamiento"
    else:
        motivo = "caída marcada; un tutor revisa el caso y decide"
    shock = " Quiebre brusco a mitad de semestre." if lat["con_shock"] else ""
    checkin = " Dejó un check-in." if isinstance(fila["checkin_texto"], str) and fila["checkin_texto"] else ""
    return f"{perfil}. {tramo.capitalize()}, {notas_txt}.{shock}{checkin} Nivel {nivel}: {motivo}."


def seleccionar_demo(ds: Dataset) -> pd.DataFrame:
    """Elige 12 casos curados (3 bajo, 4 medio, 5 alto) incluyendo un caso del subgrupo sesgado.

    El nivel esperado sale de la probabilidad REAL; el ingenuo, de aplicar la misma
    fórmula a la asistencia REGISTRADA (lo que vería un modelo sin auditoría).
    """
    est, lat = ds.estudiantes, ds.latentes
    df = est.merge(lat, on="id_seudonimo")
    df["nivel_esperado"] = [nivel_de_riesgo(p * 100) for p in df["prob_real"]]
    df["nivel_ingenuo"] = [nivel_de_riesgo(p * 100) for p in df["prob_ingenua"]]

    sobreestimados = df[df["subgrupo_sesgo"]
                        & (df["nivel_ingenuo"].map(_ORDEN_NIVEL) > df["nivel_esperado"].map(_ORDEN_NIVEL))]
    if sobreestimados.empty:
        raise ValueError("No hay casos del subgrupo sesgado que un modelo ingenuo marque mal.")
    if (sobreestimados["deserto"] == 0).any():  # historia más clara: el ingenuo alerta y no desertó
        sobreestimados = sobreestimados[sobreestimados["deserto"] == 0]
    sesgo_id = (sobreestimados["prob_ingenua"] - sobreestimados["prob_real"]).idxmax()
    elegidos: list[int] = [sesgo_id]

    cuotas = dict(DISTRIBUCION_DEMO)
    cuotas[df.loc[sesgo_id, "nivel_esperado"]] -= 1
    vt = (df["jornada"] == "vespertina") & (df["trabaja"] == "sí")
    tiene_checkin = df["checkin_texto"].fillna("").str.len() > 0
    arquetipos = {
        "bajo": [~vt & (df["jornada"] == "diurna"), vt, tiene_checkin],
        "medio": [vt, ~vt, df["con_shock"], tiene_checkin],
        "alto": [vt & df["con_shock"], ~vt, vt, tiene_checkin, df["con_shock"]],
    }
    limpio = ~df["subgrupo_sesgo"]  # historias claras: sin ruido de registro
    for nivel, cuota in cuotas.items():
        pool = df[(df["nivel_esperado"] == nivel) & limpio]
        filtros = arquetipos[nivel]
        for k in range(cuota):
            filtro = filtros[k % len(filtros)]
            cand = pool[filtro.loc[pool.index] & ~pool.index.isin(elegidos)]
            if cand.empty:
                cand = pool[~pool.index.isin(elegidos)]
            if cand.empty:
                raise ValueError(f"No hay suficientes casos de nivel {nivel} para la demo.")
            elegidos.append((cand["prob_real"] - _CENTRO_NIVEL[nivel]).abs().idxmin())

    demo = df.loc[elegidos].copy()
    demo["caso_sesgo"] = demo.index == sesgo_id
    demo["nota_demo"] = [
        _historia(f, f, f["nivel_esperado"], bool(f["caso_sesgo"]), f["nivel_ingenuo"])
        for _, f in demo.iterrows()
    ]
    demo = demo.sort_values(["nivel_esperado", "id_seudonimo"],
                            key=lambda s: s.map(_ORDEN_NIVEL) if s.name == "nivel_esperado" else s)
    return demo[COLUMNAS_DEMO].reset_index(drop=True)


# --------------------------------------------------------------------------
# Documentación y persistencia
# --------------------------------------------------------------------------
def readme_datos(ds: Dataset) -> str:
    """Documento Markdown que describe el dataset y el sesgo inyectado, con cifras reales."""
    est, lat = ds.estudiantes, ds.latentes
    ruido = lat.attrs["ruido_efectivo"]
    sub = lat["subgrupo_sesgo"].to_numpy()
    sd_sub, sd_resto = ruido[sub].std(), ruido[~sub].std()
    tasa = est["deserto"].mean()
    por_jornada = est.groupby("jornada")["deserto"].mean()
    return f"""# Dataset sintético tipo export VIVO

Generado por `src/generar_datos.py` con semilla {config.SEMILLA}. **Ningún dato es real**:
nombres y correos son ficticios (dominio `@{config.DOMINIO_CORREO_FICTICIO}`) y no hay RUT.

## Archivos
- `estudiantes.csv`: {len(est)} estudiantes de primer año.
- `estudiantes_demo.csv`: 12 casos curados para el pitch (3 bajo, 4 medio, 5 alto), con `nota_demo`.

## Columnas de `estudiantes.csv`
| Columna | Descripción |
|---|---|
| `id_seudonimo` | EST-0001 … EST-{len(est):04d} |
| `nombre_ficticio`, `correo_ficticio` | Identidad inventada. Nunca se envía a Claude ni entra al modelo |
| `carrera`, `seccion`, `jornada`, `sede`, `genero`, `trabaja` | Solo para auditoría y agregación (prohibidas como entrada del modelo) |
| `asistencia_s1` … `asistencia_s{config.N_SEMANAS}` | % de asistencia **registrada** por semana |
| `nota_<ramo>_p1`, `nota_<ramo>_p2` | Parciales 1 y 2 en {", ".join(config.RAMOS)} (escala 1,0 a 7,0) |
| `checkin_texto` | Texto libre opcional (~30%) |
| `deserto` | 1 si desertó |

## Cómo se genera la deserción
La probabilidad de desertar depende **solo de la conducta real**: asistencia promedio,
caída de asistencia (últimas 3 vs primeras 3 semanas), cantidad de notas bajo 4,0, promedio
de notas y caída entre parciales. El intercepto se calibra para una tasa esperada de 25%.

Jornada, género, sede y trabajo **no** entran en esa fórmula. La vespertina deserta más
({_fmt(por_jornada.get('vespertina', 0) * 100)}% vs {_fmt(por_jornada.get('diurna', 0) * 100)}% diurna)
porque su asistencia real cae más: la mayoría trabaja y sufre más quiebres de horario.

Tasa global observada: **{_fmt(tasa * 100)}%**.

## Sesgo inyectado (a propósito)
En el subgrupo **mujer + vespertina**, el **registro** de asistencia tiene ruido extra: cada semana,
con probabilidad {int(PROB_MARCA_ERRONEA * 100)}%, se marca una ausencia errónea que resta entre
{int(MARCA_ERRONEA_RANGO[0])} y {int(MARCA_ERRONEA_RANGO[1])} puntos. Simula marcas mal puestas a quien llega
tarde por trabajo o cuidado. Su **asistencia real y su deserción no cambian**.

- Desviación estándar del ruido de registro en mujer + vespertina: **{_fmt(sd_sub)} pp**
- En el resto: **{_fmt(sd_resto)} pp** (razón {_fmt(sd_sub / sd_resto)}x)

Consecuencia esperada: un modelo entrenado sobre la asistencia registrada sobrestimará el riesgo
de este subgrupo (más falsos positivos). La auditoría del ciclo de sesgos debe detectarlo.
`estudiantes_demo.csv` incluye un caso de este subgrupo marcado con `caso_sesgo = True`.
"""


def guardar_csv(df: pd.DataFrame, ruta: Path) -> Path:
    """Escribe `df` como CSV UTF-8 (formato tipo export VIVO) y devuelve la ruta."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8", lineterminator="\n")
    return ruta


def generar_todo(semilla: int = config.SEMILLA, destino: Path = config.DATA_DIR) -> Dataset:
    """Genera y guarda estudiantes.csv, estudiantes_demo.csv y README_datos.md en `destino`."""
    ds = generar_dataset(semilla=semilla)
    guardar_csv(ds.estudiantes, destino / config.RUTA_ESTUDIANTES.name)
    guardar_csv(seleccionar_demo(ds), destino / config.RUTA_DEMO.name)
    (destino / config.RUTA_README_DATOS.name).write_text(readme_datos(ds), encoding="utf-8", newline="\n")
    return ds
