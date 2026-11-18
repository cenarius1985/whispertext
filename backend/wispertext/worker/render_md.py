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
from wispertext.worker.bonsai import headers_auth

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


# ── Tablas aplanadas: detección determinista ─────────────────────────────────

_FILA_TABLA = re.compile(
    r"^\S.*?\s\d+[\.,]\d+\s*[±]\s*\d+[\.,]\d+(\s+\d+[\.,]\d*\s*[±]\s*\d+[\.,]\d+)+\s*$"
)
_FILA_RANGOS = re.compile(
    r"^\S.*?\s\d+\s*[-–]\s*\d+(\s+\d+\s*[-–]\s*\d+){1,}\s*$"
)
_N_ROW = re.compile(r"^(?:\(\s*n\s*=\s*\d+\s*\)\s*){2,}$")


def es_fila_tabla(texto: str) -> bool:
    t = texto.strip()
    return bool(_FILA_TABLA.match(t) or _FILA_RANGOS.match(t))


def es_fila_simbolos(texto: str) -> bool:
    """Filas tipo 'DXA ✓ △ n/a' (tablas de capacidades)."""
    t = texto.strip()
    return len(t) <= 80 and len(re.findall(r"✓\*?|△|n/a", t)) >= 2


def separar_filas_simbolos(texto: str) -> list[str]:
    """Un bloque puede traer dos filas pegadas: símbolo+mayúscula = corte."""
    return [r.strip() for r in re.split(r"(?<=[△✓])\s+(?=[A-Zµ])", texto.strip()) if r.strip()]


def es_encabezado_tabla(texto: str) -> bool:
    """'Característica Hombres Mujeres Total' o '(n = 10) (n = 12) (n = 22)'."""
    t = texto.strip()
    if _N_ROW.match(t):  # antes del guard de tokens: '(n = 10) …' son 9
        return True
    toks = t.split()
    if not (2 <= len(toks) <= 6) or len(t) > 60:
        return False
    # solo puntuación de ORACIÓN: los puntos internos ('Ct.Th', 'Ct.Po') son
    # términos científicos legítimos en cabeceras de tabla
    if re.search(r"[;:¿?¡!]|\.\s|\.$|,\s|,$", t):
        return False
    return all(
        re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ][\w\.\-]*", w) and not re.search(r"\d", w)
        for w in toks
    )


def fila_a_celdas(texto: str) -> list[str]:
    """'Edad (años) 38.2 ± 12.6 51.8 ± 19.5' → ['Edad (años)', '38.2 ± 12.6', …].

    Los valores llegan separados por espacios SIMPLES: se separan por el
    patrón «número ± número» (o «rango-rango» / «(n = N)»); el resto
    (cabeceras, filas de símbolos) se separa por espacios.
    """
    fila = texto.strip()
    ns = re.findall(r"\(\s*n\s*=\s*\d+\s*\)", fila)
    if len(ns) >= 2:
        return [""] + [n.strip() for n in ns]
    pares = re.findall(r"\d+[\.,]\d*\s*[±]\s*\d+[\.,]\d+", fila)
    if not pares:
        pares = re.findall(r"\d+\s*[-–]\s*\d+", fila)
    if pares:
        etiqueta = fila[: fila.index(pares[0])].strip(" ;:")
        return ([etiqueta] if etiqueta else []) + [p.strip() for p in pares]
    # filas de símbolos: 'MRI-UTE (0.55 T) n/a ✓* △' → etiqueta + símbolos
    simbolos = re.findall(r"✓\*?|△|n/a", fila)
    if len(simbolos) >= 2:
        etiqueta = fila[: fila.index(simbolos[0])].strip(" ;:")
        return ([etiqueta] if etiqueta else []) + simbolos
    return [c for c in fila.split() if c]


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

# ── Fragmentos matemáticos sueltos (alrededor de ecuaciones-imagen) ─────────

_COMUNES = {
    "de", "la", "el", "los", "las", "que", "con", "para", "por", "una", "un",
    "como", "donde", "este", "esta", "es", "son", "se", "en", "y", "o", "del",
    "al", "su", "sus", "fue", "más", "entre", "cada", "sobre", "según",
}
_MATH_CHARS = re.compile(r"[=±∗×·/+∑∫≤≥∝→−–∆∂πτµΔθλσ]")


