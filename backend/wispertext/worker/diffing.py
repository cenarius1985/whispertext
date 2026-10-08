"""Diff incremental de versiones por hash de párrafo (ADR-005, RF-11).

Módulo stdlib puro: alinea la secuencia de hashes de la versión anterior con
la nueva y clasifica cada párrafo nuevo en reutilizable / a sintetizar.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass
class DiffResult:
    reused: list[tuple[int, int]] = field(default_factory=list)  # (old_idx, new_idx)
    to_synth: list[int] = field(default_factory=list)  # índices nuevos a sintetizar
    removed: list[int] = field(default_factory=list)  # índices viejos eliminados

    @property
    def total_new(self) -> int:
        return len(self.reused) + len(self.to_synth)

    @property
    def ahorro(self) -> float:
        """Fracción de párrafos que NO requieren síntesis (0..1)."""
        total = self.total_new
        return (len(self.reused) / total) if total else 1.0


def align_versions(old_hashes: list[str], new_hashes: list[str]) -> DiffResult:
    """Alinea dos secuencias de hashes de párrafos.

    - 'equal' → reutilizable: el audio del párrafo viejo sirve al nuevo.
    - 'replace'/'insert' → a sintetizar.
    - 'delete' → eliminados en la nueva versión.
    """
    res = DiffResult()
    sm = SequenceMatcher(None, old_hashes, new_hashes, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                res.reused.append((i1 + k, j1 + k))
        elif tag in ("replace", "insert"):
            res.to_synth.extend(range(j1, j2))
        elif tag == "delete":
            res.removed.extend(range(i1, i2))
    return res
