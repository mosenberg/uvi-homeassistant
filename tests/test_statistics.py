"""Regression tests for monthly statistics and historical corrections."""

from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "uvi_service"
package = types.ModuleType("uvi_statistics_test")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package


def load_module(name):
    spec = importlib.util.spec_from_file_location(f"{package.__name__}.{name}", PACKAGE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


data = load_module("statistics_data")


class MonthlyStatisticsTests(unittest.TestCase):
    def test_baseline_monthly_totals_and_dst(self):
        rows = {
            "2025-04-01": {"value": "2.200"},
            "2025-03-01": {"value": "1.100"},
            "2025-05-01": {"value": "0.000"},
        }
        stats = data.build_monthly_statistics(rows, "value", "Europe/Berlin")
        self.assertEqual([row["sum"] for row in stats], [0, 1.1, 3.3, 3.3])
        self.assertEqual(stats[0]["start"], datetime(1970, 1, 1, tzinfo=UTC))
        self.assertEqual(stats[1]["start"], datetime(2025, 2, 28, 23, tzinfo=UTC))
        self.assertEqual(stats[2]["start"], datetime(2025, 3, 31, 22, tzinfo=UTC))
        self.assertEqual(stats[3]["start"], datetime(2025, 4, 30, 22, tzinfo=UTC))

    def test_revised_month_recalculates_following_cumulative_values(self):
        rows = {"2025-01-01": {"value": "1"}, "2025-02-01": {"value": "3"}}
        before = data.build_monthly_statistics(rows, "value", "Europe/Berlin")
        rows["2025-01-01"]["value"] = "2"
        after = data.build_monthly_statistics(rows, "value", "Europe/Berlin")
        self.assertEqual([row["start"] for row in before], [row["start"] for row in after])
        self.assertEqual([row["sum"] for row in after], [0, 2, 5])

    def test_older_month_backfill_preserves_fixed_baseline(self):
        rows = {"2025-02-01": {"value": "3"}}
        before = data.build_monthly_statistics(rows, "value", "Europe/Berlin")
        rows["2025-01-01"] = {"value": "2"}
        after = data.build_monthly_statistics(rows, "value", "Europe/Berlin")
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[-1]["start"], after[-1]["start"])
        self.assertEqual(after[-1]["sum"], 5)

    def test_partial_updates_preserve_previously_known_values(self):
        existing = {"2025-01-01": {"month": "2025-01-01", "value": "3", "other": "2"}}
        merged = data.merge_monthly_records(existing, [
            {"month": "2025-01-01", "value": None, "other": "0"},
            {"month": "2025-02-01", "value": None},
        ])
        self.assertEqual(merged["2025-01-01"]["value"], "3")
        self.assertEqual(merged["2025-01-01"]["other"], "0")
        self.assertNotIn("value", merged["2025-02-01"])

    def test_missing_values_are_not_treated_as_zero(self):
        rows = {"2025-01-01": {"value": None}, "2025-02-01": {"value": "4"}}
        stats = data.build_monthly_statistics(rows, "value", "Europe/Berlin")
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats[-1]["sum"], 4)
        self.assertEqual(data.build_monthly_statistics(rows, "other", "Europe/Berlin"), [])

    def test_nonfinite_negative_and_nonmonthly_values_are_rejected(self):
        for month, value in (("2025-01-01", "NaN"), ("2025-01-01", "-1"),
                             ("2025-01-02", "1"), ("invalid", "1")):
            with self.subTest(month=month, value=value), self.assertRaises(ValueError):
                data.build_monthly_statistics({month: {"value": value}}, "value", "Europe/Berlin")

    def test_fractional_timezone_stays_in_reporting_month(self):
        rows = {"2025-01-01": {"value": "1"}}
        stats = data.build_monthly_statistics(rows, "value", "Asia/Kolkata")
        self.assertEqual(stats[-1]["start"], datetime(2024, 12, 31, 19, tzinfo=UTC))

    def test_imports_four_independent_idempotent_external_series(self):
        calls = []
        mock_modules = {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.components": types.ModuleType("homeassistant.components"),
            "homeassistant.components.recorder": types.ModuleType("homeassistant.components.recorder"),
            "homeassistant.components.recorder.models": types.SimpleNamespace(
                StatisticMeanType=types.SimpleNamespace(NONE=0)),
            "homeassistant.components.recorder.statistics": types.SimpleNamespace(
                async_add_external_statistics=lambda hass, metadata, rows: calls.append((metadata, rows))),
            "homeassistant.const": types.SimpleNamespace(
                UnitOfEnergy=types.SimpleNamespace(KILO_WATT_HOUR="kWh"),
                UnitOfVolume=types.SimpleNamespace(CUBIC_METERS="m³")),
            "homeassistant.util": types.ModuleType("homeassistant.util"),
            "homeassistant.util.unit_conversion": types.SimpleNamespace(
                EnergyConverter=types.SimpleNamespace(UNIT_CLASS="energy"),
                VolumeConverter=types.SimpleNamespace(UNIT_CLASS="volume")),
        }
        with patch.dict(sys.modules, mock_modules):
            stats_module = load_module("statistics")
            hass = types.SimpleNamespace(config=types.SimpleNamespace(time_zone="Europe/Berlin"))
            month = {"2025-01-01": {key: "2" for key in stats_module.SERIES}}
            stats_module.import_monthly_statistics(hass, "ABC123", month)
            stats_module.import_monthly_statistics(hass, "ABC123", month)
        self.assertEqual(len(calls), 8)
        self.assertEqual(calls[:4], calls[4:])
        self.assertEqual(len({metadata["statistic_id"] for metadata, _ in calls}), 4)
        for metadata, rows in calls:
            self.assertTrue(metadata["statistic_id"].startswith("uvi_service:abc123_"))
            self.assertEqual(metadata["source"], "uvi_service")
            self.assertEqual(rows[-1]["sum"], 2)


if __name__ == "__main__":
    unittest.main()
