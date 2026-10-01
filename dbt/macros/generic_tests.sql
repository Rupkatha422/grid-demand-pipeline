{% test accepted_range(model, column_name, min_value, max_value) %}
-- Fails for any non-null value outside [min_value, max_value].
select {{ column_name }}
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}


{% test unique_combination(model, columns) %}
-- Fails for any combination of columns that appears more than once.
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
