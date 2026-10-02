"""Seats-to-cash demo report: a one-page Streamlit in Snowflake app (ADR-027).

Runs inside Snowflake: the session comes from get_active_session(), and the app uses only
streamlit, pandas, and altair, which Streamlit in Snowflake provides by default. Every query
reads SEATS_TO_CASH.MARTS or SEATS_TO_CASH.AUDIT by fully qualified name and reuses the logic
of analyses/dashboard/*.sql. Every query is cached with st.cache_data.
"""

from __future__ import annotations

import decimal

import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

DB = "SEATS_TO_CASH"
MARTS = f"{DB}.MARTS"
AUDIT = f"{DB}.AUDIT"
REPORTING_START = "2024-01-01"
YEAR_START = "2026-01-01"
BASELINE_MONTH = "2025-12-01"  # December 2025 closing ARR is the 2026 opening

# Reference categorical palette (light), validated in this order for adjacent marks.
# Repricing takes slot 2 (orange) so the price effect stands apart from volume movements.
MOVEMENT_COLORS = {
    "new": "#2a78d6",
    "repricing": "#eb6834",
    "expansion": "#1baf7a",
    "reactivation": "#eda100",
    "contraction": "#e87ba4",
    "churn": "#008300",
}
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]  # first three slots: safe for all pairs
SINGLE = "#2a78d6"
GRID = "#e6e5e1"

session = get_active_session()


