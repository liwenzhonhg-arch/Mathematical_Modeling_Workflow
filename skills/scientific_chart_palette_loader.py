"""Test-only loader for the hyphenated project skill path."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_palette_module():
    path = Path(__file__).resolve().parent / "scientific-chart-palette" / "scripts" / "select_palette.py"
    spec = spec_from_file_location("scientific_chart_palette_select", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
