# Governance: inventory, access, provenance, licensing, retention

> Synthetic data — demonstration only. No real patient or student records. No compliance certification is
> claimed. A declaration of synthetic provenance is a workflow control, not a PHI detector.

## Data inventory
| Layer / schema | Contents | Sensitive fields | Who can read |
|---|---|---|---|
| Delivery folder (`data/deliveries`, git-ignored) | Synthea CSVs + manifest | Synthetic names, SSN-like strings, addresses in `patients.csv` | Operator workstation only |
| `raw` | Accepted source rows as text + locators | None of the direct identifiers (never loaded) | admin, loader, transformer |
| `ops.quarantine.payload` | Rejected rows' loaded fields | Clinical text | admin, loader, transformer; 30-day retention |
| `stg`, `int`, `seeds`, `work_*` | Typed/normalised candidates | Birth dates, source UUIDs (int/star only) | transformer (owner), publisher (read) |
| `star_rNNNN` / `star` | Published star schema | Birth date, source encounter id (protected analytical layer) | publisher only in P0 |
| `omop_rNNNN` / `omop` + `vocab` | Published scoped OMOP mart | Pseudonymous person source value only | publisher, omop_reader |
| `bi_rNNNN` / `bi` | Aggregate-ready cohort tables | Pseudonymous key, age at D, recorded demographics | publisher, bi_reader |

## Access matrix (least privilege, US-08)
| Role (group) | raw | ops | stg/int/work_* | star | omop + vocab | bi | DDL |
|---|---|---|---|---|---|---|---|
| `cwr_loader` | insert/select/delete* | batch audit insert | — | — | — | — | none |
| `cwr_transformer` | select | select; run/key/quality writes | owner | — | vocab select | — | own schemas, temp tables |
| `cwr_publisher` | — | select; release writes | select | owner | owner (views) | owner | create release schemas |
| `cwr_bi_reader` | **denied** | **denied** | **denied** | **denied** | **denied** | select | none |
| `cwr_omop_reader` | **denied** | **denied** | **denied** | **denied** | select | **denied** | none |

\* delete only within the loader's own batch transaction (duplicate-key quarantine). Login users are
NOINHERIT members that start sessions as their group role. Denials are proven by
`tests/integration/test_fixture_lifecycle.py::test_04*`.

## Credentials and network
- No credentials in Git: `.env` is ignored; `.env.example` carries placeholders that `doctor` rejects.
- Airflow reads credentials from environment-backed Connections (`AIRFLOW_CONN_CW_*`); the CLI from `CW_*`.
- Connection errors are reported with redacted DSNs. CI generates per-job passwords and masks them.
- Compose binds PostgreSQL and the Airflow API to `127.0.0.1` only; SCRAM-SHA-256 authentication.
- Host-level disk encryption (BitLocker/FileVault) is an operator prerequisite, recorded in the release checklist.
- TLS is required if a connection ever crosses the host boundary (out of P0 scope).
- `gitleaks` runs in CI.

## Provenance and licences
| Item | Source / licence | Record |
|---|---|---|
| Synthea generator | Apache-2.0, pinned release in `config/demo.yml` | generator block in every manifest |
| Fixture generator | this repository | `generator.name = cohortwarehouse-fixture-builder` |
| OMOP CDM DDL | OHDSI/CommonDataModel v5.4.2, Apache-2.0 | vendored, checksum-verified |
| OMOP vocabularies | OHDSI Athena; per-vocabulary licences (some require separate agreements) | `ops.vocabulary_release` (hashes, licence note); never committed |
| Fictional test vocabulary | this repository | marker file; `is_test_only = true` |

## Retention (project policy, not HIPAA retention claims)
- Raw rows and quarantine payloads: 30 days, except batches required to rebuild the current, previous or a
  report-pinned release, or the latest input state.
- Audit metadata (load attempts, alerts, quality results of unreleased runs): 90 days.
- Releases: current, previous and report-pinned are always kept.
- `python -m cohortwarehouse cleanup --dataset-id <id>` prints the plan; `--apply` executes it as admin.

## Real PHI (out of scope)
Real data requires separate institutional review before ingestion: authorised use, privacy/security risk
assessment, minimum-necessary access, IRB/research processes, approved hosting, BAAs where required, and a
disclosure/de-identification basis. Student health records additionally require an institutional HIPAA/FERPA
determination.
