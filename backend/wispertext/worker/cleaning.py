"""Normalización de texto extraído de PDFs para lectura TTS (ADR-007, RF-03).

Módulo 100 % stdlib y determinista: mismo input → mismo output. La versión del
normalizador entra en el hash de cache (ADR-005), por lo que cambiar estas
reglas invalida caches de forma controlada.

Problemas que resuelve (reportados por el usuario):
- acentos partidos/separados ("cafe´", "caf´e") → "café"
- ligaduras tipográficas (ﬁ → fi)
- palabras cortadas por guion de fin de línea ("infor-\\nmación")
- espacios/saltos de más dentro de un párrafo
- comillas/guiones tipográficos y caracteres de control
"""

import hashlib
import re
import unicodedata

# Acentos muertos que aparecen sueltos → combinante Unicode equivalente
_DEAD_KEYS = {
    "´": "\u0301",  # agudo
    "'": "\u0301",
    "`": "\u0300",  # grave
    "^": "\u0302",  # circunflejo
    "¨": "\u0308",  # diéresis
    "~": "\u0303",  # tilde
    "˜": "\u0303",  # tilde pequeña (U+02DC, LaTeX: "se˜nal" → "señal")
}

_LIGATURES = {
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬆ": "st",
}

# Caracteres de control excepto tab/salto de línea; incluye soft hyphen y zero-width
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u2060]")

# Guion + (o soft hyphen) de fin de línea; grupos: (head)(sep)(tail)
_HYPHEN_EOL = re.compile(r"(\w+)([\u00ad-])\s*\n\s*(\w+)")

# Sub/superíndice matemático tipografiado en líneas: "T ∗\n2" → "T2∗"
# (los PDF de LaTeX parten T2* en líneas T / ∗ / 2)
_MATH_SUBSUP_NL = re.compile(r"([A-Za-z])\s*([∗*])\s*\n\s*(\d)\b")
_MATH_SUBSUP_SP = re.compile(r"([A-Za-z]) ([∗*]) (\d)\b")

# Énfasis markdown residual del original: "*in vivo*" → "in vivo"
_MD_EMPH = re.compile(r"\*+([^*\n]{1,120}?)\*+")

# Subíndice PERDIDO por glifo matemático sin texto extraíble: el PDF trae
# "T ∗" donde el original es T2∗ (U+2217, no el * de markdown). Solo aplica
# cuando NO hay dígito después (ese caso lo resuelve fix_math_subsup).
_MATH_TSTAR_LOST = re.compile(r"\bT\s+∗(?!\d)")
# Paréntesis perdido con él: "(T2∗ enfoque" → "(T2∗) enfoque"
_MATH_TSTAR_PAREN = re.compile(r"\(T2∗\s+(?=[a-záéíóúñ])")

_MULTI_SPACE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE = re.compile(r"\s*\n\s*")

# Citas entre corchetes / llamadas de nota al pie: [12], [12-14], [12, 15]
_BRACKET_REF = re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]")


def fix_ligatures(text: str) -> str:
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)
    return text


def fix_separated_accents(text: str) -> str:
    """Recompone acentos que quedaron separados de su vocal.

    Semántica de teclado (máquina de escribir): el acento muerto aplica a la
    vocal SIGUIENTE ("caf´e" → "café"). Si no hay vocal después, aplica a la
    vocal anterior ("cafe´" → "café").

    Incluye la "ı" (i sin punto, U+0131) que produce LaTeX: "Metodolog´ıa".
    La ı+acento no tiene forma precompuesta, así que se convierte a i+acento
    antes de recomponer (→ "Metodología").
    """
    nfd = unicodedata.normalize("NFD", text)
    letters = "aeiouıAEIOUüÜnN"  # n/N: la virgulilla LaTeX ("˜n" → "ñ")
    for dead, combining in _DEAD_KEYS.items():
        dead_esc = re.escape(dead)
        # 1) acento muerto + letra → letra + combinante
        nfd = re.sub(rf"{dead_esc}\s*([{letters}])", rf"\1{combining}", nfd)
        # 2) letra + acento muerto NO seguido de otra letra → letra + combinante
        nfd = re.sub(
            rf"([{letters}])\s*{dead_esc}(?![{letters}])", rf"\1{combining}", nfd
        )
    # ı+combinante → i+combinante (para que NFC componga í/ì/î…)
    nfd = re.sub("ı([\u0300-\u036f])", r"i\1", nfd)
    out = unicodedata.normalize("NFC", nfd)
    out = out.replace("ı", "i")  # ı residual sin acento → i (español)
    return out.replace("˜", "")  # virgulilla huérfana residual


