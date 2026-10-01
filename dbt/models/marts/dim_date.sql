with dates as (
    select distinct date_local from {{ ref('fct_hourly_demand') }}
)

select
    date_local,
    extract(year from date_local)    as year,
    extract(month from date_local)   as month,
    monthname(date_local)            as month_name,
    dayname(date_local)              as day_name,
    extract(isodow from date_local) in (6, 7) as is_weekend,
    case
        when extract(month from date_local) in (12, 1, 2) then 'Winter'
        when extract(month from date_local) in (3, 4, 5)  then 'Spring'
        when extract(month from date_local) in (6, 7, 8)  then 'Summer'
        else 'Fall'
    end                              as season
from dates
