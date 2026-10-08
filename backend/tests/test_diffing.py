"""Tests del diff incremental de versiones (RF-11 / ADR-005)."""

from wispertext.worker.diffing import align_versions


def h(i: str) -> str:
    return i


def test_reemplazo_pequeno_reutiliza_la_mayoria():
    old = [h(f"p{i}") for i in range(100)]
    new = list(old)
    new[10] = "CAMBIADO"
    new[50] = "OTRO"
    new.insert(80, "NUEVO")
    diff = align_versions(old, new)
    assert len(diff.to_synth) == 3          # 2 cambiados + 1 insertado
    assert len(diff.reused) == 98           # 100 - 2 cambiados
    assert diff.ahorro > 0.95


def test_documento_identicoo():
    old = ["a", "b", "c"]
    diff = align_versions(old, list(old))
    assert diff.to_synth == []
    assert diff.removed == []
    assert diff.ahorro == 1.0


def test_eliminaciones_y_agrupados():
    old = ["a", "b", "c", "d", "e"]
    new = ["a", "c", "e", "f"]
    diff = align_versions(old, new)
    assert set(diff.removed) == {1, 3}
    assert diff.to_synth == [3]  # "f" entra como insert
    # a, c, e reutilizados en su posición nueva
    assert sorted(diff.reused) == [(0, 0), (2, 1), (4, 2)]


def test_indices_de_reused_apuntan_a_listas_correctas():
    old = ["x1", "x2", "x3"]
    new = ["x1", "x3"]
    diff = align_versions(old, new)
    for old_idx, new_idx in diff.reused:
        assert old[old_idx] == new[new_idx]
