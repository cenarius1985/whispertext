"""Tests del plan de decisión del watchdog (sin BD)."""

from wispertext.worker.watchdog import MAX_FALLOS, STALE_MIN, _plan


def test_doc_sano_no_se_toca():
    assert _plan("synthesizing", "running", stale(2), 0, 500) is None
    assert _plan("synthesizing", "queued", stale(3), 0, 500) is None
    assert _plan("ready", "done", stale(999), 0, 0) is None
    assert _plan("error", "error", stale(999), 9, 0) is None


def test_job_error_se_reanuda():
    # el caso real: arq canceló por timeout (job error), quedan párrafos
    assert _plan("synthesizing", "error", stale(1), 0, 1014) == "reanudar"
    assert _plan("synthesizing", "error", stale(1), MAX_FALLOS - 1, 5) == "reanudar"


def test_job_running_congelado_se_reanuda():
    # CPU colgada/OOM: el job dice running pero lleva 47 min sin avanzar
    assert _plan("synthesizing", "running", stale(47), 0, 500) == "reanudar"
    assert _plan("synthesizing", "queued", stale(47), 0, 500) == "reanudar"  # redis perdió la cola


def test_sintesis_completa_se_cierra_como_ready():
    assert _plan("synthesizing", "error", stale(10), 0, 0) == "ready"


def test_extracting_o_cleaning_muerto_a_error():
    # sin párrafos no hay nada que reanudar: error visible para re-subir
    assert _plan("extracting", "error", stale(10), 0, 0) == "error"
    assert _plan("cleaning", None, stale(999), 0, 0) == "error"


def test_fallos_agotados_no_reintenta():
    assert _plan("synthesizing", "error", stale(10), MAX_FALLOS, 500) == "error"
    # las cancelaciones por timeout no cuentan como fallo: quien llama pasa
    # fallos_reales excluyéndolas, y con menos de MAX_FALLOS sí reanuda
    assert _plan("synthesizing", "error", stale(10), MAX_FALLOS - 1, 500) == "reanudar"


def test_sin_job_ninguno_es_huerfano():
    assert _plan("synthesizing", None, stale(999), 0, 10) == "reanudar"


def test_en_arranque_running_reciente_es_huerfano():
    # crash del worker: el job quedó 'running' con updated_at hace 1 min,
    # pero al arrancar nadie lo está ejecutando → reanudar ya
    assert _plan("synthesizing", "running", stale(1), 0, 500, arranque=True) == "reanudar"
    # los 'queued' pueden seguir vivos en Redis: no tocarlos en el arranque
    assert _plan("synthesizing", "queued", stale(1), 0, 500, arranque=True) is None


def stale(minutos: float) -> float:
    return minutos


def test_constantes_sanas():
    # un párrafo tarda <60 s: el umbral stale debe dar margen amplio
    assert STALE_MIN >= 10
    assert MAX_FALLOS >= 1
