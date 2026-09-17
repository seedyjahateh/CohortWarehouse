-- Section 8.4.4: when a content fingerprint is reused, the canonical content must be identical. Checked across
-- EVERY raw batch ever loaded (not just the selected revision), per file. Zero rows = pass.
{% set files = ['patients', 'encounters', 'conditions', 'medications', 'observations'] %}
{% for f in files %}
select '{{ f }}' as source_file, _row_fingerprint, count(distinct (
           to_jsonb(r) - '_dataset_id' - '_batch_id' - '_file_sha256' - '_record_number' - '_ingested_at'
           - '_row_fingerprint'
       )) as distinct_contents
from {{ source('raw', f) }} as r
group by _row_fingerprint
having count(distinct (
           to_jsonb(r) - '_dataset_id' - '_batch_id' - '_file_sha256' - '_record_number' - '_ingested_at'
           - '_row_fingerprint'
       )) > 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
