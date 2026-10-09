"""Tests de los extractores multi-formato (PRD v2, RF-MF-03…07).

Cada test fabrica un archivo real en un directorio temporal y verifica los
bloques que produce el extractor: orden, tipos (texto/titulo/codigo/figura) y
metadatos. Compatibles con el runner simple (python tests/run_all.py, sin
fixtures de pytest).
"""

import io
import tempfile
import zipfile
from pathlib import Path

from wispertext.worker.extractors import (
    extract_any,
    extract_docx,
    extract_epub,
    extract_html,
    extract_text,
)


def _tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="wispertext_test_"))


# --------------------------------------------------------------------------- #
# TXT / MD
# --------------------------------------------------------------------------- #


def test_txt_parrafos_y_titulo_mayusculas():
    d = _tmpdir()
    f = d / "norma.txt"
    f.write_text(
        "RESOLUCION EXENTA NUMERO 1123\n\n"
        "Establece norma técnica administrativa.\n"
        "Con dos líneas que se unen.\n\n"
        "Segundo párrafo del cuerpo.\n",
        encoding="utf-8",
    )
    res = extract_text(str(f))
    tipos = [b.tipo for b in res.bloques]
    assert tipos == ["titulo", "texto", "texto"]
    assert "RESOLUCION" in res.bloques[0].texto
    assert "Establece" in res.bloques[1].texto
    assert res.titulo_documento == "RESOLUCION EXENTA NUMERO 1123"


