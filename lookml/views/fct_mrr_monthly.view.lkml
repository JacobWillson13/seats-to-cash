# Month-end MRR and ARR per paid subscription (dbt model marts.fct_mrr_monthly).
view: fct_mrr_monthly {
  sql_table_name: MARTS.FCT_MRR_MONTHLY ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: ${TABLE}.tailnet_id || '-' || CAST(${TABLE}.month AS VARCHAR) ;;
  }

  dimension_group: month {
    type: time
    timeframes: [month, quarter, year]
    datatype: date
    convert_tz: no
    sql: ${TABLE}.month ;;
  }

  dimension: tailnet_id {
    type: string
    sql: ${TABLE}.tailnet_id ;;
  }

  dimension: subscription_id {
    type: string
    sql: ${TABLE}.subscription_id ;;
  }

  dimension: plan_code {
    type: string
    sql: ${TABLE}.plan_code ;;
  }

  dimension: price_version {
    type: string
    description: "v3 (legacy active-user pricing) or v4 (seat pricing)."
    sql: ${TABLE}.price_version ;;
  }

  dimension: billing_basis {
    type: string
    description: "mau (v3 active users), seat (v4 seats), or contract (Enterprise)."
    sql: ${TABLE}.billing_basis ;;
  }

  dimension: quantity {
    type: number
    description: "Billable active users, seats held, or contracted seats at month end."
    sql: ${TABLE}.quantity ;;
  }

  measure: mrr_usd {
    type: sum
    value_format_name: usd
    sql: ${TABLE}.mrr_usd ;;
  }

  measure: arr_usd {
    type: sum
    value_format_name: usd
    sql: ${TABLE}.arr_usd ;;
  }

  measure: paying_tailnets {
    type: count_distinct
    sql: CASE WHEN ${TABLE}.arr_usd > 0 THEN ${TABLE}.tailnet_id END ;;
  }
}
