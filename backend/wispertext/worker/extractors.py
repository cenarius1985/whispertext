"""Extractores multi-formato (RF-MF-02…07, PRD v2): txt/md/docx/html/epub.

Contrato: cada extractor devuelve el MISMO ``ExtractionResult`` que
``extract_pdf`` (bloques ``RawBlock`` en orden de lectura), de modo que el
pipeline posterior (limpieza → normalizador → ecuaciones → diff → TTS) es
agnóstico del formato de origen. ``extract_any`` es el dispatcher que usa
el worker según la extensión del archivo.
"""

import base64
import io
import logging
import re
import zipfile
from pathlib import Path, PurePosixPath

from wispertext.worker.extraction import (
    ExtractionResult,
    RawBlock,
    extract_pdf,
)

log = logging.getLogger("wispertext.extractors")

FORMATOS = {"txt", "text", "md", "docx", "html", "htm", "epub"}

# Páginas "lógicas" para formatos sin páginas: 1 bloque ≈ 1 párrafo, así el
# filtro editorial (que consulta Bonsai en primeras/últimas páginas) no
# escanea todo el documento.
_BLOQUES_POR_PAGINA = 30


def _pag(idx: int) -> int:
    return idx // _BLOQUES_POR_PAGINA + 1


def _to_png(raw: bytes) -> bytes | None:
    """Cualquier imagen (jpg/png/gif/webp) → PNG bytes (Pillow)."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.debug("imagen no convertible: %s", exc)
        return None


def _leer_texto(path: str) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


# --------------------------------------------------------------------------- #
# TXT / MD
# --------------------------------------------------------------------------- #

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_MD_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
_TERMINAL = re.compile(r"[.!?…:;]$")
_MAYUSCULAS = re.compile(r"[A-ZÁÉÍÓÚÑ]")


def _es_titulo_txt(linea: str) -> bool:
    t = linea.strip()
    if not t or len(t) > 80 or _TERMINAL.search(t[-1]):
        return False
    letras = [c for c in t if c.isalpha()]
    if not letras:
        return False
    up = sum(1 for c in letras if c.isupper())
    # Mayúsculas predominantes (NORMA TÉCNICA) o snake/kebab-case corto
    return up / len(letras) >= 0.7 or (len(t.split()) <= 6 and not " " in t.strip("-_"))


def extract_text(path: str, markdown: bool = False) -> ExtractionResult:
    res = ExtractionResult()
    texto = _leer_texto(path)

    # Separar bloques de código (md) primero: los fences pueden abarcar
    # párrafos vacíos y deben salir como bloque único no leído.
    segmentos: list[tuple[str, str]] = []  # (kind, contenido)
    if markdown:
        partes = re.split(r"```", texto)
        for i, parte in enumerate(partes):
            if not parte.strip():
                continue
            # el primer segmento (i=0) y los pares están fuera de fences;
            # impares = dentro del fence (la 1ª línea es el lenguaje)
            if i % 2 == 1:
                contenido = "\n".join(parte.splitlines()[1:]) if parte.splitlines() else parte
                segmentos.append(("codigo", contenido.strip()))
            else:
                segmentos.append(("md", parte))
    else:
        segmentos.append(("txt", texto))

    idx = 0
    for kind, contenido in segmentos:
        if kind == "codigo":
            res.bloques.append(RawBlock(_pag(idx), "codigo", contenido))
            idx += 1
            continue
        # Párrafos por línea vacía
        for parrafo in re.split(r"\n\s*\n", contenido):
            p = parrafo.strip()
            if not p:
                continue
            lineas = [ln.strip() for ln in p.splitlines() if ln.strip()]
            if not lineas:
                continue
            if markdown:
                # headings #: el párrafo completo de headings concatenados
                heads = [_MD_HEADING.match(ln) for ln in lineas]
                if heads and all(heads):
                    titulo = " ".join(m.group(2).strip() for m in heads if m)
                    if titulo:
                        res.bloques.append(RawBlock(_pag(idx), "titulo", titulo))
                        idx += 1
                        if not res.titulo_documento:
                            res.titulo_documento = titulo[:300]
                    continue
                # tabla markdown: bloque con separador |---|---|
                if len(lineas) >= 2 and any(_MD_TABLE_SEP.match(ln) for ln in lineas):
                    res.bloques.append(RawBlock(_pag(idx), "codigo", p))
                    idx += 1
                    continue
            else:
                if len(lineas) == 1 and _es_titulo_txt(lineas[0]):
                    res.bloques.append(RawBlock(_pag(idx), "titulo", lineas[0]))
                    idx += 1
                    if not res.titulo_documento:
                        res.titulo_documento = lineas[0][:300]
                    continue
            res.bloques.append(RawBlock(_pag(idx), "texto", "\n".join(lineas)))
            idx += 1

    if not res.titulo_documento and res.bloques:
        res.titulo_documento = res.bloques[0].texto.strip().splitlines()[0][:300]
    res.num_paginas = max(1, _pag(len(res.bloques) - 1)) if res.bloques else 1
    return res


# --------------------------------------------------------------------------- #
# HTML (usado también por EPUB)
# --------------------------------------------------------------------------- #

_DESCARTAR = ("script", "style", "nav", "header", "footer", "aside", "form",
              "noscript", "iframe", "svg", "button", "template")
_EMITIR = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote",
           "figcaption", "dt", "dd", "pre"}
_CONTENEDORES = {"html", "body", "div", "section", "article", "main", "ul",
                 "ol", "dl", "figure", "table", "thead", "tbody", "tr", "td",
                 "th", "caption", "details", "summary", "center", "td"}


def _decode_data_uri(src: str) -> bytes | None:
    m = re.match(r"data:image/\w+;base64,(.+)", src, re.DOTALL)
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1))
    except Exception:  # noqa: BLE001
        return None


def walk_soup(
    node,
    base_dir: Path | None,
    raiz_zip: zipfile.ZipFile | None = None,
    ruta_relativa: str = "",
    contador: list[int] | None = None,
) -> list[RawBlock]:
    """Recorre el árbol en orden de documento emitiendo RawBlocks.

    base_dir/raiz_zip/ruta_relativa permiten resolver imágenes: archivo local
    (HTML del disco) o entrada del zip (capítulo EPUB).
    """
    from bs4.element import Tag

    contador = contador if contador is not None else [0]
    bloques: list[RawBlock] = []

    def emitir(tipo: str, texto: str, img: bytes | None = None) -> None:
        texto = texto.strip()
        if tipo != "figura" and not texto:
            return
        bloques.append(RawBlock(_pag(contador[0]), tipo, texto, img))
        contador[0] += 1

    def leer_imagen(src: str) -> bytes | None:
        if not src:
            return None
        raw = _decode_data_uri(src)
        if raw is not None:
            return _to_png(raw)
        if raiz_zip is not None and ruta_relativa:
            # ruta relativa al capítulo dentro del zip
            objetivo = str(
                PurePosixPath(ruta_relativa).parent / PurePosixPath(src.split("?")[0])
            ).lstrip("/")
            try:
                return _to_png(raiz_zip.read(objetivo))
            except KeyError:
                return None
        if base_dir is not None:
            archivo = (base_dir / src.split("?")[0].lstrip("/")).resolve()
            try:
                if archivo.is_file():
                    return _to_png(archivo.read_bytes())
            except OSError:
                return None
        return None

    def walk(el) -> None:
        if not isinstance(el, Tag):  # NavigableString/comment: nada que hacer
            return
        tag = el.name
        if tag in _DESCARTAR:
            return
        if tag == "figure":
            # figura con caption asociado (img + figcaption en cualquier orden)
            img_el = el.find("img")
            cap_el = el.find("figcaption")
            if img_el is not None:
                img = leer_imagen(img_el.get("src", ""))
                caption = cap_el.get_text(" ", strip=True) if cap_el else (img_el.get("alt") or "")
                if img is not None or caption:
                    emitir("figura", caption, img)
            elif cap_el is not None:
                walk(cap_el)
            for sub in el.children:
                if sub is not cap_el and getattr(sub, "name", None) not in (None, "img", "figcaption"):
                    walk(sub)
            return
        if tag == "img":
            src = el.get("src", "")
            alt = (el.get("alt") or "").strip()
            img = leer_imagen(src)
            if img is not None:
                emitir("figura", alt, img)
            elif alt:
                emitir("texto", alt)  # alt descriptivo sin imagen accesible
            return
        if tag == "table":
            filas = []
            for tr in el.find_all("tr"):
                celdas = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                fila = " | ".join(c for c in celdas if c)
                if fila:
                    filas.append(fila)
            if filas:
                emitir("texto", "\n".join(filas))
            return
        if tag in _EMITIR:
            texto = el.get_text("\n", strip=True)
            if not texto:
                return
            tipo = "titulo" if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} else (
                "codigo" if tag == "pre" else "texto"
            )
            emitir(tipo, texto)
            return
        for sub in el.children:
            walk(sub)

    walk(node)
    return bloques


def extract_html(path: str) -> ExtractionResult:
    from bs4 import BeautifulSoup

    res = ExtractionResult()
    soup = BeautifulSoup(_leer_texto(path), "lxml")
    for tag in soup(_DESCARTAR):
        tag.decompose()

    if soup.title and soup.title.get_text(strip=True):
        res.titulo_documento = soup.title.get_text(strip=True)[:300]

    res.bloques = walk_soup(soup, base_dir=Path(path).parent)
    if not res.titulo_documento and res.bloques:
        res.titulo_documento = res.bloques[0].texto.strip().splitlines()[0][:300]
    res.num_paginas = max(1, _pag(len(res.bloques) - 1)) if res.bloques else 1
    return res


# --------------------------------------------------------------------------- #
# DOCX (Word)
# --------------------------------------------------------------------------- #

_NS_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_NS_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def extract_docx(path: str) -> ExtractionResult:
    from docx import Document as Docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    res = ExtractionResult()
    docx = Docx(path)
    idx = 0

    props = docx.core_properties
    res.autor = (props.author or "").strip()[:200]
    if (props.title or "").strip():
        res.titulo_documento = props.title.strip()[:300]

    for child in docx.element.body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, docx)
            texto = p.text.strip()
            # imágenes embebidas del párrafo → figura (la 1ª imagen además es portada)
            for blip in child.iter(_NS_BLIP):
                rid = blip.get(_NS_EMBED)
                part = docx.part.related_parts.get(rid) if rid else None
                if part is None:
                    continue
                png = _to_png(part.blob)
                if png is None:
                    continue
                if res.cover_png is None:
                    res.cover_png = png
                    continue
                res.bloques.append(RawBlock(_pag(idx), "figura", "", png))
                idx += 1
            if not texto:
                continue
            estilo = (p.style.name if p.style is not None else "") or ""
            es_titulo = estilo.startswith(("Heading", "Title", "Encabezado", "Título"))
            if es_titulo or (len(texto) <= 90 and not _TERMINAL.search(texto[-1]) and estilo):
                res.bloques.append(RawBlock(_pag(idx), "titulo", texto))
                idx += 1
                if not res.titulo_documento:
                    res.titulo_documento = texto[:300]
                continue
            res.bloques.append(RawBlock(_pag(idx), "texto", texto))
            idx += 1
        elif tag == "tbl":
            t = Table(child, docx)
            filas = []
            for row in t.rows:
                fila = " | ".join(
                    c.text.strip() for c in row.cells if c.text.strip()
                )
                if fila:
                    filas.append(fila)
            if filas:
                res.bloques.append(RawBlock(_pag(idx), "texto", "\n".join(filas)))
                idx += 1

    if not res.titulo_documento and res.bloques:
        res.titulo_documento = res.bloques[0].texto.strip().splitlines()[0][:300]
    res.num_paginas = max(1, _pag(idx - 1)) if idx else 1
    return res


# --------------------------------------------------------------------------- #
# EPUB
# --------------------------------------------------------------------------- #

_XHTML_TYPES = ("application/xhtml+xml", "text/html", "application/xml", "text/xml")


def extract_epub(path: str) -> ExtractionResult:
    from bs4 import BeautifulSoup

    res = ExtractionResult()
    zf = zipfile.ZipFile(path)

    # container.xml → ruta del OPF
    container = BeautifulSoup(zf.read("META-INF/container.xml"), "lxml")
    opf_path = container.find("rootfile")["full-path"]
    opf_dir = str(PurePosixPath(opf_path).parent)

    opf = BeautifulSoup(zf.read(opf_path), "lxml")
    titulo = opf.find("dc:title")
    if titulo is None:  # algunos OPF sin prefijo
        titulo = opf.find("title")
    if titulo is not None and titulo.get_text(strip=True):
        res.titulo_documento = titulo.get_text(strip=True)[:300]
    creador = opf.find("dc:creator") or opf.find("creator")
    if creador is not None:
        res.autor = creador.get_text(strip=True)[:200]

    # manifest: id → (href, media-type, properties)
    items: dict[str, dict] = {}
    for it in opf.find_all("item"):
        items[it.get("id", "")] = {
            "href": it.get("href", ""),
            "media": it.get("media-type", ""),
            "props": it.get("properties", "") or "",
        }

    # portada: properties=cover-image o <meta name="cover">
    cover_href = None
    for it in items.values():
        if "cover-image" in it["props"]:
            cover_href = it["href"]
            break
    if cover_href is None:
        meta = opf.find("meta", attrs={"name": "cover"})
        if meta is not None and meta.get("content") in items:
            cover_href = items[meta["content"]]["href"]
    if cover_href:
        try:
            res.cover_png = _to_png(zf.read(f"{opf_dir}/{cover_href}".lstrip("./")))
        except KeyError:
            pass

    # spine: orden de lectura
    idx = 0
    for ref in opf.find_all("itemref"):
        item = items.get(ref.get("idref", ""))
        if item is None or item["media"] not in _XHTML_TYPES:
            continue
        ruta_cap = f"{opf_dir}/{item['href']}".lstrip("./") if opf_dir else item["href"]
        try:
            html = zf.read(ruta_cap).decode("utf-8", errors="replace")
        except KeyError:
            continue
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(_DESCARTAR):
            tag.decompose()
        # página = capítulo+1 (zonas editoriales reales del epub: créditos al final)
        bloques_cap = walk_soup(soup, base_dir=None, raiz_zip=zf, ruta_relativa=ruta_cap)
        for b in bloques_cap:
            b.pagina = idx + 1
            res.bloques.append(b)
        idx += 1

    res.num_paginas = max(1, idx)
    if not res.titulo_documento and res.bloques:
        res.titulo_documento = res.bloques[0].texto.strip().splitlines()[0][:300]
    return res


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #


def extract_any(path: str) -> ExtractionResult:
    """RF-MF-02: enruta por extensión al extractor correspondiente."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext in (".txt", ".text"):
        return extract_text(path, markdown=False)
    if ext == ".md":
        return extract_text(path, markdown=True)
    if ext == ".docx":
        return extract_docx(path)
    if ext in (".html", ".htm"):
        return extract_html(path)
    if ext == ".epub":
        return extract_epub(path)
    raise ValueError(f"formato no soportado: {ext}")
