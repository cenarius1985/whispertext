"""Configuración del LLM en caliente (ecuaciones/editorial/traducción).

El LLM de WISPER-TEXT (Bonsai por defecto) es fail-soft y se configura por
env (BONSAI_BASE_URL / BONSAI_MODEL / BONSAI_ENABLED). Este módulo permite
CAMBIARLO en caliente desde Ajustes sin rebuild ni reinicio:

  · El override vive en ``models/llm_settings.json`` — un archivo del volumen
    que YA comparten api y worker (/data/models), así el cambio es visible
    para ambos al instante.
  · Sin archivo (o con archivo inválido) se usa el .env, como siempre.
  · La lectura es barata: solo re-stat/parsea el JSON si cambió su mtime.

Sirve para apuntar a cualquier endpoint OpenAI-compatible: el llama-server
del propio stack (perfil bonsai), Ollama con /v1, vLLM, LM Studio, o una
nube con clave en la URL si el usuario así lo decide — el contrato que
consume worker/bonsai.py es /chat/completions, igual que siempre.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from wispertext.config import get_settings

log = logging.getLogger("wispertext.llm_runtime")

_SETTINGS_FILE = "llm_settings.json"
_HTTP_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


def _archivo() -> Path:
    return get_settings().models_dir / _SETTINGS_FILE


# ── Lectura (con relección por mtime) ────────────────────────────────────────

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None
_cache_path: Path | None = None


def _normalizar(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def get_llm_config() -> dict[str, Any]:
    """
    Config efectiva del LLM: override de archivo si existe, si no el .env.

    Devuelve {base_url, model, enabled, source} con source = "archivo" | "env".
    Nunca lanza: un archivo corrupto se ignora con aviso (fail-soft). El stat
    del archivo es barato y se hace en cada llamada; el JSON solo se parsea
    cuando (ruta, mtime) cambian respecto a lo cacheado.
    """
    global _cache, _cache_mtime, _cache_path
    s = get_settings()

    archivo = _archivo()
    mtime: float | None = None
    if archivo.is_file():
        try:
            mtime = archivo.stat().st_mtime
        except OSError:
            mtime = None

    if archivo == _cache_path and mtime == _cache_mtime and _cache is not None:
        return dict(_cache)

    if mtime is None:
        _cache = {
            "base_url": _normalizar(s.bonsai_base_url),
            "model": s.bonsai_model,
            "enabled": s.bonsai_enabled,
            "source": "env",
        }
    else:
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            base = datos.get("base_url")
            _cache = {
                "base_url": _normalizar(base) if base else _normalizar(s.bonsai_base_url),
                "model": (datos.get("model") or s.bonsai_model).strip(),
                "enabled": bool(datos.get("enabled", s.bonsai_enabled)),
                "source": "archivo",
            }
        except Exception as exc:  # noqa: BLE001 — archivo corrupto → env
            log.warning("llm_settings.json ilegible (%s); se usa el .env", exc)
            _cache_mtime = None
            _cache_path = archivo
            _cache = {
                "base_url": _normalizar(s.bonsai_base_url),
                "model": s.bonsai_model,
                "enabled": s.bonsai_enabled,
                "source": "env",
            }
            return dict(_cache)

    _cache_path, _cache_mtime = archivo, mtime
    return dict(_cache)


# ── Escritura ───────────────────────────────────────────────────────────────


class LLMConfigError(ValueError):
    """Config rechazada por inválida (esquema, campos vacíos)."""


def save_llm_config(
    base_url: str | None = None,
    model: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """
    Guarda el override (PUT parcial: lo que no viene conserva lo actual).

    Al escribir el archivo, api y worker lo ven en su próxima llamada. Los
    timeouts (bonsai_*_timeout_s del .env) no se tocan: son operativos.
    """
    actual = get_llm_config()
    nuevo_base = _normalizar(base_url) if base_url else actual["base_url"]
    nuevo_model = (model or actual["model"]).strip()
    nuevo_enabled = actual["enabled"] if enabled is None else bool(enabled)

    if not _HTTP_SCHEME.match(nuevo_base):
        raise LLMConfigError(
            f"base_url debe empezar con http:// o https:// (recibido: {nuevo_base[:60]!r})"
        )
    if not nuevo_model:
        raise LLMConfigError("model no puede quedar vacío")

    datos = {"base_url": nuevo_base, "model": nuevo_model, "enabled": nuevo_enabled}
    archivo = _archivo()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    global _cache_mtime, _cache_path
    _cache_mtime, _cache_path = None, None  # fuerza relección inmediata
    log.info("LLM reconfigurado: %s · modelo %s · enabled=%s",
             nuevo_base, nuevo_model, nuevo_enabled)
    return get_llm_config()


def reset_llm_config() -> dict[str, Any]:
    """Borra el override: vuelve a mandar la configuración del .env."""
    archivo = _archivo()
    try:
        archivo.unlink()
    except FileNotFoundError:
        pass
    global _cache_mtime, _cache_path
    _cache_mtime, _cache_path = None, None
    return get_llm_config()


# ── Sondas para Ajustes (catálogo y prueba real) ────────────────────────────


def listar_modelos(base_url: str | None = None, timeout_s: float = 10.0) -> list[str]:
    """IDs del catálogo del endpoint (GET {base}/models). [] si no responde."""
    import httpx

    base = _normalizar(base_url) if base_url else get_llm_config()["base_url"]
    try:
        r = httpx.get(f"{base}/models", timeout=timeout_s)
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", []) if m.get("id")]
    except Exception as exc:  # noqa: BLE001 — sonda, no pipeline
        raise LLMConfigError(f"no se pudo listar modelos de {base}: {exc}") from exc


def verificar(
    base_url: str | None = None,
    model: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """
    Prueba real: un chat completion mínimo contra el endpoint.

    Devuelve {ok, model, respuesta, elapsed_ms, detail}. ok=False con detail
    accionable — es lo que muestra el botón «Probar» de Ajustes.
    """
    import httpx

    cfg = get_llm_config()
    base = _normalizar(base_url) if base_url else cfg["base_url"]
    modelo = model or cfg["model"]
    t0 = time.perf_counter()
    try:
        r = httpx.post(
            f"{base}/chat/completions",
            json={
                "model": modelo,
                "messages": [
                    {"role": "user", "content": "Responde únicamente: OK"}
                ],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=timeout_s,
        )
        elapsed = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return {
                "ok": False, "model": modelo, "respuesta": "",
                "elapsed_ms": elapsed,
                "detail": f"HTTP {r.status_code}: {r.text[:200]}",
            }
        texto = (r.json()["choices"][0]["message"]["content"] or "").strip()
        return {
            "ok": bool(texto), "model": r.json().get("model", modelo),
            "respuesta": texto[:120], "elapsed_ms": elapsed,
            "detail": "" if texto else "respondió 200 pero sin texto",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False, "model": modelo, "respuesta": "",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000),
            "detail": f"{type(exc).__name__}: {exc}",
        }
