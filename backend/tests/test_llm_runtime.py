"""Tests de la configuración del LLM en caliente (llm_runtime)."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wispertext import llm_runtime


def _settings_con_dir(tmp: Path) -> SimpleNamespace:
    """Settings falso con models_dir apuntando al tmp y env de ejemplo."""
    return SimpleNamespace(
        models_dir=tmp,
        bonsai_base_url="http://env-default:4687/v1",
        bonsai_model="ternary-bonsai-8b",
        bonsai_enabled=True,
    )


def _con_tmp(fn):
    d = Path(tempfile.mkdtemp(prefix="wt_llm_cfg_"))
    settings = _settings_con_dir(d)
    with patch.object(llm_runtime, "get_settings", return_value=settings):
        llm_runtime._cache_mtime = None
        llm_runtime._cache_path = None
        fn(d)
    llm_runtime._cache_mtime = None
    llm_runtime._cache_path = None


def test_sin_archivo_usa_env():
    def caso(d: Path):
        cfg = llm_runtime.get_llm_config()
        assert cfg["source"] == "env"
        assert cfg["base_url"] == "http://env-default:4687/v1"
        assert cfg["model"] == "ternary-bonsai-8b"
        assert cfg["enabled"] is True
    _con_tmp(caso)


def test_save_crea_override_visible_en_caliente():
    def caso(d: Path):
        cfg = llm_runtime.save_llm_config(
            base_url="http://ollama:11434/v1/", model="qwen3:8b", enabled=True
        )
        assert cfg["source"] == "archivo"
        assert cfg["base_url"] == "http://ollama:11434/v1"  # sin barra final
        assert cfg["model"] == "qwen3:8b"
        # El archivo quedó escrito y la siguiente lectura lo ve
        data = json.loads((d / "llm_settings.json").read_text(encoding="utf-8"))
        assert data["model"] == "qwen3:8b"
        assert llm_runtime.get_llm_config()["model"] == "qwen3:8b"
    _con_tmp(caso)


def test_put_parcial_conserva_lo_actual():
    def caso(d: Path):
        llm_runtime.save_llm_config("http://a:1/v1", "m1", True)
        # solo cambia el modelo
        cfg = llm_runtime.save_llm_config(model="m2")
        assert cfg["base_url"] == "http://a:1/v1"
        assert cfg["model"] == "m2"
        assert cfg["enabled"] is True
    _con_tmp(caso)


def test_base_url_invalida_rechazada():
    def caso(d: Path):
        try:
            llm_runtime.save_llm_config(base_url="vllm:8000")
        except llm_runtime.LLMConfigError as exc:
            assert "http" in str(exc)
        else:
            raise AssertionError("debía rechazar esquema no http(s)")
        # modelo vacío también
        try:
            llm_runtime.save_llm_config(model="   ")
        except llm_runtime.LLMConfigError:
            pass
        else:
            raise AssertionError("debía rechazar modelo vacío")
        # y no quedó archivo
        assert not (d / "llm_settings.json").exists()
    _con_tmp(caso)


def test_archivo_corrupto_cae_a_env():
    def caso(d: Path):
        (d / "llm_settings.json").write_text("{no json", encoding="utf-8")
        llm_runtime._cache_mtime = None
        llm_runtime._cache_path = None
        cfg = llm_runtime.get_llm_config()
        assert cfg["source"] == "env"
        assert cfg["base_url"] == "http://env-default:4687/v1"
    _con_tmp(caso)


def test_reset_vuelve_al_env():
    def caso(d: Path):
        llm_runtime.save_llm_config("http://a:1/v1", "m1", False)
        cfg = llm_runtime.reset_llm_config()
        assert cfg["source"] == "env"
        assert cfg["model"] == "ternary-bonsai-8b"
        assert cfg["enabled"] is True
        assert not (d / "llm_settings.json").exists()
    _con_tmp(caso)


def test_enabled_false_apaga():
    def caso(d: Path):
        cfg = llm_runtime.save_llm_config("http://a:1/v1", "m1", enabled=False)
        assert cfg["enabled"] is False
    _con_tmp(caso)
