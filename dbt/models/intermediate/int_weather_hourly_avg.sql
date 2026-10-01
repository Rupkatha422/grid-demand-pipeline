-- Average temperature across the PJM cities for each UTC hour.
select
    hour_utc,
    avg(temperature_f) as avg_temperature_f,
    min(temperature_f) as min_temperature_f,
    max(temperature_f) as max_temperature_f,
    count(*)           as cities_reporting
from {{ ref('stg_weather') }}
group by hour_utc
