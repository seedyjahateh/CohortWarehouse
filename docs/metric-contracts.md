# Metric contracts

Every Power BI measure (`bi/measures.dax`) has a definition, unit, filter contract and a matching SQL check.
Clinical rules are implemented and tested in dbt (`bi_cohort_membership`); DAX aggregates and displays.
All figures describe **synthetic records only — demonstration, not prevalence**.

Filter context used below: `:release` = the imported `bi_rNNNN` schema; demographic filters apply to
`bi_patient_snapshot` (age band, recorded sex, race, ethnicity, state); cohort selection applies to
`bi_cohort_definition`; month filters apply only to `bi_month` → `bi_cohort_month`.

| Measure | Definition | Unit | Filter contract | SQL check (same filters as `WHERE` on `s`) |
|---|---|---|---|---|
| Eligible Patients | Adults (completed years ≥ 18 at D), alive at end of D, ≥ 1 encounter in [D−364, D] | people | Demographic filters apply. Cohort and month selections do **not** change it (snapshot is the one side of all relationships). | `select count(*) from :release.bi_patient_snapshot s` |
| Cohort Patients | Distinct members of the selected cohort definition | people | Demographic filters apply through snapshot→membership. Returns 0, not blank, when empty. | `select count(distinct m.patient_key) from :release.bi_cohort_membership m join :release.bi_patient_snapshot s using (patient_key) where m.cohort_id = :cohort` |
| Cohort Share | Cohort Patients ÷ Eligible Patients under the **same** demographic filters | ratio (%) | Denominator uses identical demographic filters. Not prevalence. | ratio of the two queries above |
| Cohort Encounters | Distinct encounters starting in [D−364, D] for members | encounters | Requires exactly one cohort (blank otherwise). Month filter narrows to encounter-start months; membership and D do not change. | `select sum(encounter_count) from :release.bi_cohort_month c join :release.bi_patient_snapshot s using (patient_key) where c.cohort_id = :cohort [and c.month_key = :month]` |
| Mean Age in Cohort | Mean completed-years age at D of members | years | Demographic filters apply. | `select avg(s.age_at_as_of) from :release.bi_patient_snapshot s where s.patient_key in (select patient_key from :release.bi_cohort_membership where cohort_id = :cohort)` |
| Cohort Patients Missing Systolic | Members with **no valid** systolic (numeric, approved unit) in [D−89, D] | people | Demographic filters apply. "No valid measurement" ≠ "normal blood pressure". | `... where s.patient_key in (members) and not s.has_valid_recent_systolic` |
| Cohort Patients With Missing Systolic Values | Members with ≥ 1 systolic record in window whose value is empty | people | Demographic filters apply. Evidence of a missing value, not absence of a measurement. | `... and s.recent_systolic_missing_value_count > 0` |
| Unmapped Source Events | Retained-unmapped + routing-excluded source events | events | Not filtered by cohort or demographics (release-level quality). | `select sum(retained_unmapped_events + routing_excluded_events) from :release.bi_mapping_coverage where category <> 'cohort code sets'` |
| Imported Release | The single release id present in the import | text | Must show exactly one release; otherwise an explicit error string. | `select release_id from :release.bi_release_status` (exactly one row) |

## Acceptance scenarios (Section 11.4)

For each measure, compare the displayed value with the SQL above for at least these ten scenarios and record
results in `docs/evidence/bi-reconciliation.md` (created during the Power BI acceptance walkthrough):

1. C1, no filters  2. C2, no filters  3. C3, no filters  4. C1 × recorded sex = F  5. C2 × age band 45-64
6. C3 × ethnicity = hispanic (expected empty → count 0 and empty-state message)  7. C1 × race = black × age 18-29
8. C3 × month = latest month in window (encounters only change)  9. multi-select attempt → Cohort Encounters blank
10. Data trust page: Imported Release equals `ops.current_release` at refresh time.

On the fixture (release built from `fixture-C`), scenarios 1–3 must show 12 / 6 / 3 patients of 21 eligible.
