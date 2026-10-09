"""Extracción estructurada de PDFs con PyMuPDF + OCR de respaldo (ADR-007).

Entrega bloques ordenados (posición de lectura) clasificados en texto, título
y figura (imagen + caption), para que el worker los convierta en párrafos.

Figuras: además de imágenes raster, se recuperan GRÁFICOS VECTORIALES
(matplotlib etc.) renderizando la región del PDF asociada a su caption
("FIGURE 1 | …" / "Figura 2. …" / tablas). Las ecuaciones numeradas se
renderizan como imagen (se muestran fieles al PDF; el audio las salta).
"""

import io
import logging
import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from wispertext.config import get_settings
from wispertext.worker.cleaning import find_repeated_furniture

log = logging.getLogger("wispertext.extraction")

# Captions ES/EN, case-insensitive: "FIGURE 1 |", "Figura 2.", "Table 3"
CAPTION_RE = re.compile(
    r"^\s*(fig(?:ura|ure)?s?\.?|tabla|table|imagen|cuadro|gr[áa]fico|esquema|scheme"
    r"|l[áa]mina)[\s.]*\d+",
    re.IGNORECASE,
)
# Ecuación numerada: termina en "(12)" y es corta
_EQ_NUM_RE = re.compile(r"\(\d{1,3}\)\s*$")
_MATHY_CHARS = set("∥∑∫∂√≈≤≥±∗∆Δθρσπλαβγωτφ×µ")
_EQ_EQ_CHARS = set("+-=*/^_|")

_TERMINAL_PUNCT = re.compile(r"[.!?…:;]$")
_MIN_OCR_TEXT = 20
_MIN_IMAGE_DIM = 90
_FIGURE_MIN_AREA = 40 * 40


@dataclass
class RawBlock:
    pagina: int
    tipo: str  # texto | titulo | figura
    texto: str = ""  # en figura: caption (puede venir vacío)
    image_bytes: bytes | None = None


@dataclass
class ExtractionResult:
    bloques: list[RawBlock] = field(default_factory=list)
    num_paginas: int = 0
    paginas_ocr: list[int] = field(default_factory=list)
    titulo_documento: str = ""
    autor: str = ""  # docx/epub: metadatos del origen (PDF lo deja vacío)
    cover_png: bytes | None = None


