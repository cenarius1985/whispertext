"""Preparación del texto hablado (RF-14): siglas, números, URLs, traducción.

Determinista primero (diccionario + reglas); Argos/Bonsai solo para traducir.
"""

import logging
import re

from wispertext.worker.cleaning import strip_bracket_refs

log = logging.getLogger("wispertext.speakable")

# Diccionario por defecto de pronunciación de siglas (editable desde ajustes en P1)
DEFAULT_SIGLAS: dict[str, str] = {
    "OMS": "Organización Mundial de la Salud",
    "OPS": "Organización Panamericana de la Salud",
    "ONU": "Organización de las Naciones Unidas",
    "MINSAL": "Ministerio de Salud",
    "ISO": "I S O",
    "OIT": "Organización Internacional del Trabajo",
    "UNESCO": "Unesco",
    "UNICEF": "Unicef",
    "CEPAL": "Cepal",
    "FMI": "Fondo Monetario Internacional",
    "BID": "Banco Interamericano de Desarrollo",
    "ISS": "Instituto de Seguridad Social",
    "REM": "lista de espera no urgente",  # contexto MINSAL
    "NR": "norma ramal",
    "PDF": "P D F",
}

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MULTI_PUNCT = re.compile(r"([.,;:!?¡¿])(?:\s*\1)+")
_WS_RE = re.compile(r"\s+")

# Notación técnica MRI dicha como se lee en voz alta (textos del usuario)
# — orden importa: T2* antes que T2; unidades antes que símbolos sueltos.
_SPOKEN_TOKENS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bT\s*2\s*[∗*]s?(?!\w)"), "T dos estrella"),
    (re.compile(r"\bT\s*2(?:s)?\b"), "T dos"),
    (re.compile(r"\bT\s*1(?:s)?\b"), "T uno"),
    (re.compile(r"\bB\s*0\b"), "B cero"),
    (re.compile(r"\bB\s*1\b"), "B uno"),
    (re.compile(r"\bµ\s?s\b"), "microsegundos"),
    (re.compile(r"(\d)\s*[×x]\s*(\d)"), r"\1 por \2"),
]

# Ruido tipográfico que no aporta a la escucha
_NOISE = re.compile(r"[\[\]•✓|▪◦]")

# Símbolos matemáticos/griegos → lectura en español (vía str.translate)
_SPEECH_CHAR_MAP = {
    "±": " más menos ",
    "≈": " aproximadamente ",
    "∼": " aproximadamente ",
    "=": " igual ",
    "<": " menor que ",
    ">": " mayor que ",
    "≤": " menor o igual ",
    "≥": " mayor o igual ",
    "+": " más ",
    "−": " menos ",
    "×": " por ",
    "∗": " estrella ",
    "µ": " micro ",
    "θ": " theta ",
    "ρ": " rho ",
    "σ": " sigma ",
    "π": " pi ",
    "∆": " delta ",
    "Δ": " delta ",
    "α": " alfa ",
    "β": " beta ",
    "γ": " gamma ",
    "λ": " lambda ",
    "ω": " omega ",
    "φ": " fi ",
    "τ": " tau ",
    "ε": " épsilon ",
}
_SPEECH_TABLE = str.maketrans(_SPEECH_CHAR_MAP)


def _fix_spoken_tokens(text: str) -> str:
    text = _NOISE.sub(" ", text)
    # tokens estructurales primero (necesitan los caracteres originales),
    # símbolos sueltos después
    for rx, repl in _SPOKEN_TOKENS:
        text = rx.sub(repl, text)
    text = text.replace("*", " ")  # asteriscos sueltos (viñetas rotas) fuera
    return text.translate(_SPEECH_TABLE)


def _spellout(acronym: str) -> str:
    return " ".join(ch.upper() for ch in acronym if ch.isalpha())


def expand_siglas(text: str, extra: dict[str, str] | None = None) -> str:
    """Expande siglas conocidas; deletrea las cortas desconocidas (≤4 letras)."""
    dic = dict(DEFAULT_SIGLAS)
    if extra:
        dic.update(extra)

    def repl(m: re.Match) -> str:
        token = m.group(0)
        if token in dic:
            return dic[token]
        if len(token) <= 4 and token.isalpha() and token.isupper():
            return _spellout(token)
        return token

    return re.sub(r"\b[A-ZÁÉÍÓÚÑ]{2,6}\b", repl, text)


def prepare_speech(text: str, extra_siglas: dict[str, str] | None = None) -> str:
    """Pipeline final antes del TTS: refs fuera, URLs fuera, notación técnica
    y siglas expandidas."""
    text = strip_bracket_refs(text)
    text = _URL_RE.sub(" ", text)
    text = _fix_spoken_tokens(text)
    text = expand_siglas(text, extra_siglas)
    text = _MULTI_PUNCT.sub(r"\1", text)
    return _WS_RE.sub(" ", text).strip()


class TranslationUnavailable(RuntimeError):
    """Argos Translate no está instalado (paquete opcional, ver requirements)."""


def translate(text: str, source: str, target: str, use_bonsai: bool = False) -> str:
    """Traduce un párrafo. Argos local (determinista) o Bonsai opcional.

    Lanza TranslationUnavailable si no hay ningún traductor.
    """
    if source == target:
        return text
    if use_bonsai:
        from wispertext.worker.bonsai import bonsai_translate

        out = bonsai_translate(text, target)
        if out:
            return out
        log.info("Bonsai no tradujo; caigo a Argos si existe")
    try:
        import argostranslate.translate as argos  # dependencia opcional

        return argos.translate(text, source, target)
    except ImportError as exc:
        raise TranslationUnavailable(
            "Argos Translate no instalado (pip install argostranslate + paquete "
            f"{source}→{target}) y Bonsai no disponible"
        ) from exc
