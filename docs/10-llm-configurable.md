# LLM configurable en caliente — Ajustes

> Estado: ✅ implementado y verificado (2026-10-09)

El LLM de WISPERTEXT (ecuaciones LaTeX, clasificación editorial, traducción de
apoyo) es **fail-soft** y se configura por `.env`. Esta característica permite
**cambiarlo en caliente desde la página de Ajustes**: endpoint y modelo, sin
rebuild ni reinicio, para cualquier API OpenAI-compatible.

## Uso (Ajustes → "Modelo LLM")

1. **Selector de proveedor** (presets): Bonsai de este stack · Bonsai externo
   (:4687) · Ollama local (:11434) · LM Studio (:1234) · vLLM (:8000) ·
   **Personalizado** (URL libre). Elegir un preset lo aplica al instante y trae
   su catálogo.
2. **Modelo**: del catálogo del propio servidor (`GET /v1/models`) o escrito a
   mano si no lo expone.
3. **Probar conexión**: un chat completion real antes (o después) de guardar.
4. **On/Off**: modo determinista puro, sin llamadas externas.
5. **Restablecer**: vuelve a la configuración del `.env`.

## Cómo está implementado

```
Ajustes (frontend) ──PUT /api/settings/llm──► models/llm_settings.json
                                                    │ (volumen compartido)
                                    api y worker leen en cada llamada
                                                    │
                     fallback al .env si no existe archivo (o está corrupto)
```

- `wispertext/llm_runtime.py`: config efectiva con override en
  `models/llm_settings.json` (volumen que api y worker **ya comparten** → el
  cambio es visible al instante para ambos). Relección barata por (ruta, mtime).
- `worker/bonsai.py`: `base_url`/`model`/`enabled` salen de la config en
  caliente; los **timeouts** siguen en `.env` (son operativos).
- `api/routers/settings.py`: `GET/PUT/DELETE /api/settings/llm`,
  `GET /api/settings/llm/models` (catálogo del endpoint) y
  `POST /api/settings/llm/verify` (acepta config sin guardar, para validar
  antes de aplicar).

## Garantías

- **Fail-soft intacto**: sin override, con endpoint caído o `enabled=false`,
  el pipeline sigue en modo determinista (las ecuaciones se muestran como
  imagen y no se leen) — igual que siempre.
- La clave nunca sale: WISPERTEXT no tiene cuentas; si tu endpoint exige API
  key, inclúyela en la URL según el formato del servidor (p. ej.
  `https://host/v1?key=…`) — bajo tu responsabilidad.
- Tests: `tests/test_llm_runtime.py` (override, PUT parcial, esquema inválido,
  archivo corrupto → fallback, reset, enabled).

## API (resumen)

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/settings/llm` | config efectiva + fuente (`archivo`/`env`) + defaults del `.env` |
| PUT | `/api/settings/llm` | guarda override parcial `{base_url?, model?, enabled?}` |
| DELETE | `/api/settings/llm` | borra el override → vuelve al `.env` |
| GET | `/api/settings/llm/models?base_url=` | catálogo del endpoint |
| POST | `/api/settings/llm/verify` | prueba real; con body prueba ESA config sin guardarla |
