"""Tests del módulo de música de fondo (docs/11): validación de URL y
construcción del filtro de mezcla — sin red ni ffmpeg."""

from wispertext.worker.musica import DUCK, es_url_youtube, filtro_mezcla


def test_es_url_youtube_acepta_formatos_validos():
    assert es_url_youtube("https://www.youtube.com/watch?v=abc")
    assert es_url_youtube("https://youtube.com/watch?v=abc&list=xyz")
    assert es_url_youtube("https://music.youtube.com/playlist?list=xyz")
    assert es_url_youtube("https://youtu.be/abc123")
    assert es_url_youtube("http://www.youtube.com/watch?v=abc")


def test_es_url_youtube_rechaza_otros_dominios():
    assert not es_url_youtube("https://vimeo.com/12345")
    assert not es_url_youtube("https://evilo.com/youtube.com/watch?v=x")
    assert not es_url_youtube("file:///etc/passwd")
    assert not es_url_youtube("")
    assert not es_url_youtube("no una url")


def test_filtro_mezcla_parametrizado():
    f = filtro_mezcla(600.0, -15.0)
    # ducking con la voz como sidechain y mezcla que termina con la voz
    assert f"[mus][voz]sidechaincompress={DUCK}" in f
    assert "duration=first:normalize=0" in f
    assert "volume=-15.0dB" in f
    # fade out arranca en dur-6s para cerrar al final del audiolibro
    assert "afade=t=out:st=594.0:d=6.0" in f


def test_filtro_mezcla_fade_out_no_negativo():
    # audiolibro más corto que el fade: el fade arranca en 0, nunca negativo
    assert "afade=t=out:st=0.0" in filtro_mezcla(3.0, -10.0)
