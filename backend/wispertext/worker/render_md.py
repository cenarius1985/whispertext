"""Re-render visual con LLM: texto crudo de PDF → Markdown con LaTeX (docs/12).

El lector sincroniza párrafo ↔ audio, así que la unidad sigue siendo el
PÁRRAFO: este módulo produce ``Paragraph.texto_md`` (presentación) sin tocar
texto_original/hablado ni el orden. El LLM configurado (GLM por defecto hoy)
recibe lotes de bloques consecutivos —el contexto del lote permite juntar
tablas y fórmulas partidas entre bloques— y devuelve un JSON {id: markdown}.

Fail-soft por bloque: lo que el LLM no devuelve cae al limpiador determinista
(ligaduras + acentos separados + caracteres de uso privado). El trabajo nunca
pierde contenido por un lote fallido.
"""

import json
import logging
import re

import httpx

from wispertext.config import get_settings
from wispertext.llm_runtime import get_llm_config
from wispertext.worker import cleaning

log = logging.getLogger("wispertext.render_md")

LOTE_MAX_BLOQUES = 12
LOTE_MAX_CHARS = 6000

# caracteres de uso privado (Wingdings/Symbol) y basura de extracción
_PUA = re.compile(r"[\ue000-\uf8ff\uf000]")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

PROMPT = """Recibes bloques consecutivos extraídos de un PDF científico (pueden \
tener caracteres corruptos por mala codificación de fuentes). Para CADA bloque \
devuelve su versión limpiada en Markdown para mostrar en HTML.

Reglas estrictas:
- NO resumas, NO traduzcas, NO inventes contenido: solo limpia y formatea.
- Corrige caracteres corruptos según contexto (p. ej. "¾sea" → "ósea").
- MATEMÁTICA SIEMPRE EN LATEX inline $...$ con subíndices _ y superíndices ^: \
"T2∗" → $T_2^*$, "R1" → $R_1$, "B1" → $B_1$, "M⊥(z) ∝" → $M_\\perp(z) \\pro$, \
"10×10 mm" → $10\\times10$ mm. Ecuación destacada: línea propia $$...$$.
- TABLAS: si varios bloques (aunque haya otros intercalados) son filas de una \
misma tabla de datos, devuelve la tabla Markdown COMPLETA en el PRIMERO y "" \
en los demás. Ejemplo:
  entrada: "Edad (años) 38.2 ± 12.6 51.8 ± 19.5" y "Peso (kg) 77.7 ± 8.3 ..."
  salida:  "| Medida | Grupo A | Grupo B |\\n|---|---|---|\\n| Edad (años) | $38.2\\pm12.6$ | $51.8\\pm19.5$ | ..." y ""
- Si un bloque es solo un número de ecuación huérfano o basura sin sentido \
(p. ej. "(3)"), devuelve "".
- Usa **negrita**, *cursiva*, listas y ### subtítulos cuando ayuden.
- NO uses bloques de código ni ``` .

Responde SOLO un objeto JSON que mapee el id de cada bloque a su Markdown:
{"17": "texto...", "18": "| Col | Val |\\n|---|---|\\n..."}
Bloques:
"""


# ── Tablas aplanadas: detección determinista (filas "X (un) A ± B C ± D") ────

_FILA_TABLA = re.compile(
    r"^\S.*?\s\d+[\.,]\d+\s*[±]\s*\d+[\.,]\d+(\s+\d+[\.,]\d*\s*[±]\s*\d+[\.,]\d+)+\s*$"
)


def es_fila_tabla(texto: str) -> bool:
    return bool(_FILA_TABLA.match(texto.strip()))


def fila_a_celdas(texto: str) -> list[str]:
    """'Edad (años) 38.2 ± 12.6 51.8 ± 19.5' → ['Edad (años)', '38.2 ± 12.6', …].

    Los valores llegan separados por espacios SIMPLES: se separan por el
    patrón «número ± número» en vez de por columnas de espacios.
    """
    fila = texto.strip()
    pares = re.findall(r"\d+[\.,]\d*\s*[±]\s*\d+[\.,]\d+", fila)
    if not pares:
        return [c.strip() for c in re.split(r"\s{2,}", fila) if c.strip()]
    etiqueta = fila[: fila.index(pares[0])].strip(" ;:")
    return ([etiqueta] if etiqueta else []) + [p.strip() for p in pares]


