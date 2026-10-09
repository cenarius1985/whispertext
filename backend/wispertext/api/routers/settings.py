"""Configuración del LLM en caliente — Ajustes de WISPER-TEXT.

GET/PUT sobre la config efectiva (override en archivo compartido + fallback
.env), catálogo de modelos del endpoint y prueba real de conexión. Pensado
para cambiar el modelo de ecuaciones/editorial sin rebuild ni reinicio.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wispertext import llm_runtime
from wispertext.config import get_settings

log = logging.getLogger("wispertext.settings")

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMConfigIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None


class LLMConfigOut(BaseModel):
    base_url: str
    model: str
    enabled: bool
    source: str  # "archivo" (override de Ajustes) | "env" (.env)
    env_default: dict[str, object]


def _out(cfg: dict) -> LLMConfigOut:
    s = get_settings()
    return LLMConfigOut(
        base_url=cfg["base_url"],
        model=cfg["model"],
        enabled=cfg["enabled"],
        source=cfg["source"],
        env_default={"base_url": s.bonsai_base_url, "model": s.bonsai_model},
    )


@router.get("/llm", response_model=LLMConfigOut)
async def get_llm():
    """Config efectiva del LLM + los defaults del .env (para «Restablecer»)."""
    return _out(llm_runtime.get_llm_config())


@router.put("/llm", response_model=LLMConfigOut)
async def put_llm(body: LLMConfigIn):
    """Guarda el override (parcial). Api y worker lo aplican al instante."""
    if body.base_url is None and body.model is None and body.enabled is None:
        raise HTTPException(400, "nada que guardar: indica base_url, model o enabled")
    try:
        cfg = llm_runtime.save_llm_config(
            base_url=body.base_url, model=body.model, enabled=body.enabled
        )
    except llm_runtime.LLMConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    log.info("LLM reconfigurado desde Ajustes: %s (modelo %s)",
             cfg["base_url"], cfg["model"])
    return _out(cfg)


@router.delete("/llm", response_model=LLMConfigOut)
async def reset_llm():
    """Borra el override: vuelve a la configuración del .env."""
    return _out(llm_runtime.reset_llm_config())


@router.get("/llm/models")
async def modelos_llm(base_url: str | None = None):
    """Catálogo del endpoint (GET {base}/models) para el selector."""
    try:
        return {"modelos": llm_runtime.listar_modelos(base_url)}
    except llm_runtime.LLMConfigError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/llm/verify")
async def verificar_llm(body: LLMConfigIn | None = None):
    """
    Prueba real: un chat completion mínimo. Con body, prueba ESA config sin
    guardarla (para validar antes de aplicar); sin body, la vigente.
    """
    cfg = llm_runtime.get_llm_config()
    base = (body.base_url if body and body.base_url else None) or None
    model = (body.model if body and body.model else None) or None
    if base is None and model is None:
        base, model = cfg["base_url"], cfg["model"]
    elif base or model:
        base = base or cfg["base_url"]
        model = model or cfg["model"]
    return llm_runtime.verificar(base_url=base, model=model)
