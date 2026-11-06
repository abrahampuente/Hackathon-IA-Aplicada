# Evidencia: envío real de correo (demo)

Prueba única de envío real autorizada por el equipo para la demo de la Hackathon IA Aplicada 2026.
Ningún otro mensaje del sistema sale de la bandeja simulada.

## Resumen

| Campo | Valor |
|---|---|
| Fecha y hora de salida (hora de Chile) | **06-11-2026, 13:58:54** (16:58:54 UTC) |
| Resultado | Aceptado por el servidor SMTP de Gmail (`ok = true`) |
| Tiempo de envío | 3,42 s (el límite es 10 s) |
| Destinatario | `a***@duocuc.cl`, la única dirección de la lista blanca (`CORREOS_PERMITIDOS`) |
| Servidor | `smtp.gmail.com:587` con STARTTLS |
| Caso | `EST-DEMO` (ficticio, nivel alto, 83% de riesgo estimado) |
| Asunto | Un espacio de apoyo para tu primer año |
| Pie | Mensaje de prueba del prototipo, Hackathon IA Aplicada 2026. |

## Flujo seguido

1. **Claude generó el mensaje en vivo**, sin caché: modelo `claude-haiku-5-5`, 6,68 s. El payload solo tenía `carrera` y `canal`, sin correo, nombre ni riesgo.
2. El mensaje quedó **PROGRAMADO**, con una ventana de 24 h para que el tutor lo revisara.
3. Al **avanzar el reloj simulado 24 h**, el programador lo entregó.
4. El correo de destino y el nombre se insertaron **localmente**, solo al momento de enviar.
5. El mensaje también quedó en la bandeja simulada del estudiante.

## Registro (`data/log_correo.jsonl`, con el destinatario enmascarado)

```json
{"ts": "2026-11-06T16:58:54+00:00", "resultado": "enviado", "ok": true, "motivo": "enviado",
 "hora": "2026-11-06T13:58:54", "segundos": 3.42, "destinatario": "a***@duocuc.cl"}
```

El log nunca guarda la clave SMTP ni el correo completo (`verify/ciclo_correo.py`, criterio C4).

## Texto enviado (antes de insertar el nombre)

```text
Hola {NOMBRE}:

Te escribimos para ofrecerte los espacios de acompañamiento estudiantil que tenemos para quienes
cursan primer año. Son voluntarios y sin costo, y sus horarios consideran a quienes trabajan.

Ahí puedes pedir tutorías de ramos, recibir apoyo para organizar tus tiempos o conversar con un
tutor sobre lo que necesites.

¿Por qué recibí esto? Acompañamos a estudiantes de primer año en Ingeniería en Informática.

Si quieres saber más, responde a este correo y te contaremos los horarios disponibles.

Si prefieres no recibir más mensajes, responde NO MÁS.

Equipo de Acompañamiento Estudiantil

--
Mensaje de prueba del prototipo, Hackathon IA Aplicada 2026.
```

## Pantallazo

<!-- Guarda la captura como docs/img/correo_enviado.png -->
![Correo recibido en la bandeja de entrada](img/correo_enviado.png)

> Antes de subir la captura, tapa la dirección completa de correo y cualquier dato personal que no sea necesario.

## Controles verificados

- Con `MODO_CORREO_REAL=0` no se abre ninguna conexión SMTP.
- Un destinatario fuera de la lista blanca se rechaza, aunque el modo real esté activo.
- Si el envío falla o tarda más de 10 s, el panel no se cae: el mensaje queda en la bandeja simulada, con aviso.
- La clave SMTP no aparece en ningún archivo del repositorio ni en los logs.
