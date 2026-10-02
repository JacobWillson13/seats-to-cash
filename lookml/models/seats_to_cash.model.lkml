# Seats-to-cash LookML model on the Snowflake build (connection name is set in Looker).
connection: "seats_to_cash_snowflake"

include: "/lookml/views/*.view.lkml"

explore: fct_arr_movements {
  label: "ARR movements"
  description: "ARR movements with each tailnet's month-end MRR; repricing is its own movement."

  join: fct_mrr_monthly {
    type: left_outer
    relationship: many_to_one
    sql_on: ${fct_arr_movements.tailnet_id} = ${fct_mrr_monthly.tailnet_id}
      AND ${fct_arr_movements.month_month} = ${fct_mrr_monthly.month_month} ;;
  }
}
