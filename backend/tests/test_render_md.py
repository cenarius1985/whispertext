"""Tests del re-render visual (docs/12): tablas aplanadas, matemática inline
y fallback determinista — sin red ni LLM."""

from wispertext.worker.render_md import (
    es_fila_tabla,
    fila_a_celdas,
    limpieza_determinista,
    matizar_inline,
    tabla_de_filas,
)


def test_es_fila_tabla():
    assert es_fila_tabla("Edad (años) 38.2 ± 12.6 51.8 ± 19.5 45.6 ± 17.8")
    assert es_fila_tabla("Peso (kg) 77.7 ± 8.3 73.3 ± 17.4")
    assert not es_fila_tabla("La fragilidad ósea depende de la calidad ósea.")
    assert not es_fila_tabla("El valor fue 38.2 ± 12.6 en total")  # un solo par


def test_fila_a_celdas_separa_por_pares():
    celdas = fila_a_celdas("Edad (años) 38.2 ± 12.6 51.8 ± 19.5 45.6 ± 17.8")
    assert celdas == ["Edad (años)", "38.2 ± 12.6", "51.8 ± 19.5", "45.6 ± 17.8"]


def test_tabla_de_filas_formato_markdown():
    md = tabla_de_filas(
        [
            "Edad (años) 38.2 ± 12.6 51.8 ± 19.5",
            "Peso (kg) 77.7 ± 8.3 73.3 ± 17.4",
        ]
    )
    lineas = md.split("\n")
    assert lineas[0].startswith("| Edad (años) |")
    assert lineas[1] == "|---|---|---|"
    assert "Peso (kg)" in lineas[2]


def test_matizar_inline_envuelve_simbolos_cientificos():
    assert "$T_2^{*}$" in matizar_inline("las componentes de T2∗ corta y larga")
    assert "$R_1$" in matizar_inline("el mapa de R1 cortical")
    # no duplica si el LLM ya puso matemática
    assert matizar_inline("ya con $T_2$ math") == "ya con $T_2$ math"


def test_limpieza_determinista_quita_pua():
    # caracteres de uso privado (Wingdings) no deben llegar al HTML
    assert "\uf0b7" not in limpieza_determinista("lista \uf0b7 ítem")
