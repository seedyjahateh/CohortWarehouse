import datetime as dt

import pytest

from cohortwarehouse.freshness import evaluate
from cohortwarehouse.omop_ddl import POPULATED_TABLES, VOCABULARY_TABLES, load_ddl

NOW = dt.datetime(2026, 9, 17, 6, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("age_hours", "status"),
    [(1, "pass"), (26, "pass"), (26.5, "warn"), (48, "warn"), (48.1, "fail")],
)
def test_scheduled_freshness_thresholds(age_hours, status):
    delivered = NOW - dt.timedelta(hours=age_hours)
    assert evaluate(delivered, now=NOW, mode="scheduled", warn_hours=26, error_hours=48)["status"] == status


def test_frozen_demo_is_labelled_not_called_fresh():
    report = evaluate(NOW - dt.timedelta(days=90), now=NOW, mode="frozen_demo", warn_hours=26, error_hours=48)
    assert report["status"] == "pass"
    assert "FROZEN DEMO" in report["label"]


def test_no_delivery_fails():
    assert evaluate(None, now=NOW, mode="scheduled", warn_hours=26, error_hours=48)["status"] == "fail"


def test_pinned_official_ddl_parses_with_expected_tables():
    ddl = load_ddl()
    for table in (*POPULATED_TABLES, *VOCABULARY_TABLES):
        assert table in ddl, table
    person = {c.name: c for c in ddl["person"].columns}
    assert person["person_id"].data_type == "integer" and not person["person_id"].nullable
    assert person["person_source_value"].data_type == "varchar(50)"
