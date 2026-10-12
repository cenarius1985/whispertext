"""Runner simple sin pytest: python tests/run_all.py"""

import importlib
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

MODULOS = [
    "tests.test_cleaning",
    "tests.test_diffing",
    "tests.test_editorial",
    "tests.test_jobs",
    "tests.test_speakable",
    "tests.test_extractors",
    "tests.test_llm_runtime",
]


def main() -> int:
    total = fallos = 0
    for mod_name in MODULOS:
        mod = importlib.import_module(mod_name)
        for nombre in dir(mod):
            if nombre.startswith("test_"):
                fn = getattr(mod, nombre)
                total += 1
                try:
                    fn()
                    print(f"  ok  {mod_name}::{nombre}")
                except Exception:
                    fallos += 1
                    print(f"FAIL  {mod_name}::{nombre}")
                    traceback.print_exc()
    print(f"\n{total - fallos}/{total} tests OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
