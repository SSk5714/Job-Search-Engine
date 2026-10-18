from datetime import UTC, datetime

import pytest

from jobpilot.domain.schedule import Cadence, describe, next_run, validate_cron


@pytest.mark.parametrize("cad,cron", [
    ({"kind": "off"}, None),
    ({"kind": "daily", "at": "07:30"}, "30 7 * * *"),
    ({"kind": "weekdays", "at": "08:00"}, "0 8 * * 1-5"),
    ({"kind": "weekly", "weekday": "sun", "at": "18:15"}, "15 18 * * 0"),
    ({"kind": "every_hours", "every_hours": 6, "at": "00:05"}, "5 */6 * * *"),
])
def test_presets_to_cron(cad, cron):
    assert Cadence(**cad).to_cron() == cron


def test_more_than_hourly_is_refused():
    with pytest.raises(ValueError, match="once an hour"):
        validate_cron("*/15 * * * *", "Europe/Berlin")
    with pytest.raises(ValueError):
        Cadence(kind="cron", cron="*/5 * * * *")


def test_invalid_cron_and_zone_are_refused():
    with pytest.raises(ValueError):
        Cadence(kind="cron", cron="61 * * * *")
    with pytest.raises(ValueError):
        Cadence(kind="daily", timezone="Mars/Olympus")


def test_next_run_is_local_time_across_daylight_saving():
    # 07:30 Berlin is 05:30 UTC in summer and 06:30 UTC in winter (DST ended 25 Oct 2026)
    before = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    assert next_run("30 7 * * *", "Europe/Berlin", before) == datetime(2026, 10, 25, 6, 30, tzinfo=UTC)
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert next_run("30 7 * * *", "Europe/Berlin", summer) == datetime(2026, 7, 2, 5, 30, tzinfo=UTC)


def test_describe():
    assert describe("30 7 * * 1-5", "Europe/Berlin") == "Weekdays at 07:30 (Europe/Berlin)"
    assert describe(None, "Europe/Berlin").startswith("Off")