def test_md_headings_codigo_y_tabla():
    d = _tmpdir()
    f = d / "doc.md"
    f.write_text(
        "# Norma principal\n\n"
        "Párrafo introductorio.\n\n"
        "## Sección 1\n\n"
        "Contenido de la sección.\n\n"
        "```python\nprint('hola')\nx = 1\n```\n\n"
        "| col a | col b |\n|-------|-------|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    res = extract_any(str(f))
    tipos = [b.tipo for b in res.bloques]
    assert tipos == ["titulo", "texto", "titulo", "texto", "codigo", "codigo"]
    assert res.titulo_documento == "Norma principal"
    assert "print" in res.bloques[4].texto
    assert "col a" in res.bloques[5].texto  # tabla markdown → no leída


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #


def test_html_solo_contenido_principal():
    d = _tmpdir()
    f = d / "pagina.html"
    f.write_text(
        """<html><head><title>Circular 45</title>
        <style>.x{color:red}</style></head>
        <body>
        <nav><a href="#">Inicio</a><a href="#">Normas</a></nav>
        <header>Ministerio — banner</header>
        <script>alert('x')</script>
        <main>
          <h1>Circular número 45</h1>
          <p>Se instruye lo siguiente a los establecimientos.</p>
          <ul><li>Punto uno de la circular.</li><li>Punto dos.</li></ul>
          <table><tr><th>Rol</th><th>Valor</th></tr><tr><td>A</td><td>3</td></tr></table>
        </main>
        <footer>© 2026 Gobierno</footer>
        </body></html>""",
        encoding="utf-8",
    )
    res = extract_html(str(f))
    textos = "\n".join(b.texto for b in res.bloques)
    assert res.titulo_documento == "Circular 45"
    # el mobiliario NO se lee
    assert "Inicio" not in textos and "banner" not in textos
    assert "alert" not in textos and "2026 Gobierno" not in textos
    tipos = [b.tipo for b in res.bloques]
    assert tipos[0] == "titulo"
    assert any(b.tipo == "texto" and "instruye" in b.texto for b in res.bloques)
    assert any("Punto uno" in b.texto for b in res.bloques)
    assert any("Rol | Valor" in b.texto for b in res.bloques)  # tabla → filas


def test_html_figure_con_data_uri():
    import base64

    from PIL import Image

    d = _tmpdir()
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    f = d / "conimg.html"
    f.write_text(
        f"""<html><body><h2>Informe</h2>
        <figure><img src="data:image/png;base64,{b64}" alt="esquema"/>
        <figcaption>Figura 1. Esquema del proceso.</figcaption></figure>
        <p>Cierre del informe.</p></body></html>""",
        encoding="utf-8",
    )
    res = extract_html(str(f))
    fig = next(b for b in res.bloques if b.tipo == "figura")
    assert fig.image_bytes is not None and fig.image_bytes[:4] == b"\x89PNG"
    assert "Esquema del proceso" in fig.texto  # caption asociado a la figura


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #


def test_docx_headings_parrafos_y_tabla():
    from docx import Document

    d = _tmpdir()
    doc = Document()
    doc.core_properties.title = "Norma técnica MINSAL"
    doc.core_properties.author = "Departamento Ejemplo"
    doc.add_heading("Norma técnica MINSAL", level=1)
    doc.add_heading("Alcance", level=2)
    doc.add_paragraph("Esta norma aplica a todos los establecimientos.")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Rol"
    t.cell(0, 1).text = "Valor"
    t.cell(1, 0).text = "A"
    t.cell(1, 1).text = "3"
    f = d / "norma.docx"
    doc.save(str(f))

    res = extract_docx(str(f))
    tipos = [b.tipo for b in res.bloques]
    assert tipos == ["titulo", "titulo", "texto", "texto"]
    assert res.titulo_documento == "Norma técnica MINSAL"
    assert res.autor == "Departamento Ejemplo"
    assert "establecimientos" in res.bloques[2].texto
    assert "Rol | Valor" in res.bloques[3].texto  # tabla → texto por filas


# --------------------------------------------------------------------------- #
# EPUB
# --------------------------------------------------------------------------- #


def _epub_de_prueba(path: Path) -> None:
    """EPUB mínimo válido: OPF con título/autor/cover + 2 capítulos."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 6), (10, 100, 200)).save(buf, "PNG")
    cover = buf.getvalue()

    cap1 = """<html><head><title>Cap 1</title></head><body>
      <h1>Capítulo primero</h1><p>Texto del primer capítulo.</p></body></html>"""
    cap2 = """<html><head><title>Cap 2</title></head><body>
      <h1>Capítulo segundo</h1><p>Texto del segundo capítulo.</p></body></html>"""
    opf = """<?xml version="1.0"?>
    <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Libro de prueba</dc:title>
        <dc:creator>Autoría Central</dc:creator>
        <meta name="cover" content="cover-img"/>
      </metadata>
      <manifest>
        <item id="cap1" href="cap1.xhtml" media-type="application/xhtml+xml"/>
        <item id="cap2" href="cap2.xhtml" media-type="application/xhtml+xml"/>
        <item id="cover-img" href="cover.png" media-type="image/png"/>
        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
      </manifest>
      <spine>
        <itemref idref="cap1"/><itemref idref="cap2"/>
      </spine>
    </package>"""
    container = """<?xml version="1.0"?>
    <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/></rootfiles>
    </container>"""

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/cap1.xhtml", cap1)
        z.writestr("OEBPS/cap2.xhtml", cap2)
        z.writestr("OEBPS/cover.png", cover)


def test_epub_spine_orden_metadatos_y_cover():
    d = _tmpdir()
    f = d / "libro.epub"
    _epub_de_prueba(f)
    res = extract_epub(str(f))

    assert res.titulo_documento == "Libro de prueba"
    assert res.autor == "Autoría Central"
    assert res.cover_png is not None and res.cover_png[:4] == b"\x89PNG"
    # spine en orden: cap1 antes que cap2, títulos de capítulo
    assert [b.texto for b in res.bloques] == [
        "Capítulo primero",
        "Texto del primer capítulo.",
        "Capítulo segundo",
        "Texto del segundo capítulo.",
    ]
    assert res.bloques[0].pagina == 1 and res.bloques[2].pagina == 2
    assert res.num_paginas == 2


def test_extract_any_despacha_por_extension():
    d = _tmpdir()
    f = d / "x.txt"
    f.write_text("TITULO CORTO\n\nUn párrafo.", encoding="utf-8")
    res = extract_any(str(f))
    assert [b.tipo for b in res.bloques] == ["titulo", "texto"]
    try:
        extract_any(str(d / "x.xyz"))
    except ValueError:
        pass
    else:
        raise AssertionError("debía rechazar extensión desconocida")