def es_fragmento_matematico(texto: str) -> bool:
    """'Z t1', 'A(±)', 'z = −A(−)', 'TEn = TEmín', 'TEmáx': trozos de ecuación
    que el extractor separó en bloques propios. Se detectan por carecer de
    palabras de prosa y tener forma matemática."""
    t = texto.strip().rstrip(",;")
    if not t or len(t) > 60:
        return False
    toks = t.split()
    if len(toks) > 8:
        return False
    if re.fullmatch(r"\(\s*\d{1,3}\s*\)", t):  # nº de ecuación huérfano
        return True
    if any(w in _COMUNES for w in re.findall(r"[a-záéíóúñü]{2,}", t.lower())):
        return False
    if _MATH_CHARS.search(t):
        return True
    if len(toks) == 1:
        # t1, B1 (dígito) · TEmáx/TEn (mayúsculas interiores) — 'Chile' no
        return bool(
            re.search(r"\d", t)
            or (re.search(r"[A-Z].*[A-Z]", t) and re.search(r"[a-záéíóúñü]", t))
        )
    mathy = [
        w
        for w in toks
        if not re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúñü]+", w)  # 'Chile' no
        and re.fullmatch(r"[\w±∗×·/()=.,\-–−^_!]{1,10}", w)
    ]
    return len(mathy) >= max(2, len(toks) - 1)


def pasada_determinista(paragraphs) -> None:
    """Resuelve SIN LLM lo que se puede resolver a ciegas (docs/12):

    · ecuaciones → $$latex$$ o "" (la imagen contiene la fórmula)
    · tablas de símbolos (✓/△/n/a) → tabla Markdown (+ cabecera previa)
    · tablas de datos (A ± B) y de rangos → tabla Markdown (+ fila (n = …))
    · fragmentos matemáticos pegados a una ecuación → "" (absorbidos)
    Lo que queda en None va al LLM (preparar_bloques).
    """
    crudo_de = lambda p: (p.texto_normalizado or p.texto_original or "").strip()  # noqa: E731

    # 1) ecuaciones
    for p in paragraphs:
        if p.tipo == "ecuacion":
            p.texto_md = f"$${p.texto_latex}$$" if p.texto_latex else ""

    indices = {id(p): i for i, p in enumerate(paragraphs)}
    pag_ecuaciones = [i for i, p in enumerate(paragraphs) if p.tipo == "ecuacion"]

    # 2) tablas de símbolos: agrupar filas consecutivas (misma página, gap≤8)
    def grupo_desde(i: int, es_fila) -> list[int] | None:
        if not es_fila(crudo_de(paragraphs[i])) or paragraphs[i].texto_md is not None:
            return None
        g = [i]
        # busca la SIGUIENTE fila saltando bloques intercalados (PDF a dos
        # columnas mete prosa/fragmentos entre las filas de una tabla)
        j, prev = i + 1, i
        while j < len(paragraphs) and j - prev <= 8:
            q = paragraphs[j]
            if (
                q.pagina == paragraphs[prev].pagina
                and q.texto_md is None
                and es_fila(crudo_de(q))
            ):
                g.append(j)
                prev = j
            j += 1
        return g

    def cabecera_previa(i: int) -> int | None:
        """Bloque inmediatamente anterior que es cabecera de tabla."""
        if i == 0:
            return None
        prev = paragraphs[i - 1]
        if prev.texto_md is None and es_encabezado_tabla(crudo_de(prev)):
            return i - 1
        return None

    i = 0
    while i < len(paragraphs):
        for detector, splitter in ((es_fila_simbolos, separar_filas_simbolos), (es_fila_tabla, None)):
            g = grupo_desde(i, detector)
            if g and len(g) >= (2 if detector is es_fila_tabla else 1):
                filas: list[str] = []
                for k in g:
                    crudo = crudo_de(paragraphs[k])
                    filas.extend(splitter(crudo) if splitter else [crudo])
                h = cabecera_previa(g[0])
                if h is not None:
                    filas.insert(0, crudo_de(paragraphs[h]))
                    paragraphs[h].texto_md = ""
                paragraphs[g[0]].texto_md = tabla_de_filas(filas)
                for k in g[1:]:
                    paragraphs[k].texto_md = ""
                i = g[-1] + 1
                break
        else:
            i += 1
            continue
        continue

    # 3) fragmentos matemáticos cerca de una ecuación (misma página, ±8)
    for i, p in enumerate(paragraphs):
        if p.texto_md is not None:
            continue
        crudo = crudo_de(p)
        if crudo and es_fragmento_matematico(crudo) and any(
            abs(i - e) <= 8 and p.pagina == paragraphs[e].pagina
            for e in pag_ecuaciones
        ):
            p.texto_md = ""


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
                headers=headers_auth(),
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

    NO van: los ya resueltos por pasada_determinista (texto_md asignado).
    """
    bloques: list[tuple[str, str]] = []
    for p in paragraphs:
        if p.tipo == "ecuacion" or p.texto_md is not None:
            continue
        texto = (p.texto_normalizado or p.texto_original or "").strip()
        if not texto:
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
