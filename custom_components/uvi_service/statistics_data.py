"""Convert monthly consumption totals into cumulative hourly statistics."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import math
from zoneinfo import ZoneInfo

BASELINE = datetime(1970, 1, 1, tzinfo=UTC)


def merge_monthly_records(existing, rows):
    """Keep previously observed fields if the portal omits a value later."""
    result = dict(existing)
    for row in rows:
        previous = result.get(row["month"], {})
        result[row["month"]] = {
            **previous,
            **{key: value for key, value in row.items() if value is not None and value != ""},
        }
    return result


def build_monthly_statistics(months, field, timezone_name):
    """Place each month's total in its first complete UTC hour.

    Each row's sum is cumulative. A zero baseline allows the first month to be
    counted. No attempt is made to infer actual daily or hourly consumption.
    """
    timezone = ZoneInfo(timezone_name)
    result = []
    total = Decimal(0)
    for month, row in sorted(months.items()):
        raw = row.get(field)
        if raw is None or raw == "":
            continue
        try:
            value = Decimal(str(raw))
            day = date.fromisoformat(month)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Invalid monthly statistics data") from exc
        if day.day != 1 or not value.is_finite() or value < 0:
            raise ValueError("Invalid monthly statistics data")
        instant = datetime.combine(day, time.min, timezone).astimezone(UTC)
        if instant.minute or instant.second or instant.microsecond:
            instant = instant.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        if instant <= BASELINE:
            raise ValueError("Monthly statistics predate the fixed baseline")
        if not result:
            result.append({"start": BASELINE, "state": 0.0, "sum": 0.0})
        total += value
        amount = float(total)
        if not math.isfinite(amount):
            raise ValueError("Invalid monthly statistics data")
        result.append({"start": instant, "state": amount, "sum": amount})
    return result
