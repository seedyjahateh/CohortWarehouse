import pytest

from cohortwarehouse.contract import REQUIRED_FILE_KEYS, Column, check_header, load_contract, validate_value
from cohortwarehouse.errors import ContractError


@pytest.fixture(scope="module")
def contract():
    return load_contract()


def test_contract_covers_required_files_and_never_loads_direct_identifiers(contract):
    assert set(REQUIRED_FILE_KEYS) <= set(contract.files)
    loaded = {c.name for f in contract.files.values() for c in f.loaded_columns}
    for identifier in ("SSN", "DRIVERS", "PASSPORT", "FIRST", "LAST", "MAIDEN", "ADDRESS", "LAT", "LON", "ZIP"):
        assert identifier not in loaded


def test_missing_required_header_fails(contract):
    header = [c.name for c in contract.files["conditions"].columns if c.name != "CODE"]
    with pytest.raises(ContractError, match="CODE"):
        check_header(contract.files["conditions"], header)


def test_duplicate_header_fails(contract):
    header = [c.name for c in contract.files["organizations"].columns] + ["NAME"]
    with pytest.raises(ContractError, match="duplicate"):
        check_header(contract.files["organizations"], header)


def test_extra_and_missing_optional_columns_are_recorded(contract):
    file_contract = contract.files["conditions"]
    header = [c.name for c in file_contract.columns if c.name != "SYSTEM"] + ["NEW_EXPORTER_COLUMN"]
    result = check_header(file_contract, header)
    assert result.extra_columns == ["NEW_EXPORTER_COLUMN"]
    assert result.missing_optional_columns == ["SYSTEM"]
    assert "SYSTEM" not in result.positions


@pytest.mark.parametrize(
    ("ctype", "nullable", "value", "reason"),
    [
        ("id", False, None, "null_required:X"),
        ("id", True, None, None),
        ("id", False, "has space", "invalid_id:X"),
        ("id", False, "00000000-0000-4000-8000-000000000001", None),
        ("date", False, "2026-02-30", "invalid_date:X"),
        ("date", False, "2026-02-28", None),
        ("date", False, "1700-01-01", "invalid_date:X"),
        ("timestamp", False, "2026-06-30T23:59:59Z", None),
        ("timestamp", False, "2026-06-20T06:00:00-04:00", None),
        ("timestamp", False, "2026-06-20T06:00:00", "invalid_timestamp:X"),  # offset required: no guessing zones
        ("timestamp", False, "not-a-date", "invalid_timestamp:X"),
        ("decimal", True, "abc", None),  # decimals are parsed (with status) in staging, not quarantined
    ],
)
def test_validate_value(ctype, nullable, value, reason):
    assert validate_value(Column("X", ctype, True, nullable, True), value) == reason
