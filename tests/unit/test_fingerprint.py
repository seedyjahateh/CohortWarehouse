import hashlib

from cohortwarehouse.fingerprint import NULL_MARKER, canonical_serialize, escape, row_fingerprint


def test_null_is_distinct_from_literal_null_marker_and_empty_string():
    assert escape(None) == NULL_MARKER
    assert escape("\\N") != NULL_MARKER
    assert row_fingerprint("f", [None]) != row_fingerprint("f", ["\\N"])
    assert row_fingerprint("f", [None]) != row_fingerprint("f", [""])


def test_delimiters_inside_values_cannot_shift_fields():
    # ["a|b", "c"] and ["a", "b|c"] would collide without escaping.
    assert row_fingerprint("f", ["a|b", "c"]) != row_fingerprint("f", ["a", "b|c"])
    assert row_fingerprint("f", ["a\\", "|b"]) != row_fingerprint("f", ["a\\|", "b"])


def test_newlines_and_unicode_are_preserved_exactly():
    value = 'Former smoker, "quit"\nsee note – Ångström'
    serial = canonical_serialize("observations", [value])
    assert "\n" not in serial
    assert "Ångström" in serial
    assert row_fingerprint("observations", [value]) != row_fingerprint("observations", [value.replace("\n", " ")])


def test_file_key_is_part_of_identity():
    assert row_fingerprint("conditions", ["x"]) != row_fingerprint("medications", ["x"])


def test_format_is_stable():
    # Guards against accidental format drift: changing the canonical form changes every event identity.
    expected = hashlib.sha256(b"conditions|2026-01-01|\\N|a\\|b").hexdigest()
    assert row_fingerprint("conditions", ["2026-01-01", None, "a|b"]) == expected