def _norm_furniture_line(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def _page_edge_lines(pdict: dict) -> list[str]:
    """Primeras/últimas 2 líneas de los bloques extremos (mobiliario)."""
    blocks = [b for b in pdict.get("blocks", []) if b.get("type") == 0]
    out: list[str] = []
    if blocks:
        for ln in blocks[0].get("lines", [])[:2]:
            out.append("".join(sp.get("text", "") for sp in ln.get("spans", [])))
    if len(blocks) > 1:
        for ln in blocks[-1].get("lines", [])[-2:]:
            out.append("".join(sp.get("text", "") for sp in ln.get("spans", [])))
    return out


def _body_font_size(doc: fitz.Document) -> float:
    sizes: dict[float, int] = {}
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b.get("lines", []):
                for sp in ln.get("spans", []):
                    size = round(sp.get("size", 0) * 2) / 2
                    sizes[size] = sizes.get(size, 0) + len(sp.get("text", ""))
    if not sizes:
        return 11.0
    return max(sizes, key=sizes.get)  # type: ignore[return-value]


def _block_text(block: dict) -> str:
    parts = []
    for ln in block.get("lines", []):
        parts.append("".join(sp.get("text", "") for sp in ln.get("spans", [])))
    return "\n".join(p for p in parts if p.strip())


def _is_title(block: dict, body_size: float) -> bool:
    sizes: list[float] = []
    text = ""
    bold_chars = 0
    for ln in block.get("lines", []):
        for sp in ln.get("spans", []):
            sizes.append(sp.get("size", 0))
            text += sp.get("text", "")
            if "bold" in sp.get("font", "").lower():
                bold_chars += len(sp.get("text", ""))
    text = text.strip()
    if not text or len(text) > 250:
        return False
    if sizes and max(sizes) >= body_size * 1.3:
        return True
    total = max(len(text), 1)
    return bold_chars / total > 0.7 and len(text.split()) <= 20


def _image_png(doc: fitz.Document, xref: int) -> bytes | None:
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n - pix.alpha > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        return pix.tobytes("png")
    except Exception as exc:  # noqa: BLE001
        log.debug("xref %s no extraíble: %s", xref, exc)
        return None


def _render_clip(page: fitz.Page, rect: fitz.Rect, dpi: int = 150) -> bytes | None:
    """Renderiza una región del PDF a PNG (figuras vectoriales, ecuaciones)."""
    try:
        rect = rect & page.rect  # recorta al área de la página
        if rect.is_empty or rect.width < 20 or rect.height < 12:
            return None
        return page.get_pixmap(clip=rect, dpi=dpi).tobytes("png")
    except Exception as exc:  # noqa: BLE001
        log.debug("render clip falló: %s", exc)
        return None


def _is_equation(text: str) -> bool:
    """Ecuación display numerada: "(12)" final, corta y densa en matemática."""
    t = text.strip()
    if len(t) > 250 or not _EQ_NUM_RE.search(t):
        return False
    if any(c in _MATHY_CHARS for c in t):
        return True
    if not re.search(r"[a-zA-Z]", t):
        return True
    symbolic = sum(1 for c in t if c.isdigit() or c in _EQ_EQ_CHARS or c.isspace())
    return symbolic / max(len(t), 1) > 0.5


def _ocr_page(page: fitz.Page, langs: str) -> str:
    try:
        import pytesseract
        from PIL import Image

        png = page.get_pixmap(dpi=200).tobytes("png")
        return pytesseract.image_to_string(Image.open(io.BytesIO(png)), lang=langs)
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR no disponible en página %s: %s", page.number + 1, exc)
        return ""


def _x_overlap(a: fitz.Rect, b: fitz.Rect) -> float:
    lo = max(a.x0, b.x0)
    hi = min(a.x1, b.x1)
    return max(0.0, hi - lo)


_FIGURE_GAP_PT = 70  # separación máx. entre partes contiguas de una figura


def _recover_figures(page: fitz.Page, items: list[dict]) -> None:
    """Detecta captions y recupera la figura asociada (vector o raster).

    Criterio tipográfico: las FIGURAS llevan caption DEBAJO (se busca la
    imagen arriba del caption); las TABLAS llevan caption ARRIBA (se busca
    debajo). Desde el candidato más cercano al borde del caption se expande
    por contigüidad (une subplots de una misma figura sin saltar a la vecina).
    """
    try:
        clusters = [fitz.Rect(c) for c in page.cluster_drawings()]
    except Exception:  # noqa: BLE001
        clusters = []
    cand = [r for r in clusters if r.width > 15 and r.height > 8]
    for it in items:
        if it["tipo"] == "figura" and it.get("rect") is not None:
            cand.append(fitz.Rect(it["rect"]))

    used: set[int] = set()  # índices de cand ya absorbidos por otra figura

    def caption_side(first_line: str) -> str:
        return "abajo" if re.match(r"^\s*(tabla|table)\b", first_line, re.I) else "arriba"

    for it in items:
        if it["tipo"] == "figura" or it.get("_consumed"):
            continue
        first_line = it["texto"].split("\n", 1)[0]
        if not CAPTION_RE.match(first_line):
            continue
        cap = fitz.Rect(it["rect"])
        cap_w = max(cap.width, 1)
        sides = ["arriba", "abajo"] if caption_side(first_line) == "arriba" else ["abajo", "arriba"]
        for side in sides:
            if side == "arriba":
                pool = [r for r in cand if r.y1 <= cap.y0 + 12]
                key = lambda r: cap.y0 - r.y1  # gap al borde superior
            else:
                pool = [r for r in cand if r.y0 >= cap.y1 - 12]
                key = lambda r: r.y0 - cap.y1
            pool = [r for r in sorted(pool, key=key) if _x_overlap(r, cap) > 0.25 * cap_w]
            union = None
            for r in pool:
                if union is None:
                    if key(r) <= _FIGURE_GAP_PT:
                        union = fitz.Rect(r)
                    else:
                        break  # ordenado: los demás están más lejos
                    continue
                contiguo = (
                    r.intersects(union)
                    or min(abs(r.y0 - union.y1), abs(union.y0 - r.y1)) <= _FIGURE_GAP_PT
                )
                if contiguo and _x_overlap(r, union) > 0.2 * max(union.width, 1):
                    union |= r
                else:
                    break
            if union is not None and union.get_area() >= _FIGURE_MIN_AREA:
                union += (-4, -4, 4, 4)
                png = _render_clip(page, union)
                if png:
                    it["tipo"] = "figura"
                    it["png"] = png
                    it["rect"] = tuple(union)
                    for other in items:
                        if (
                            other is not it
                            and other.get("_raster")
                            and fitz.Rect(other["rect"]).intersects(union)
                        ):
                            other["_consumed"] = True
                    break


def extract_pdf(path: str) -> ExtractionResult:
    settings = get_settings()
    result = ExtractionResult()
    doc = fitz.open(path)
    result.num_paginas = doc.page_count
    try:
        result.cover_png = doc[0].get_pixmap(dpi=110).tobytes("png")
    except Exception:  # noqa: BLE001
        result.cover_png = None

    body_size = _body_font_size(doc)

    page_dicts = [page.get_text("dict") for page in doc]
    furniture_input = [
        [_norm_furniture_line(x) for x in _page_edge_lines(pd) if x.strip()]
        for pd in page_dicts
    ]
    furniture = find_repeated_furniture(furniture_input)

    def drop_furniture(text: str) -> str:
        kept = [
            ln
            for ln in text.split("\n")
            if not ln.strip() or _norm_furniture_line(ln) not in furniture
        ]
        return "\n".join(kept)

    for pnum, (page, pdict) in enumerate(zip(doc, page_dicts), start=1):
        if len(page.get_text().strip()) < _MIN_OCR_TEXT:
            ocr_text = _ocr_page(page, settings.tesseract_langs)
            if ocr_text.strip():
                result.paginas_ocr.append(pnum)
                result.bloques.append(RawBlock(pnum, "texto", ocr_text))
                for b in pdict.get("blocks", []):
                    if (
                        b.get("type") == 1
                        and b.get("width", 0) >= _MIN_IMAGE_DIM
                        and b.get("number")
                    ):
                        png = _image_png(doc, b["number"])
                        if png:
                            result.bloques.append(RawBlock(pnum, "figura", "", png))
                continue

        items: list[dict] = []
        for b in pdict.get("blocks", []):
            if b.get("type") == 0:
                txt = drop_furniture(_block_text(b))
                if txt.strip():
                    if _is_equation(txt):
                        # ecuación display: se renderiza fiel y el texto lineal
                        # se conserva para que Bonsai reconstruya LaTeX+habla
                        png = _render_clip(page, fitz.Rect(b["bbox"]), dpi=170)
                        items.append(
                            {"tipo": "ecuacion", "texto": txt, "y": b["bbox"][1],
                             "rect": b["bbox"], "png": png}
                        )
                        continue
                    tipo = "titulo" if _is_title(b, body_size) else "texto"
                    items.append(
                        {"tipo": tipo, "texto": txt, "y": b["bbox"][1],
                         "rect": b["bbox"], "png": None}
                    )
            elif (
                b.get("type") == 1
                and b.get("width", 0) >= _MIN_IMAGE_DIM
                and b.get("number")
            ):
                # png puede fallar (xref corrupto): igual dejamos el rect como
                # candidato para la recuperación por caption (render del clip)
                png = _image_png(doc, b["number"])
                items.append(
                    {"tipo": "figura", "texto": "", "y": b["bbox"][1],
                     "rect": b["bbox"], "png": png, "_raster": True}
                )
        items.sort(key=lambda it: it["y"])

        # Figuras vectoriales/raster con caption (ES/EN, case-insensitive)
        _recover_figures(page, items)

        # caption clásico debajo de una figura raster (sin cluster vectorial)
        used_as_caption: set[int] = set()
        for i, it in enumerate(items):
            if it["tipo"] != "figura" or it.get("_consumed"):
                continue
            for j in range(i + 1, len(items)):
                if items[j]["tipo"] == "figura" or items[j].get("_consumed"):
                    break
                if j in used_as_caption:
                    continue
                first_line = items[j]["texto"].split("\n", 1)[0]
                if CAPTION_RE.match(first_line) and len(items[j]["texto"]) < 900:
                    it["texto"] = items[j]["texto"]
                    used_as_caption.add(j)
                    break

        for j, it in enumerate(items):
            if it.get("_consumed"):
                continue
            if j in used_as_caption and it["tipo"] != "figura":
                continue
            if it["tipo"] == "figura" and not it.get("png") and not it["texto"].strip():
                continue  # raster sin imagen recuperable ni caption
            result.bloques.append(RawBlock(pnum, it["tipo"], it["texto"], it["png"]))

    # ---- Fusión de cortes de párrafo entre bloques ----
    merged: list[RawBlock] = []
    for b in result.bloques:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev.tipo == "texto"
            and b.tipo == "texto"
            and b.pagina == prev.pagina
            and prev.texto.strip()
            and not _TERMINAL_PUNCT.search(prev.texto.strip()[-1])
            and (b.texto.strip()[:1] or "").islower()
        ):
            prev.texto = prev.texto + "\n" + b.texto
        else:
            merged.append(b)

    # ---- Sub/superíndice matemático partido ENTRE bloques ----
    i = 1
    while i < len(merged):
        prev, cur = merged[i - 1], merged[i]
        if (
            prev.tipo == "texto"
            and cur.tipo == "texto"
            and re.search(r"[A-Za-z]\s*[∗*]\s*$", prev.texto.strip())
            and re.match(r"\d\b", cur.texto.lstrip())
        ):
            prev.texto = prev.texto.rstrip() + "\n" + cur.texto.lstrip()
            merged.pop(i)
        else:
            i += 1
    result.bloques = merged

    # ---- Título del documento: líneas del mayor tamaño de la cabecera ----
    # (los títulos multilínea se unen; los acentos rotos se normalizan)
    if page_dicts:
        from wispertext.worker import cleaning as _cleaning

        try:
            h0 = doc[0].rect.height
        except Exception:  # noqa: BLE001
            h0 = 800.0
        lines: list[tuple[float, str, float]] = []  # (y, texto, tamaño_máx)
        for b in page_dicts[0].get("blocks", []):
            if b.get("type") != 0:
                continue
            for ln in b.get("lines", []):
                if ln["bbox"][1] >= h0 * 0.45:
                    continue
                txt, size = "", 0.0
                for sp in ln.get("spans", []):
                    if sp.get("text", "").strip():
                        txt += sp["text"]
                        size = max(size, sp.get("size", 0))
                if txt.strip():
                    lines.append((ln["bbox"][1], txt.strip(), size))
        if lines:
            umbral = max(s for _, _, s in lines) * 0.9
            elegidas = sorted((l for l in lines if l[2] >= umbral))
            crudo = " ".join(t for _, t, _ in elegidas)
            result.titulo_documento = _cleaning.normalize_for_tts(crudo)[:300]
    return result