def tabla_de_filas(filas: list[str]) -> str:
    """Filas crudas → tabla Markdown (1ª fila como encabezado)."""
    celdas = [fila_a_celdas(f) for f in filas]
    ancho = max(len(c) for c in celdas)
    for c in celdas:
        c += [""] * (ancho - len(c))
    sep = "|" + "---|" * ancho
    head = "| " + " | ".join(celdas[0]) + " |"
    cuerpo = "\n".join("| " + " | ".join(c) + " |" for c in celdas[1:])
    return cuerpo and f"{head}\n{sep}\n{cuerpo}" or f"{head}\n{sep}"


# ── Matemática inline determinista (post-toque al output del LLM) ───────────
# El LLM no siempre envuelve; estos tokens científicos son unívocos.
_SIMB_SUBSUP = re.compile(r"\b([TRBMSEFW])(\d)\s?([∗*])")
_SIMB_SUB = re.compile(r"\b([TRBMSEFW])(\d)\b")


def matizar_inline(md: str) -> str:
    if "$" in md:  # el LLM ya matizó esta zona: no duplicar
        return md

    def sub_simsup(m: re.Match) -> str:
        return "$" + m.group(1) + "_" + m.group(2) + "^{*}$"

    md = _SIMB_SUBSUP.sub(sub_simsup, md)

    def sub_sub(m: re.Match) -> str:
        return "$" + m.group(1) + "_" + m.group(2) + "$"

    return _SIMB_SUB.sub(sub_sub, md)


def limpieza_determinista(texto: str) -> str:
    """Fallback sin LLM: arreglos conocidos + fuera PUA. Nunca lanza."""
    try:
        t = cleaning.fix_ligatures(texto)
        t = cleaning.fix_separated_accents(t)
        return _PUA.sub("", t).strip()
    except Exception:  # noqa: BLE001 — presentación, no puede tumbar el job
        return texto


def _bloques_a_prompt(bloques: list[tuple[int, str]]) -> str:
    cuerpo = "\n".join(f"[{bid}] {texto[:1200]}" for bid, texto in bloques)
    return PROMPT + cuerpo + "\n\nJSON:"


def _llm_markdown(bloques: list[tuple[str, str]]) -> dict[str, str] | None:
    """Un lote → {id: markdown}. None si el LLM no respondió nada usable."""
    settings = get_settings()
    cfg = get_llm_config()
    if not cfg["enabled"]:
        return None
    prompt = _bloques_a_prompt(bloques)
    for intento in (1, 2):  # 1 reintento: lotes con tablas pueden tardar
        try:
            resp = httpx.post(
                f"{cfg['base_url']}/chat/completions",
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
                timeout=settings.render_llm_timeout_s,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"] or ""
            m = _JSON_RE.search(raw)
            if not m:
                raise ValueError("respuesta sin JSON")
            datos = json.loads(m.group(0))
            if not isinstance(datos, dict):
                raise ValueError("JSON no es objeto")
            salida = {
                bid: val.strip()
                for bid, _ in bloques
                if isinstance(val := datos.get(bid), str)
            }
            return salida or None
        except Exception as exc:  # noqa: BLE001 — fail-soft por lote
            log.warning("render_md lote falló (intento %d): %s", intento, exc)
    return None


def preparar_bloques(paragraphs) -> list[tuple[str, str]]:
    """(str(p.id), texto_a_limpiar) de los bloques que van al LLM, en orden.

    NO van: ecuaciones (imagen/LaTeX ya resueltos por el job) ni filas de
    tabla detectadas deterministamente (agrupadas por el job).
    """
    bloques: list[tuple[str, str]] = []
    for p in paragraphs:
        if p.tipo == "ecuacion":
            continue
        texto = (p.texto_normalizado or p.texto_original or "").strip()
        if not texto or es_fila_tabla(texto):
            continue
        bloques.append((str(p.id), texto))
    return bloques


def lotes(bloques: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Agrupa consecutivos respetando los dos topes del lote."""
    out: list[list[tuple[str, str]]] = []
    actual: list[tuple[str, str]] = []
    chars = 0
    for b in bloques:
        if actual and (len(actual) >= LOTE_MAX_BLOQUES or chars + len(b[1]) > LOTE_MAX_CHARS):
            out.append(actual)
            actual, chars = [], 0
        actual.append(b)
        chars += len(b[1])
    if actual:
        out.append(actual)
    return out
