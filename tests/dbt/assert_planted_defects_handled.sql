-- Every planted defect that has manifest records is fully handled.
select * from {{ ref('audit_defect_scorecard') }}
where injected_records > 0 and not fully_handled
