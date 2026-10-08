"""Filtro editorial determinista (RF-04, camino regex; Bonsai es el respaldo
dudoso en editorial_bonsai). Módulo stdlib puro para tests.
"""

import re

# Patrones fuertes: casi siempre son páginas legales/créditos
_STRONG = [
    (r"\bISBN\b", "isbn"),
    (r"\bISSN\b", "issn"),
    (r"©|&copy;|\(c\)\s*\d{2,4}", "copyright"),
    (r"\bcopyright\b", "copyright"),
    (r"derechos\s+(de\s+)?(autor|reservados)", "copyright"),
    (r"\ball\s+rights\s+reserved\b", "copyright"),
    (r"dep[óo]sito\s+legal", "deposito_legal"),
    (r"hecho\s+el\s+dep[óo]sito", "deposito_legal"),
    (r"(primera|segunda|tercera)\s+(edici[óo]n|reimpresi[óo]n)", "edicion"),
    (r"impres[oa]\s+(en|por)", "impreso"),
    (r"\beditorial\s+[A-ZÁÉÍÓÚÑ]", "editorial"),
    (r"\bEditado\s+por\b", "editorial"),
    (r"tirada\s+de\s+\d+", "impreso"),
    (r"\bI\.?S\.?B\.?N\.?\s*[:\-]?\s*[\d\-Xx]{10,17}", "isbn"),
    (r"www\.[^\s]+\.(cl|com|es|org)", "web_legal"),
    (r"dise[ñn]o\s+(de\s+)?(portada|tapa|interiores)", "diseno"),
    (r"correcci[óo]n\s+(de\s+(estilo|pruebas)|ortotipogr[áa]fica)", "correccion"),
    (r"diagramaci[óo]n", "diseno"),
    (r"comit[ée]\s+editorial", "editorial"),
    (r"los\s+textos\s+(de\s+este|del\s+presente)\s+(libro|documento)", "copyright"),
]

_STRONG_RE = [(re.compile(p, re.IGNORECASE), reason) for p, reason in _STRONG]

# Señales débiles: suman puntaje
_WEAK = [
    (re.compile(r"^\s*(por|de)\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)+\s*$", re.M | re.I), "credito_autor"),
    (re.compile(r"^\s*\d{4}\s*$", re.M), "anio_solo"),
    (re.compile(r"(coordinaci[óo]n|compilaci[óo]n|revisi[óo]n\s+t[ée]cnica)\s*(general)?\s*:", re.I), "credito_rol"),
]

# Un bloque corto con ≥2 señales débiles o 1 fuerte → editorial
_STRONG_THRESHOLD = 1
_WEAK_THRESHOLD = 2
_MAX_EDITORIAL_CHARS = 600  # bloques muy largos casi nunca son puro editorial


def classify_editorial(text: str) -> tuple[bool, str | None]:
    """Devuelve (es_editorial, motivo). Determinista, sin LLM."""
    if not text or not text.strip():
        return True, "vacio"
    if len(text.strip()) > _MAX_EDITORIAL_CHARS:
        return False, None
    hits: list[str] = []
    for rx, reason in _STRONG_RE:
        if rx.search(text):
            hits.append(reason)
    if hits:
        return True, hits[0]
    weak = sum(1 for rx, _ in _WEAK if rx.search(text))
    if weak >= _WEAK_THRESHOLD:
        return True, "creditos"
    return False, None
