# Alerta temprana y acompañamiento – Primer año Duoc UC

Hackathon de IA Aplicada · Congreso Social UC 2026 · Desafío 2: deserción en educación superior.

Este sistema estima el riesgo de deserción de estudiantes de primer año, con foco en los vespertinos que trabajan, y organiza el acompañamiento según ese riesgo. Todos los datos son **sintéticos** y ningún mensaje se envía de verdad.

## Flujo

```
 ┌──────────────────────┐
 │ generar_datos.py     │  export simulado de VIVO (perfil + asistencia/notas semanales)
 └──────────┬───────────┘
            │  solo conducta académica
            ▼
 ┌──────────────────────┐      género, sede, jornada, trabajo, origen
 │ modelo.py            │ ───► auditoria.py (solo auditar sesgos, nunca entrada)
 │ % riesgo + 3 razones │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │ nivel (config.py)    │  bajo <40%  ·  medio 40–70%  ·  alto >70%
 └───┬──────────┬───────┘
     │ bajo     │ medio / alto
     ▼          ▼
  sin acción  ┌──────────────────────┐
  individual  │ seudonimizar.py      │  nada identificable sale del sistema
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │ claude_client.py     │  explica riesgo · redacta invitación ·
              │ (prompts/*.txt)      │  clasifica check-ins · resume sección
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │ app.py: panel tutor  │  alto: un tutor revisa y DECIDE
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │ bandeja simulada     │  medio: invitación automática (data/bandeja_simulada.jsonl)
              └──────────────────────┘
```

## Estructura

| Ruta | Rol |
|---|---|
| `src/config.py` | Umbrales, rutas, variables permitidas/prohibidas, `ANTHROPIC_MODEL`, `OFFLINE` |
| `src/generar_datos.py` | Datos sintéticos tipo VIVO |
| `src/modelo.py` | Modelo interpretable, nivel de riesgo y 3 razones |
| `src/auditoria.py` | Métricas por grupo demográfico |
| `src/seudonimizar.py` | Seudónimos y filtro de datos personales antes de llamar a Claude |
| `src/claude_client.py` | Llamadas a Claude: explicar al tutor, invitación, check-ins, resumen por sección, sugerir apoyos y estimar horas (con caché offline, log y tope de 200 llamadas) |
| `src/generar_cache.py` | Ejecuta los usos de Claude sobre los 12 casos demo y guarda `data/cache_claude.json` |
| `src/apoyos.py` | Catálogo de apoyos de ejemplo y flujo propuesta → tutor → consentimiento |
| `src/plan_estudio.py` | Planificador determinista de bloques de estudio (sin Claude) |
| `prompts/` | Plantillas de los prompts |
| `app.py` | Panel Streamlit |
| `run_demo.py` | Pipeline completo con un solo comando |
| `verify/` | `cicloN.py` por ciclo + `run_all.py` |
| `data/` | Archivos generados (excluidos de git) |

## Uso

```bash
pip install -r requirements.txt
copy .env.example .env        # y completa ANTHROPIC_API_KEY
python run_demo.py
streamlit run app.py
python verify/run_all.py
```

Con `OFFLINE=1` en `.env`, el sistema no llama a la API.
