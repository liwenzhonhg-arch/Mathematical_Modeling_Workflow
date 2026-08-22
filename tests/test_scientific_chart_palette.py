import json
import unittest
from pathlib import Path

from skills.scientific_chart_palette_loader import load_palette_module


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "skills" / "scientific-chart-palette" / "references" / "palettes.json"


class ScientificChartPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_palette_module()
        cls.catalog = cls.module.load_catalog(CATALOG)

    def test_catalog_has_thirteen_approved_palettes(self):
        self.assertEqual(len(self.catalog["palettes"]), 13)
        self.assertTrue(all(p["status"] == "approved" for p in self.catalog["palettes"]))

    def test_five_contract_examples_are_deterministic(self):
        cases = [
            {"chart_type": "line", "series_count": 2, "output_mode": "print", "roles": ["observed", "forecast"]},
            {"chart_type": "bar", "series_count": 3, "output_mode": "print", "roles": ["baseline"]},
            {"chart_type": "heatmap", "series_count": 1, "output_mode": "print", "scale_semantics": "sequential"},
            {"chart_type": "heatmap", "series_count": 1, "output_mode": "print", "scale_semantics": "diverging", "midpoint": "0"},
            {"chart_type": "gantt", "series_count": 4, "output_mode": "grayscale"},
        ]
        for case in cases:
            first = self.module.select_palette(self.catalog, **case)
            second = self.module.select_palette(self.catalog, **case)
            self.assertEqual(first, second)
            self.assertTrue(first["palette_id"])

    def test_more_than_six_series_uses_secondary_encoding(self):
        result = self.module.select_palette(self.catalog, chart_type="line", series_count=7, output_mode="screen")
        self.assertIn("linestyle", result["secondary_encodings"])
        self.assertTrue(result["warnings"])
        self.assertLessEqual(len(result["colors"]), 6)

    def test_continuous_curve_palette_is_available(self):
        result = self.module.select_palette(
            self.catalog,
            chart_type="line",
            series_count=1,
            output_mode="print",
            scale_semantics="sequential",
        )
        self.assertEqual(result["palette_id"], "blue-teal-sun-v1")
        self.assertEqual(result["colors"], ["#2F4B7C", "#2C7A8A", "#26A69A", "#A6C36F", "#B8791F"])

    def test_diverging_requires_midpoint(self):
        with self.assertRaises(self.module.PaletteError):
            self.module.select_palette(
                self.catalog,
                chart_type="heatmap",
                series_count=1,
                output_mode="print",
                scale_semantics="diverging",
            )


if __name__ == "__main__":
    unittest.main()
