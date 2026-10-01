select
    period_utc                                                         as hour_utc,
    -- Naive UTC -> Eastern local time (handles daylight saving automatically)
    (period_utc at time zone 'UTC') at time zone 'America/New_York'    as hour_local,
    respondent                                                         as balancing_authority,
    demand_mwh
from {{ source('raw', 'raw_demand') }}
