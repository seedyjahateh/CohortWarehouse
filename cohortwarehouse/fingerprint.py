"""Canonical source-row serialization and SHA-256 fingerprints (Section 8.4, rules 3-4).

Format `sha256-canonical-v1`:

* Input is the file key followed by the contract's *loaded* columns, in contract order.
  Load metadata (batch, file order, ingestion time) is never part of the content.
* A NULL (blank CSV value) is written as the two characters ``\\N``.
* Non-null text is escaped: ``\\`` -> ``\\\\``, ``|`` -> ``\\|``, LF -> ``\\n``, CR -> ``\\r``.
  Because backslash is escaped first, a literal value ``\\N`` can never collide with NULL.
* Fields are joined with ``|`` and encoded as UTF-8 exactly as decoded from the CSV
  (no Unicode normalisation, no trimming).

Identical source rows produce identical fingerprints; multiplicity is preserved downstream
with an occurrence ordinal, never by collapsing duplicates.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

NULL_MARKER = "\\N"
FORMAT_VERSION = "sha256-canonical-v1"


def escape(value: str | None) -> str:
    if value is None:
        return NULL_MARKER
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n").replace("\r", "\\r")


def canonical_serialize(file_key: str, values: Sequence[str | None]) -> str:
    return "|".join([escape(file_key), *(escape(v) for v in values)])


def row_fingerprint(file_key: str, values: Sequence[str | None]) -> str:
    return hashlib.sha256(canonical_serialize(file_key, values).encode("utf-8")).hexdigest()


def file_sha256(path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
