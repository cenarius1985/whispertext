"""Tests de preparación de habla (RF-14): siglas, refs, URLs."""

from wispertext.worker.speakable import expand_siglas, prepare_speech


def test_siglas_conocidas():
    assert "Organización Mundial de la Salud" in expand_siglas("según la OMS y la OPS")
    assert expand_siglas("norma ISO 9001") == "norma I S O 9001"


def test_sigla_corta_desconocida_se_deletrea():
    assert expand_siglas("registro ABC completo") == "registro A B C completo"


def test_palabra_normal_no_se_toca():
    assert expand_siglas("para y casa") == "para y casa"


def test_refs_y_urls_fuera():
    out = prepare_speech("El método propuesto [12] se validó en https://ejemplo.cl/x y funcionó")
    assert "[12]" not in out
    assert "https" not in out
    assert "El método propuesto se validó en" in out


def test_puntuacion_repetida():
    assert prepare_speech("¡¡atención!! llegó...") .startswith("¡atención! llegó")


def test_t2_hablado():
    assert "T dos estrella" in prepare_speech("con T2∗ corto")
    assert prepare_speech("el T2 y el T1") == "el T dos y el T uno"


def test_operadores_matematicos():
    assert "por" in prepare_speech("matriz 256 × 256")
    assert "menos" in prepare_speech("del orden de 10 −14")
    # los rangos ASCII NO se tocan
    assert "menos" not in prepare_speech("entre 1990-1995 hubo cambios")


def test_simbolos_griegos_y_math():
    out = prepare_speech("σ ≈ 3 ± 0,5 en 400 µs a 3 T")
    assert "sigma" in out and "aproximadamente" in out and "más menos" in out
    assert "microsegundos" in out


def test_ruido_tipografico_fuera():
    out = prepare_speech("✓ item • nota | tabla [14")
    assert not any(c in out for c in "✓•|[]")


def test_t2_estrella_no_duplica():
    assert prepare_speech("T2∗ corto") == "T dos estrella corto"
