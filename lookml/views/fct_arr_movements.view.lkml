# ARR movements by tailnet, month, and type (dbt model marts.fct_arr_movements, ADR-007).
view: fct_arr_movements {
  sql_table_name: MARTS.FCT_ARR_MOVEMENTS ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: ${TABLE}.tailnet_id || '-' || CAST(${TABLE}.month AS VARCHAR) || '-' || ${TABLE}.movement_type ;;
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

  dimension: movement_type {
    type: string
    description: "new, expansion, repricing, contraction, churn, or reactivation."
    sql: ${TABLE}.movement_type ;;
  }

  dimension: is_repricing {
    type: yesno
    sql: ${TABLE}.movement_type = 'repricing' ;;
  }

  measure: arr_delta_usd {
    type: sum
    value_format_name: usd
    sql: ${TABLE}.arr_delta_usd ;;
  }

  measure: expansion_excluding_repricing_usd {
    type: sum
    value_format_name: usd
    sql: CASE WHEN ${TABLE}.movement_type = 'expansion' THEN ${TABLE}.arr_delta_usd ELSE 0 END ;;
  }

  measure: repricing_usd {
    type: sum
    value_format_name: usd
    sql: CASE WHEN ${TABLE}.movement_type = 'repricing' THEN ${TABLE}.arr_delta_usd ELSE 0 END ;;
  }
}
