"""Tests del normalizador (RF-03): acentos, ligaduras, guiones, mobiliario."""

from wispertext.worker.cleaning import (
    dehyphenate,
    find_repeated_furniture,
    fix_separated_accents,
    join_paragraph_lines,
    looks_like_junk,
    normalize_for_tts,
    paragraph_hash,
)


def test_acento_despues_de_vocal():
    assert fix_separated_accents("cafe´") == "café"
    assert fix_separated_accents("ra´ pido") != ""  # no explota con espacios


def test_acento_antes_de_vocal():
    assert fix_separated_accents("caf´e") == "café"
    assert fix_separated_accents("m´edico") == "médico"


def test_acento_con_espacio_intermedio():
    assert fix_separated_accents("cafe ´") == "café"


def test_ligaduras():
    assert normalize_for_tts("ﬁnanciaci´on ﬂuida") == "financiación fluida"


def test_dehifenizacion():
    assert dehyphenate("la infor-\nmación del estudio") == "la información del estudio"
    assert dehyphenate("el infor\u00ad\nmático") == "el informático"


def test_dehifenizacion_conserva_mayusculas():
    # la continuación en mayúscula no se une (rango "1990-\n1995")
    out = dehyphenate("entre 1990-\n1995 hubo")
    assert "1990- 1995" in out or "1990-\n1995" in out
    assert "19901995" not in out


def test_une_lineas_y_espacios():
    assert join_paragraph_lines("el   texto\n\n  sigue aquı   \n") == "el texto sigue aquı"


def test_normalizacion_tipograficos():
    out = normalize_for_tts("“cita”… y —guión– raro")
    assert '"' in out and "..." in out


def test_mobiliario_repetido():
    paginas = [["Norma Técnica 12", "3"], ["Norma Técnica 14", "7"], ["Norma Técnica 99", "9"]]
    furn = find_repeated_furniture(paginas, min_pages=3)
    # el número de página varía (→ #) y repite; el título también
    assert any("#" in f for f in furn)
    assert "norma técnica #" in furn


def test_junk():
    assert looks_like_junk("12")
    assert looks_like_junk("— — —")
    assert not looks_like_junk("Un párrafo normal con contenido.")


def test_hash_estable():
    h1 = paragraph_hash("texto", "es", "v1")
    h2 = paragraph_hash("texto", "es", "v1")
    h3 = paragraph_hash("texto ", "es", "v1")  # espacios bordes no importan
    h4 = paragraph_hash("texto", "en", "v1")
    assert h1 == h2 == h3
    assert h1 != h4


def test_acento_latex_dotless_i():
    # patrón real de main.pdf (LaTeX): ´ + ı sin punto
    assert normalize_for_tts("Metodolog´ıa de adquisici´on") == "Metodología de adquisición"
    assert normalize_for_tts("im´agenes") == "imágenes"
    assert normalize_for_tts("Ram´ırez") == "Ramírez"


def test_t2_star_partido_en_lineas():
    # LaTeX tipografía T2* como T / ∗ / 2 en líneas separadas
    assert normalize_for_tts("el T ∗\n2 de la m´edula") == "el T2∗ de la médula"
    assert normalize_for_tts("(T ∗\n2 < 1 ms)") == "(T2∗ < 1 ms)"
    assert normalize_for_tts("ca´ıda del T ∗ 2") == "caída del T2∗"


def test_virgulilla_latex():
    assert normalize_for_tts("la se˜nal dominante") == "la señal dominante"
    assert normalize_for_tts("espa˜nol") == "español"


def test_enfasis_markdown_fuera():
    assert normalize_for_tts("medida *in vivo* del hueso") == "medida in vivo del hueso"


def test_t2_subindice_perdido():
    # glifo matemático sin texto extraíble: el "2)" no existe en el PDF
    assert normalize_for_tts("(T ∗\nenfoque de UTE") == "(T2∗) enfoque de UTE"
    assert normalize_for_tts("el T ∗ del agua") == "el T2∗ del agua"
    # los correctos no se tocan
    assert normalize_for_tts("el T ∗\n2 de la médula") == "el T2∗ de la médula"
    assert normalize_for_tts("(T2∗) corto") == "(T2∗) corto"
