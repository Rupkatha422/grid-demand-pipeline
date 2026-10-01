-- Returns one row per UTC hour missing between the first and last demand hour,
-- excluding documented source gaps in the known_demand_gaps seed.
-- A few new gaps only warn; a full day missing fails the build.
{{ config(severity='error', warn_if='>0', error_if='>24') }}

with bounds as (
    select min(hour_utc) as first_hour, max(hour_utc) as last_hour
    from {{ ref('stg_demand') }}
),

expected as (
    select unnest(generate_series(first_hour, last_hour, interval 1 hour)) as hour_utc
    from bounds
),

missing as (
    select expected.hour_utc
    from expected
    left join {{ ref('stg_demand') }} as actual using (hour_utc)
    where actual.hour_utc is null
)

select missing.hour_utc
from missing
where not exists (
    select 1 from {{ ref('known_demand_gaps') }} as gap
    where missing.hour_utc between gap.gap_start_utc and gap.gap_end_utc
)