def _frame(sql: str) -> pd.DataFrame:
    """Run SQL; lower-case the column names and turn Decimal columns into floats."""
    df = session.sql(sql).to_pandas()
    df.columns = [c.lower() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object and df[col].map(lambda v: isinstance(v, decimal.Decimal)).any():
            df[col] = pd.to_numeric(df[col])
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def arr_waterfall() -> pd.DataFrame:
    # analyses/dashboard/arr_waterfall.sql: opening + movements = closing per month.
    return _frame(f"""
        select month, opening_arr_usd, new_usd, expansion_usd, repricing_usd,
               contraction_usd, churn_usd, reactivation_usd, closing_arr_usd
        from {MARTS}.FCT_ARR_WATERFALL
        where month >= '{REPORTING_START}'
        order by month
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def arr_trend() -> pd.DataFrame:
    # analyses/dashboard/arr_trend.sql
    return _frame(f"""
        select month,
               sum(arr_usd) as arr_usd,
               count(distinct case when arr_usd > 0 then tailnet_id end) as paying_tailnets
        from {MARTS}.FCT_MRR_MONTHLY
        where month >= '{REPORTING_START}'
        group by month
        order by month
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def billings_revenue_cash() -> pd.DataFrame:
    # analyses/dashboard/billings_revenue_cash.sql
    return _frame(f"""
        select month, billings_usd, revenue_usd, net_cash_usd, refunds_usd, credit_notes_usd,
               fees_usd
        from {MARTS}.FCT_BILLINGS_REVENUE_CASH
        where month >= '{REPORTING_START}'
        order by month
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def deferred_revenue() -> pd.DataFrame:
    # analyses/dashboard/deferred_revenue.sql
    return _frame(f"""
        select month, opening_usd, billings_usd, revenue_usd, closing_usd,
               closing_usd = closing_check_usd as ties_out
        from {MARTS}.FCT_DEFERRED_REVENUE_ROLLFORWARD
        where month >= '{REPORTING_START}'
        order by month
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def migration_exposure() -> pd.DataFrame:
    # analyses/dashboard/migration_exposure.sql
    return _frame(f"""
        select migration_risk_tier,
               count(*) as tailnets,
               sum(legacy_mrr_usd) * 12 as legacy_arr_usd,
               sum(projected_v4_mrr_usd) * 12 as projected_v4_arr_usd,
               sum(arr_delta_usd) as arr_delta_usd
        from {MARTS}.FCT_MIGRATION_EXPOSURE
        group by migration_risk_tier
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def restatements() -> pd.DataFrame:
    # analyses/dashboard/restatements.sql
    return _frame(f"""
        select period, metric, closed_value_usd, current_value_usd, restatement_usd,
               late_refunds, late_credit_notes, reason
        from {MARTS}.FCT_RESTATEMENTS
        order by period, metric
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def defect_scorecard() -> pd.DataFrame:
    # analyses/dashboard/defect_scorecard.sql (defect rows)
    return _frame(f"""
        select defect_code, description, injected_records, detected_records,
               handled_records, fully_handled
        from {AUDIT}.AUDIT_DEFECT_SCORECARD
        order by defect_code
    """)


@st.cache_data(ttl=3600, show_spinner=False)
def answer_key_checks() -> pd.DataFrame:
    # analyses/dashboard/defect_scorecard.sql (answer-key rows)
    return _frame(f"""
        select 'MRR and ARR tailnet-months matching truth' as check_name,
               count(*) as checked,
               sum(case when status = 'match' then 1 else 0 end) as passed
        from {AUDIT}.AUDIT_MRR_VS_TRUTH
        union all
        select 'Revenue tailnet-months matching truth', count(*),
               sum(case when status = 'match' then 1 else 0 end)
        from {AUDIT}.AUDIT_REVENUE_VS_TRUTH
        union all
        select 'Tailnets with the true Stripe and Salesforce IDs', count(*),
               sum(case when is_match then 1 else 0 end)
        from {AUDIT}.AUDIT_IDENTITY_VS_TRUTH
    """)


def money(value: float) -> str:
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:,.2f}M"
    if value >= 10_000:
        return f"{sign}${value / 1_000:,.0f}K"
    return f"{sign}${value:,.0f}"


def themed(chart: alt.Chart, height: int = 280) -> alt.Chart:
    return (
        chart.properties(height=height)
        .configure_axis(
            gridColor=GRID,
            domainColor=GRID,
            tickColor=GRID,
            labelColor="#52514e",
            titleColor="#52514e",
        )  # fmt: skip
        .configure_view(strokeWidth=0)
        .configure_legend(orient="top", title=None, labelColor="#52514e")
    )


def month_axis(title: str | None = None) -> alt.X:
    return alt.X("month:T", title=title, axis=alt.Axis(format="%b %Y", labelAngle=0))


def usd_axis(field: str, title: str, **kwargs) -> alt.Y:
    return alt.Y(f"{field}:Q", title=title, axis=alt.Axis(format="$,.2~s"), **kwargs)


def table(df: pd.DataFrame, label: str = "Show data") -> None:
    with st.expander(label):
        st.dataframe(df, use_container_width=True, hide_index=True)


st.set_page_config(page_title="Seats to cash", layout="wide")

# 1. Title -------------------------------------------------------------------------------------
st.title("Seats to cash: Wirefern ARR, close, and data quality")
st.caption(
    "How much of ARR growth is real expansion and how much is repricing as legacy active-user "
    "plans move to seat plans, and whether billings, revenue, and cash tie out."
)

waterfall = arr_waterfall()
current = waterfall.iloc[-1]
baseline = waterfall.loc[waterfall["month"].astype(str) == BASELINE_MONTH, "closing_arr_usd"]
baseline_arr = (
    float(baseline.iloc[0]) if len(baseline) else float(waterfall.iloc[0]["opening_arr_usd"])
)
year = waterfall[waterfall["month"].astype(str) >= YEAR_START]
growth = float(current["closing_arr_usd"]) - baseline_arr
repricing_2026 = float(year["repricing_usd"].sum())
exposure = migration_exposure()
scorecard = defect_scorecard()
handled = int(scorecard["fully_handled"].fillna(False).astype(bool).sum())

# 2. KPI row -----------------------------------------------------------------------------------
current_month = pd.to_datetime(current["month"]).strftime("%b %Y")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric(f"ARR, {current_month}", money(float(current["closing_arr_usd"])))
k2.metric(
    "ARR growth since Dec 2025",
    money(growth),
    f"{growth / baseline_arr:+.1%}" if baseline_arr else None,
)
k3.metric(
    "Repricing share of 2026 growth",
    f"{repricing_2026 / growth:.1%}" if growth else "n/a",
    help="Repricing movements in 2026 divided by the change in ARR since December 2025.",
)
k4.metric(
    "Projected migration ARR change",
    money(float(exposure["arr_delta_usd"].sum())),
    help="Every legacy v3 tailnet moved to the matching v4 seat plan at today's usage.",
)
k5.metric("Defects handled", f"{handled} of {len(scorecard)}")

# 3. ARR trend and the 2026 waterfall ----------------------------------------------------------
st.subheader("ARR")
c1, c2 = st.columns(2)
with c1:
    trend = arr_trend()
    st.markdown("**Month-end ARR**")
    line = (
        alt.Chart(trend)
        .mark_line(color=SINGLE, strokeWidth=2, point=alt.OverlayMarkDef(size=30, color=SINGLE))
        .encode(
            x=month_axis(),
            y=usd_axis("arr_usd", "ARR"),
            tooltip=[
                alt.Tooltip("month:T", format="%b %Y", title="Month"),
                alt.Tooltip("arr_usd:Q", format="$,.2f", title="ARR"),
                alt.Tooltip("paying_tailnets:Q", format=",", title="Paying tailnets"),
            ],
        )
    )
    st.altair_chart(themed(line), use_container_width=True)
    table(trend)
with c2:
    st.markdown("**2026 ARR movements by type**")
    moves = year.melt(
        id_vars="month",
        value_vars=[f"{m}_usd" for m in MOVEMENT_COLORS],
        var_name="movement",
        value_name="arr_usd",
    )
    moves["movement"] = moves["movement"].str.removesuffix("_usd")
    moves["order"] = moves["movement"].map({m: i for i, m in enumerate(MOVEMENT_COLORS)})
    bars = (
        alt.Chart(moves)
        .mark_bar(size=18, stroke="#fcfcfb", strokeWidth=1)
        .encode(
            x=month_axis(),
            y=usd_axis("arr_usd", "ARR change", stack="zero"),
            color=alt.Color(
                "movement:N",
                scale=alt.Scale(domain=list(MOVEMENT_COLORS), range=list(MOVEMENT_COLORS.values())),
                sort=list(MOVEMENT_COLORS),
            ),
            order=alt.Order("order:Q"),
            tooltip=[
                alt.Tooltip("month:T", format="%b %Y", title="Month"),
                alt.Tooltip("movement:N", title="Movement"),
                alt.Tooltip("arr_usd:Q", format="$,.2f", title="ARR change"),
            ],
        )
    )
    st.altair_chart(themed(bars), use_container_width=True)
    table(year)

# 4. Billings, revenue, cash, and deferred revenue ---------------------------------------------
st.subheader("Billings, revenue, and cash")
c3, c4 = st.columns(2)
with c3:
    brc = billings_revenue_cash()
    st.markdown("**Billings vs. revenue vs. net cash, by month**")
    long = brc.melt(
        id_vars="month",
        value_vars=["billings_usd", "revenue_usd", "net_cash_usd"],
        var_name="measure",
        value_name="usd",
    )
    names = {"billings_usd": "Billings", "revenue_usd": "Revenue", "net_cash_usd": "Net cash"}
    long["measure"] = long["measure"].map(names)
    lines = (
        alt.Chart(long)
        .mark_line(strokeWidth=2)
        .encode(
            x=month_axis(),
            y=usd_axis("usd", "USD"),
            color=alt.Color(
                "measure:N", scale=alt.Scale(domain=list(names.values()), range=SERIES_COLORS)
            ),  # fmt: skip
            tooltip=[
                alt.Tooltip("month:T", format="%b %Y", title="Month"),
                alt.Tooltip("measure:N", title="Measure"),
                alt.Tooltip("usd:Q", format="$,.2f", title="USD"),
            ],
        )
    )
    st.altair_chart(themed(lines), use_container_width=True)
    table(brc)
with c4:
    deferred = deferred_revenue()
    st.markdown("**Deferred revenue balance at month end**")
    balance = (
        alt.Chart(deferred)
        .mark_line(color=SINGLE, strokeWidth=2)
        .encode(
            x=month_axis(),
            y=usd_axis("closing_usd", "Deferred revenue"),
            tooltip=[
                alt.Tooltip("month:T", format="%b %Y", title="Month"),
                alt.Tooltip("closing_usd:Q", format="$,.2f", title="Closing balance"),
                alt.Tooltip("ties_out:N", title="Rollforward ties"),
            ],
        )
    )
    st.altair_chart(themed(balance), use_container_width=True)
    table(deferred)

# 5. Migration exposure ------------------------------------------------------------------------
st.subheader("Legacy migration exposure")
tiers = ["high", "medium", "low"]
exposure["migration_risk_tier"] = pd.Categorical(exposure["migration_risk_tier"], tiers)
exposure = exposure.sort_values("migration_risk_tier")
c5, c6 = st.columns(2)
for column, field, title, fmt in (
    (c5, "tailnets", "Legacy tailnets by risk tier", ",d"),
    (c6, "arr_delta_usd", "Projected ARR change on v4 seats, by risk tier", "$,.2~s"),
):
    with column:
        st.markdown(f"**{title}**")
        chart = (
            alt.Chart(exposure)
            .mark_bar(color=SINGLE, cornerRadiusEnd=4, size=36)
            .encode(
                x=alt.X(
                    "migration_risk_tier:N",
                    sort=tiers,
                    title="Risk tier",
                    axis=alt.Axis(labelAngle=0),
                ),  # fmt: skip
                y=alt.Y(f"{field}:Q", title=None, axis=alt.Axis(format=fmt)),
                tooltip=[
                    alt.Tooltip("migration_risk_tier:N", title="Risk tier"),
                    alt.Tooltip("tailnets:Q", format=",", title="Tailnets"),
                    alt.Tooltip("legacy_arr_usd:Q", format="$,.0f", title="Legacy ARR"),
                    alt.Tooltip("projected_v4_arr_usd:Q", format="$,.0f", title="Projected v4 ARR"),
                    alt.Tooltip("arr_delta_usd:Q", format="$,.0f", title="ARR change"),
                ],
            )
        )
        st.altair_chart(themed(chart, height=240), use_container_width=True)
table(exposure.astype({"migration_risk_tier": str}))
st.caption(
    "Risk tier compares projected v4 MRR with legacy MRR. High: more than a 40% increase, or "
    "no legacy MRR today (three or fewer active users). Medium: more than 10%. Low: the rest."
)

# 6. Month-end close ---------------------------------------------------------------------------
st.subheader("Month-end close: restatements")
st.caption(
    "Closed figures that changed after the close, explained by refunds and credit notes "
    "loaded after it."
)
METRIC_NAMES = {
    "closing_arr_usd": "Closing ARR",
    "new_arr_usd": "New ARR",
    "expansion_arr_usd": "Expansion ARR",
    "repricing_arr_usd": "Repricing ARR",
    "contraction_arr_usd": "Contraction ARR",
    "churn_arr_usd": "Churned ARR",
    "reactivation_arr_usd": "Reactivated ARR",
    "billings_usd": "Billings",
    "recognized_revenue_usd": "Recognized revenue",
    "refunds_usd": "Refunds",
    "credit_notes_usd": "Credit notes",
    "revenue_usd": "Revenue",
    "net_cash_usd": "Net cash",
    "deferred_revenue_usd": "Deferred revenue",
}
restated = restatements()
if restated.empty:
    st.info("No restatements: run make close-history TARGET=snowflake to post the closes.")
else:
    view = restated.assign(metric=restated["metric"].map(METRIC_NAMES).fillna(restated["metric"]))
    st.dataframe(
        view.rename(
            columns={
                "period": "Period",
                "metric": "Metric",
                "closed_value_usd": "Closed value (USD)",
                "current_value_usd": "Current value (USD)",
                "restatement_usd": "Delta (USD)",
                "late_refunds": "Late refunds",
                "late_credit_notes": "Late credit notes",
                "reason": "Reason",
            }
        ),
        use_container_width=True,
        hide_index=True,
        height=36 * (len(view) + 1) + 3,  # every row visible, no inner scroll
        column_config={
            name: st.column_config.NumberColumn(name, format="%.2f")
            for name in ("Closed value (USD)", "Current value (USD)", "Delta (USD)")
        },
    )

# 7. Data quality ------------------------------------------------------------------------------
st.subheader("Data quality")
c7, c8 = st.columns(2)
with c7:
    st.markdown("**Planted defects**")
    st.dataframe(
        scorecard.rename(
            columns={
                "defect_code": "Code",
                "description": "Defect",
                "injected_records": "Injected",
                "detected_records": "Detected",
                "handled_records": "Handled",
                "fully_handled": "Fully handled",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
with c8:
    st.markdown("**Answer-key match rates**")
    checks = answer_key_checks()
    checks["match_rate"] = 100 * checks["passed"] / checks["checked"]
    st.dataframe(
        checks.rename(
            columns={
                "check_name": "Check",
                "checked": "Checked",
                "passed": "Matched",
                "match_rate": "Match rate",
            }
        ),  # fmt: skip
        use_container_width=True,
        hide_index=True,
        column_config={
            "Match rate": st.column_config.NumberColumn("Match rate", format="%.2f%%")
        },  # fmt: skip
    )

st.divider()
st.caption("Synthetic data. Pricing mechanics modeled on public information.")
