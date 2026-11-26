{#-
  SCD2 integrity: for each entity, validity windows must not overlap and must be ordered.
  An open-ended current row has valid_to = null.
-#}
{% test scd2_no_overlap(model, entity_column, valid_from_column, valid_to_column) %}
with ordered as (
    select
        {{ entity_column }} as entity,
        {{ valid_from_column }} as vf,
        coalesce({{ valid_to_column }}, cast('9999-12-31' as date)) as vt,
        lead({{ valid_from_column }}) over (
            partition by {{ entity_column }} order by {{ valid_from_column }}
        ) as next_vf
    from {{ model }}
)
select *
from ordered
where vt < vf                         -- window ends before it starts
   or (next_vf is not null and next_vf <= vt)   -- overlaps the next version
{% endtest %}