def _hyphen_repl(m: re.Match) -> str:
    head, _sep, tail = m.group(1), m.group(2), m.group(3)
    # Solo unir palabras: la continuación debe empezar en minúscula
    # (evita romper "1990-\n1995" o "Capítulo 2\nAnexo").
    if tail[0].islower():
        return head + tail
    return f"{head}- {tail}"


def dehyphenate(text: str) -> str:
    """Une palabras cortadas por guion al final de línea."""
    return _HYPHEN_EOL.sub(_hyphen_repl, text)


def join_paragraph_lines(text: str) -> str:
    """Colapsa saltos de línea y espacios múltiples dentro de un párrafo."""
    text = _MULTI_NEWLINE.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def fix_math_subsup(text: str) -> str:
    """Recompone notación matemática partida en líneas: "T ∗\\n2" → "T2∗"."""
    text = _MATH_SUBSUP_NL.sub(r"\1\3\2", text)
    text = _MATH_SUBSUP_SP.sub(r"\1\3\2", text)
    return text


def normalize_for_tts(text: str) -> str:
    """Pipeline determinista de normalización de un párrafo."""
    if not text:
        return ""
    text = fix_ligatures(text)
    text = fix_separated_accents(text)
    text = dehyphenate(text)
    text = fix_math_subsup(text)
    text = _MATH_TSTAR_LOST.sub("T2∗", text)
    text = _MD_EMPH.sub(r"\1", text)
    text = _CONTROL.sub("", text)
    text = text.replace("\u00ad", "")  # soft hyphen residual
    # Tipográficos → neutros para TTS
    text = text.translate(
        str.maketrans(
            {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "..."}
        )
    )
    text = join_paragraph_lines(text)
    # cierre del paréntesis perdido junto al subíndice (aplica post-join)
    return _MATH_TSTAR_PAREN.sub("(T2∗) ", text)


def strip_bracket_refs(text: str) -> str:
    """Quita referencias [12] y llama a colapso de espacios."""
    text = _BRACKET_REF.sub("", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def _norm_furniture_line(line: str) -> str:
    """Normaliza una línea para comparar mobiliario (minúsculas, dígitos → #)."""
    return re.sub(r"\d+", "#", line.strip().lower())


def find_repeated_furniture(pages_lines: list[list[str]], min_pages: int = 3) -> set[str]:
    """Detecta encabezados/pies repetidos entre páginas.

    Recibe, por página, líneas candidatas (primera/última de cada bloque).
    Se normalizan internamente para que "Página 12" y "Página 13" cuenten
    como la misma. Una línea presente en ≥ min_pages páginas (o >60 % si
    hay pocas) se considera mobiliario y debe eliminarse de los párrafos.
    """
    counts: dict[str, int] = {}
    for lines in pages_lines:
        for raw in set(lines):
            line = _norm_furniture_line(raw)
            if line:
                counts[line] = counts.get(line, 0) + 1
    if not pages_lines:
        return set()
    threshold = max(min_pages, int(len(pages_lines) * 0.6) + 1)
    return {line for line, n in counts.items() if n >= threshold}


def paragraph_hash(texto_normalizado: str, idioma: str, normalizer_version: str) -> str:
    """Hash del párrafo: identidad para diff y cache de audio (ADR-005)."""
    payload = f"{normalizer_version}|{idioma}|{texto_normalizado.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def looks_like_junk(text: str) -> bool:
    """Párrafos que no aportan a la escucha: números de página, líneas de guiones."""
    stripped = text.strip()
    if not stripped:
        return True
    if re.fullmatch(r"[\d\s\-–—.,:;|/]+", stripped):
        return True
    return False
