select
    city,
    hour_utc,
    temperature_c,
    temperature_c * 9.0 / 5.0 + 32 as temperature_f
from {{ source('raw', 'raw_weather') }}
