#!/usr/bin/env python3
"""Deterministic palette catalog validation and semantic selection."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


HEX_RE = re.compile(r"^#[0-9A-F]{6}$")
EXPECTED_COUNTS = {"categorical": 4, "sequential": 4, "diverging": 3, "highlight": 1, "neutral": 1}
CHART_TYPES = {"line", "scatter", "distribution", "bar", "heatmap", "tornado", "pareto", "gantt"}
ROLE_DEFAULTS = {
    "observed": "neutral_dark",
    "forecast": "primary",
    "baseline": "neutral",
    "front": "primary",
    "dominated": "neutral",
    "fit": "accent",
    "interval": "primary",
    "highlight": "highlight",
}
PREFERRED = {
    "categorical": "muted-editorial-v1",
    "sequential": "blue-teal-sun-v1",
    "diverging": "blue-cream-brick-v1",
    "highlight": "graphite-rose-focus-v1",
    "neutral": "charcoal-gray-v1",
}


class PaletteError(ValueError):
    """Raised for invalid input or an invalid catalog."""


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaletteError(f"cannot read catalog: {path}: {exc}") from exc
    validate_catalog(catalog)
    return catalog


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    def channel(value: str) -> float:
        value = int(value, 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(color: str) -> float:
        rgb = color[1:]
        return 0.2126 * channel(rgb[0:2]) + 0.7152 * channel(rgb[2:4]) + 0.0722 * channel(rgb[4:6])

    first, second = sorted((luminance(hex_a), luminance(hex_b)))
    return (second + 0.05) / (first + 0.05)


def validate_catalog(catalog: dict[str, Any]) -> None:
    if catalog.get("schema_version") != 1:
        raise PaletteError("catalog schema_version must be 1")
    palettes = catalog.get("palettes")
    if not isinstance(palettes, list) or len(palettes) != 13:
        raise PaletteError("catalog must contain exactly 13 palettes")
    ids: set[str] = set()
    counts = {kind: 0 for kind in EXPECTED_COUNTS}
    for palette in palettes:
        if not isinstance(palette, dict):
            raise PaletteError("each palette must be an object")
        palette_id = palette.get("id")
        kind = palette.get("kind")
        if not isinstance(palette_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", palette_id):
            raise PaletteError(f"invalid palette id: {palette_id!r}")
        if palette_id in ids:
            raise PaletteError(f"duplicate palette id: {palette_id}")
        ids.add(palette_id)
        if kind not in EXPECTED_COUNTS:
            raise PaletteError(f"invalid palette kind for {palette_id}: {kind!r}")
        counts[kind] += 1
        if palette.get("status") != "approved":
            raise PaletteError(f"runtime catalog contains non-approved palette: {palette_id}")
        colors = palette.get("colors")
        if not isinstance(colors, list) or not colors or len(colors) > 8:
            raise PaletteError(f"invalid colors for {palette_id}")
        if len(set(colors)) != len(colors) or any(not isinstance(c, str) or not HEX_RE.fullmatch(c) for c in colors):
            raise PaletteError(f"colors must be unique uppercase HEX values for {palette_id}")
        roles = palette.get("roles")
        if not isinstance(roles, dict) or any(not isinstance(c, str) or not HEX_RE.fullmatch(c) for c in roles.values()):
            raise PaletteError(f"invalid roles for {palette_id}")
        if palette.get("use_for") is None or not set(palette["use_for"]).issubset(CHART_TYPES):
            raise PaletteError(f"invalid use_for for {palette_id}")
        paper = roles.get("paper", "#FFFFFF")
        for role in ("text", "primary", "accent", "high", "highlight"):
            if role in roles and _contrast_ratio(roles[role], paper) < 3.0:
                raise PaletteError(f"role {role} has insufficient contrast in {palette_id}")
    if counts != EXPECTED_COUNTS:
        raise PaletteError(f"palette kind counts {counts} do not match {EXPECTED_COUNTS}")


def _kind_for(chart_type: str, scale_semantics: str | None) -> str:
    if chart_type not in CHART_TYPES:
        raise PaletteError(f"unknown chart type: {chart_type}")
    if scale_semantics:
        if scale_semantics not in {"categorical", "sequential", "diverging"}:
            raise PaletteError(f"unknown scale semantics: {scale_semantics}")
        return scale_semantics
    if chart_type == "heatmap":
        return "sequential"
    return "categorical"


def select_palette(
    catalog: dict[str, Any],
    *,
    chart_type: str,
    series_count: int,
    output_mode: str,
    roles: list[str] | None = None,
    scale_semantics: str | None = None,
    midpoint: str | None = None,
) -> dict[str, Any]:
    validate_catalog(catalog)
    if not isinstance(series_count, int) or series_count <= 0:
        raise PaletteError("series_count must be a positive integer")
    if output_mode not in {"screen", "print", "grayscale"}:
        raise PaletteError(f"unknown output mode: {output_mode}")
    kind = _kind_for(chart_type, scale_semantics)
    if kind == "diverging" and midpoint is None:
        raise PaletteError("diverging semantics requires midpoint")
    candidates = [p for p in catalog["palettes"] if p["kind"] == kind and chart_type in p["use_for"]]
    if not candidates:
        candidates = [p for p in catalog["palettes"] if p["kind"] == kind]
    preferred = PREFERRED[kind]
    candidates.sort(key=lambda p: (p["id"] != preferred, p["id"]))
    palette = candidates[0]
    warnings: list[str] = []
    secondary: list[str] = []
    if kind == "categorical" and series_count > 6:
        secondary = ["linestyle", "marker", "direct_label", "facet"]
        warnings.append("more than six series: use secondary encodings instead of adding colors")
    if output_mode == "grayscale":
        secondary = list(dict.fromkeys(["linestyle", "marker", "direct_label", *secondary]))
    role_map: dict[str, str] = {}
    for role in roles or []:
        role_name = ROLE_DEFAULTS.get(role, role)
        color = palette["roles"].get(role_name)
        if color is None:
            warnings.append(f"role {role!r} is not defined by {palette['id']}")
        else:
            role_map[role] = color
    colors = (
        palette["colors"][: min(series_count, len(palette["colors"]))]
        if kind == "categorical"
        else list(palette["colors"])
    )
    return {
        "palette_id": palette["id"],
        "colors": colors,
        "role_map": role_map,
        "secondary_encodings": secondary,
        "backend_status": {"matplotlib": "supported", "matlab": "supported", "origin": "validate-before-use"},
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).parents[1] / "references" / "palettes.json")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--chart-type", choices=sorted(CHART_TYPES))
    parser.add_argument("--series-count", type=int)
    parser.add_argument("--output-mode", choices=["screen", "print", "grayscale"])
    parser.add_argument("--roles", default="")
    parser.add_argument("--scale-semantics", choices=["categorical", "sequential", "diverging"])
    parser.add_argument("--midpoint")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.validate:
            print(json.dumps({"status": "ok", "catalog_id": catalog.get("catalog_id"), "palette_count": len(catalog["palettes"])}, ensure_ascii=False))
            return 0
        missing = [name for name in ("chart_type", "series_count", "output_mode") if getattr(args, name) is None]
        if missing:
            parser.error(f"missing required arguments: {', '.join(missing)}")
        result = select_palette(
            catalog,
            chart_type=args.chart_type,
            series_count=args.series_count,
            output_mode=args.output_mode,
            roles=[role for role in args.roles.split(",") if role],
            scale_semantics=args.scale_semantics,
            midpoint=args.midpoint,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except PaletteError as exc:
        print(f"palette error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
