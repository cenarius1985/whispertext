"""Tests del filtro editorial determinista (RF-04)."""

from wispertext.worker.editorial import classify_editorial


def test_isbn():
    ok, reason = classify_editorial("ISBN 978-956-360-123-4\nPrimera edición")
    assert ok and reason == "isbn"


def test_copyright():
    ok, _ = classify_editorial("© Ministerio de Salud 2024. Derechos reservados.")
    assert ok


def test_deposito_legal():
    ok, _ = classify_editorial("Hecho el depósito que indica la ley 17.336")
    assert ok


def test_credito_de_autores():
    texto = "Por Ana María González\nDe Sebastián Rojas Valdivieso\n2016"
    ok, _ = classify_editorial(texto)
    assert ok


def test_contenido_normal_no_se_salta():
    texto = (
        "La vigilancia epidemiológica de las infecciones asociadas a la atención "
        "en salud requiere de un sistema de notificación oportuna y estandarizada "
        "que permita comparar resultados entre establecimientos."
    )
    ok, reason = classify_editorial(texto)
    assert not ok
    assert reason is None


def test_bloque_largo_no_se_salta_although_isbn():
    # >600 chars: casi nunca es puro editorial, no se salta por regla
    texto = "ISBN 123-4\n" + ("contenido técnico repetido. " * 60)
    ok, _ = classify_editorial(texto)
    assert not ok


def test_vacio():
    ok, reason = classify_editorial("   ")
    assert ok and reason == "vacio"
