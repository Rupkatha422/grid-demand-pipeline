-- One row per UTC hour: PJM demand joined to average PJM-area temperature.
-- Weather lags real time by a few days, so the newest hours can have null temperature.
with demand as (
    select * from {{ ref('stg_demand') }}
),

weather as (
    select * from {{ ref('int_weather_hourly_avg') }}
)

select
    demand.hour_utc,
    demand.hour_local,
    cast(demand.hour_local as date)                       as date_local,
    extract(hour from demand.hour_local)                  as hour_of_day_local,
    demand.demand_mwh,
    weather.avg_temperature_f,
    weather.cities_reporting,
    -- Degree-hours (base 65°F): the standard way utilities measure heating and cooling need.
    greatest(weather.avg_temperature_f - 65, 0)           as cooling_degree_hours,
    greatest(65 - weather.avg_temperature_f, 0)           as heating_degree_hours
from demand
left join weather using (hour_utc)
