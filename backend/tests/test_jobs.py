"""Tests de orquestación sin BD: saneado del texto crudo al persistir."""

import uuid

from wispertext.models import Document
from wispertext.worker.extraction import RawBlock
from wispertext.worker.jobs import _build_paragraphs


def _doc() -> Document:
    return Document(
        id=uuid.uuid4(),
        titulo="t",
        archivo_original="x.pdf",
        idioma_origen="es",
        idioma_lectura="es",
    )


def test_build_paragraphs_sanitiza_bytes_invalidos():
    # bug 2026-10-11: párrafos 727/728 de una tesis traían '\x00'/'\x01' y el
    # INSERT en asyncpg reventaba, dejando el documento 'limpiando' 20 h
    bloques = [
        RawBlock(pagina=100, tipo="texto", texto="\x00"),
        RawBlock(pagina=101, tipo="texto", texto="\x01"),
        RawBlock(pagina=102, tipo="texto", texto="Metodolog´ıa de adquisici´on\x00"),
    ]
    # paginas centrales: fuera de la zona editorial no se consulta Bonsai
    paragraphs, pending_imgs = _build_paragraphs(_doc(), 1, bloques, 800)
    assert pending_imgs == []
    assert len(paragraphs) == 3
    for p in paragraphs:
        assert "\x00" not in p.texto_original
        assert "\x01" not in p.texto_original
    # la basura queda marcada skipped (normalizado vacío → junk)
    assert paragraphs[0].estado_audio == "skipped"
    assert paragraphs[1].estado_audio == "skipped"
    # el texto legible sobrevive y normaliza bien
    assert paragraphs[2].texto_normalizado.startswith("Metodología")
