from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from PIL import Image

from god_bot.amedas import (
    AmedasError,
    _normalize_query,
    _point_in_geometry,
    render_amedas_image,
)


class AmedasTests(unittest.TestCase):
    def test_parses_region_and_element(self) -> None:
        self.assertEqual(
            _normalize_query("静岡県 降水"),
            ("静岡県", "precipitation1h", "1時間降水量", "mm"),
        )
        self.assertEqual(
            _normalize_query("東海"),
            ("東海", "temp", "気温", "℃"),
        )
        with self.assertRaises(AmedasError):
            _normalize_query("")

    def test_filters_points_by_geojson_boundary(self) -> None:
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [
                    [137.0, 34.0],
                    [139.0, 34.0],
                    [139.0, 36.0],
                    [137.0, 36.0],
                    [137.0, 34.0],
                ]
            ],
        }
        self.assertTrue(_point_in_geometry(35.0, 138.0, geometry))
        self.assertFalse(_point_in_geometry(36.5, 138.0, geometry))

    @patch("god_bot.amedas._make_basemap")
    def test_renders_station_values_to_png(self, make_basemap) -> None:
        make_basemap.return_value = (
            Image.new("RGB", (1000, 650), "white"),
            8,
            57700.0,
            25800.0,
            1.0,
            1.0,
        )
        # World-pixel offsets are chosen to land inside the test canvas.
        with patch(
            "god_bot.amedas._world_pixel",
            return_value=(58200.0, 26100.0),
        ):
            result = render_amedas_image(
                region_name="静岡県",
                bounds=(34.5, 35.7, 137.4, 139.0),
                observed_at=datetime(
                    2026, 7, 27, 22, 40, tzinfo=timezone.utc
                ),
                element_key="temp",
                element_label="気温",
                unit="℃",
                stations={
                    "50331": {
                        "lat": [34, 42.6],
                        "lon": [137, 43.8],
                        "kjName": "浜松",
                    }
                },
                observations={"50331": {"temp": [28.4, 0]}},
            )
        self.assertTrue(result.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.filename, "amedas_静岡県_temp.png")
        self.assertIn("1地点", result.caption)


if __name__ == "__main__":
    unittest.main()
