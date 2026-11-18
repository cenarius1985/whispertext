"""Tests del re-render visual (docs/12): tablas aplanadas, matemática inline
y fallback determinista — sin red ni LLM."""

from wispertext.worker.render_md import (
    es_encabezado_tabla,
    es_fila_tabla,
    es_fragmento_matematico,
    fila_a_celdas,
    limpieza_determinista,
    matizar_inline,
    tabla_de_filas,
)


def test_es_fila_tabla():
    assert es_fila_tabla("Edad (años) 38.2 ± 12.6 51.8 ± 19.5 45.6 ± 17.8")
    assert es_fila_tabla("Rango 23-64 20-79 20-79")
    assert not es_fila_tabla("La fragilidad ósea depende de la calidad ósea.")
    assert not es_fila_tabla("El valor fue 38.2 ± 12.6 en total")  # un solo par


def test_es_encabezado_tabla():
    assert es_encabezado_tabla("(n = 10) (n = 12) (n = 22)")
    # el punto INTERNO de 'Ct.Th' es término científico, no fin de oración
    assert es_encabezado_tabla("Técnica BMD Ct.Th Ct.Po")
    assert not es_encabezado_tabla("Jean-Gabriel Minonzio4")
    assert not es_encabezado_tabla("Resultados.")


def test_es_fragmento_matematico():
    for frag in ("Z t1", "A(±)", "A(+)", "z = −A(−)", "TEn = TEmín", "TEmáx", "(5)"):
        assert es_fragmento_matematico(frag), frag
    assert not es_fragmento_matematico("Chile")
    assert not es_fragmento_matematico("La excitación selectiva de corte se describe")


def test_fila_a_celdas_separa_por_pares():
    celdas = fila_a_celdas("Edad (años) 38.2 ± 12.6 51.8 ± 19.5 45.6 ± 17.8")
    assert celdas == ["Edad (años)", "38.2 ± 12.6", "51.8 ± 19.5", "45.6 ± 17.8"]


def test_fila_a_celdas_simbolos_y_cabecera():
    # etiqueta multipalabra + símbolos: no partir 'MRI-UTE (0.55 T)' en 3
    assert fila_a_celdas("MRI-UTE (0.55 T) n/a ✓* △") == [
        "MRI-UTE (0.55 T)", "n/a", "✓*", "△",
    ]
    assert fila_a_celdas("µCT (ex vivo) n/a ✓ ✓") == ["µCT (ex vivo)", "n/a", "✓", "✓"]
    assert fila_a_celdas("(n = 10) (n = 12) (n = 22)") == ["", "(n = 10)", "(n = 12)", "(n = 22)"]


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
