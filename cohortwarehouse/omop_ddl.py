"""Access to the pinned official OMOP CDM 5.4 PostgreSQL DDL (GOV-01).

Source: OHDSI/CommonDataModel tag v5.4.2, inst/ddl/5.4/postgresql/OMOPCDM_postgresql_5.4_ddl.sql
(Apache-2.0). The file is vendored unmodified; its SHA-256 is verified before use.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache

from cohortwarehouse.errors import ConfigurationError
from cohortwarehouse.settings import repo_root

DDL_RELATIVE_PATH = "sql/omop/OMOPCDM_postgresql_5.4_ddl.sql"
DDL_SHA256 = "ae99be6e79edfad5f17ef71edda176281b45e3aa9e400e7a9f829103f5ec4771"
CDM_VERSION = "5.4"
DDL_SOURCE = "OHDSI/CommonDataModel@v5.4.2"

VOCABULARY_TABLES = (
    "concept", "vocabulary", "domain", "concept_class", "concept_relationship",
    "relationship", "concept_synonym", "concept_ancestor", "source_to_concept_map", "drug_strength",
)

# Tables this project populates and tests (docs/omop-scope.md). Everything else in the DDL is
# structurally present but empty.
POPULATED_TABLES = (
    "person", "observation_period", "visit_occurrence", "condition_occurrence",
    "drug_exposure", "measurement", "observation", "death", "cdm_source",
)

_CREATE_RE = re.compile(r"CREATE TABLE @cdmDatabaseSchema\.(\w+)\s*\((.*?)\);", re.S | re.I)
_COLUMN_RE = re.compile(r'^\s*"?(\w+)"?\s+(.+?)\s+(NOT NULL|NULL)\s*$', re.I)


@dataclass(frozen=True)
class DdlColumn:
    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class DdlTable:
    name: str
    columns: tuple[DdlColumn, ...]
    statement: str

    def render(self, schema: str) -> str:
        return self.statement.replace("@cdmDatabaseSchema", f'"{schema}"')


@cache
def load_ddl() -> dict[str, DdlTable]:
    path = repo_root() / DDL_RELATIVE_PATH
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != DDL_SHA256:
        raise ConfigurationError(f"{DDL_RELATIVE_PATH} checksum {actual} does not match pinned {DDL_SHA256}")
    text = content.decode("utf-8")
    tables: dict[str, DdlTable] = {}
    for match in _CREATE_RE.finditer(text):
        name = match.group(1).lower()
        columns = []
        for line in match.group(2).split(","):
            col = _COLUMN_RE.match(line.strip())
            if not col:
                raise ConfigurationError(f"unparseable DDL column in {name}: {line!r}")
            columns.append(DdlColumn(col.group(1).lower(), col.group(2).lower(), col.group(3).upper() == "NULL"))
        tables[name] = DdlTable(name, tuple(columns), match.group(0))
    if "person" not in tables or "concept" not in tables:
        raise ConfigurationError("official DDL did not parse into expected tables")
    return tables


def clinical_tables() -> dict[str, DdlTable]:
    return {k: v for k, v in load_ddl().items() if k not in VOCABULARY_TABLES}
