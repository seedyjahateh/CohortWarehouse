-- Section 8.4.4: when a content fingerprint is reused, the canonical content must be identical. Checked
-- across EVERY raw batch ever loaded, per file.
--
-- Two passes: first find fingerprints that actually repeat (a cheap grouped count), then compare canonical
-- content only inside those groups. Computing count(distinct content) over all rows cost 68s at 1.34M rows.
-- Zero rows = pass.
{% set files = ['patients', 'encounters', 'conditions', 'medications', 'observations'] %}
{% set payload %}
    to_jsonb(r) - '_dataset_id' - '_batch_id' - '_file_sha256' - '_record_number' - '_ingested_at'
    - '_row_fingerprint'
{% endset %}
{% for f in files %}
select '{{ f }}' as source_file, r._row_fingerprint, count(distinct ({{ payload }})) as distinct_contents
from {{ source('raw', f) }} as r
inner join (
    select _row_fingerprint as fp
    from {{ source('raw', f) }}
    group by _row_fingerprint
    having count(*) > 1
) as repeated on repeated.fp = r._row_fingerprint
group by r._row_fingerprint
having count(distinct ({{ payload }})) > 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
