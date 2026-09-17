-- Governance (Section 10, minimum necessary): nothing Power BI can import may carry names, government or
-- licence identifiers, addresses, coordinates, birth dates or source patient ids. Mirrors the Python gate's
-- denylist so the rule is enforced in both dbt and the release gate. Zero rows = pass.
-- depends_on: {{ ref('bi_patient_snapshot') }}
-- depends_on: {{ ref('bi_member_evidence') }}
-- depends_on: {{ ref('bi_release_status') }}
select table_name, column_name
from information_schema.columns
where table_schema = '{{ ref("bi_patient_snapshot").schema }}'
  and column_name ~ '(^|_)(first_name|last_name|middle_name|maiden_name|given_name|family_name|full_name|name|prefix|suffix|ssn|passport|drivers|license|address|street|zip|zipcode|postal_code|lat|lon|latitude|longitude|birth_date|birthdate|dob|patient_id|phone|email)($|_)'
  and column_name not in ('cohort_label', 'definition_label', 'month_label', 'reporting_label', 'organization_name')
