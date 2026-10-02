"""Calibration report: monthly lifecycle counts and each planted mechanism (SPEC 4.3) measured
on the clean simulation next to its configured value. Ratios more than 25% off are flagged,
not tuned away."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from generator.lifecycle import State, Trigger
from generator.population import KIND_TRIAL

FLAG_TOLERANCE = 0.25


def _ci_ratio(ratio, se_log):
    if not np.isfinite(ratio) or ratio <= 0 or not np.isfinite(se_log):
        return "n/a"
    return f"{ratio * math.exp(-1.96 * se_log):.2f} to {ratio * math.exp(1.96 * se_log):.2f}"


def _flag(measured, configured):
    if not np.isfinite(measured):
        return "**FLAG** (no data)"
    off = measured / configured - 1
    return f"**FLAG** ({off:+.0%})" if abs(off) > FLAG_TOLERANCE else f"ok ({off:+.0%})"


def _rate_ratio(events, exposure):
    """Hazard ratio group 1 vs group 0 from event counts and exposure-days."""
    e1, e0 = int(events[1]), int(events[0])
    x1, x0 = int(exposure[1]), int(exposure[0])
    if min(e1, e0, x1, x0) == 0:
        return float("nan"), float("nan")
    return (e1 / x1) / (e0 / x0), math.sqrt(1 / e1 + 1 / e0)


def build_report(sim, devices, timings: dict[str, float], row_counts: dict[str, int]) -> str:
    cfg, cal, b, stats = sim.config, sim.cal, sim.b, sim.stats
    tr = sim.transitions.arrays()
    month = cal.month_of[np.minimum(tr["day"], cal.n_days - 1)]
    n_months = len(cal.months)

    def count(mask):
        return np.bincount(month[mask], minlength=n_months)

    trig = tr["trigger"]
    conv = trig == Trigger.TRIAL_CONVERT
    columns = {
        "personal signups": count(trig == Trigger.SIGNUP_PERSONAL),
        "business signups": count(trig == Trigger.SIGNUP_BUSINESS),
        "conv starter v3": count(conv & (tr["to_state"] == State.STARTER)),
        "conv premium v3": count(
            conv & (tr["to_state"] == State.PREMIUM) & (tr["to_version"] == 3)
        ),
        "conv standard v4": count(conv & (tr["to_state"] == State.STANDARD)),
        "conv premium v4": count(
            conv & (tr["to_state"] == State.PREMIUM) & (tr["to_version"] == 4)
        ),
        "paying business (month end)": stats.paying_month_end,
        "Personal Plus (month end)": stats.personal_plus_month_end,
        "voluntary churn": count(trig == Trigger.CHURN_VOLUNTARY),
        "involuntary churn": count(trig == Trigger.DUNNING_EXPIRED),
        "reactivations": count(trig == Trigger.REACTIVATION),
        "Personal Plus downgrades": count(
            np.isin(trig, [Trigger.PLUS_DOWNGRADE, Trigger.PLUS_RETIREMENT])
        ),
        "v4 migrations": count(trig == Trigger.MIGRATION_VOLUNTARY),
        "enterprise closes": count(
            np.isin(trig, [Trigger.ENTERPRISE_CLOSE, Trigger.SIGNUP_DIRECT_ENTERPRISE])
        ),
    }
    enterprise_close_count = int(
        np.sum(np.isin(trig, [Trigger.ENTERPRISE_CLOSE, Trigger.SIGNUP_DIRECT_ENTERPRISE]))
    )
    late_pipeline_count = int(
        np.sum((b.close_day > cal.n_days - 1) & (b.lead_day <= cal.n_days - 1))
    )
    lines = [
        "# Calibration report",
        "",
        f"Config seed {cfg.seed}, simulation {cfg.sim_start_date} to {cfg.end_date}. "
        "Measured on the clean simulation (no defects injected yet). "
        f"Ratios more than {FLAG_TOLERANCE:.0%} off their configured value are flagged, not tuned.",
        "",
        "## Monthly lifecycle",
        "",
        "| month | " + " | ".join(columns) + " |",
        "|---|" + "---:|" * len(columns),
    ]
    for m, name in enumerate(cal.months):
        lines.append(f"| {name} | " + " | ".join(str(int(v[m])) for v in columns.values()) + " |")
    totals = " | ".join("" if "month end" in k else str(int(v.sum())) for k, v in columns.items())
    lines.append(f"| **total** | {totals} |")

    # Planted mechanisms -------------------------------------------------------------------
    trials = np.flatnonzero((b.kind == KIND_TRIAL) & (b.created_day >= 0))
    btw = b.personal_first[trials]
    share = btw.mean()
    share_se = math.sqrt(share * (1 - share) / trials.size)

    ended = np.isin(trig, [Trigger.TRIAL_CONVERT, Trigger.TRIAL_FALLBACK]) & (tr["domain"] == 1)
    ended_tn, ended_conv = tr["tailnet"][ended], trig[ended] == Trigger.TRIAL_CONVERT
    pf = b.personal_first[ended_tn]
    k1, n1 = int(ended_conv[pf].sum()), int(pf.sum())
    k0, n0 = int(ended_conv[~pf].sum()), int((~pf).sum())
    conv_ratio = (k1 / n1) / (k0 / n0)
    conv_se = math.sqrt((1 - k1 / n1) / k1 + (1 - k0 / n0) / k0)

    churn_ratio, churn_se = _rate_ratio(
        stats.churn_event_count[:, 0], stats.churn_exposure_days[:, 0]
    )
    uplift_ratio, uplift_se = _rate_ratio(
        stats.churn_event_count[0, :], stats.churn_exposure_days[0, :]
    )
    removal_events = stats.removal_event_count.sum(axis=0)
    removal_exposure = stats.removal_exposure_days.sum(axis=0)
    removal_ratio, removal_se = _rate_ratio(removal_events, removal_exposure)
    std_ratio, std_se = _rate_ratio(
        stats.upgrade_event_count["standard"], stats.upgrade_exposure_days["standard"]
    )
    st_ratio, st_se = _rate_ratio(
        stats.upgrade_event_count["starter"], stats.upgrade_exposure_days["starter"]
    )
    pooled_upgrade_events = (
        stats.upgrade_event_count["standard"] + stats.upgrade_event_count["starter"]
    )
    pooled_upgrade_exposure = (
        stats.upgrade_exposure_days["standard"] + stats.upgrade_exposure_days["starter"]
    )
    pooled_ratio, pooled_se = _rate_ratio(pooled_upgrade_events, pooled_upgrade_exposure)
    machine_share, machine_n = _shared_machine_share(sim, devices)

    def sample(events, exposure):
        return (
            f"{int(events[1])} events / {int(exposure[1]):,} days vs "
            f"{int(events[0])} / {int(exposure[0]):,}"
        )

    rows = [
        (
            "Bring-to-work share of business creators",
            cfg.people.personal_first_share,
            share,
            f"{share - 1.96 * share_se:.3f} to {share + 1.96 * share_se:.3f}",
            f"{int(btw.sum())} of {trials.size} trials",
        ),
        (
            "Trial conversion, bring-to-work vs not",
            cfg.trial.bring_to_work_multiplier,
            conv_ratio,
            _ci_ratio(conv_ratio, conv_se),
            f"{k1}/{n1} ({k1 / n1:.1%}) vs {k0}/{n0} ({k0 / n0:.1%})",
        ),
        (
            "Voluntary churn hazard, low utilization vs not",
            cfg.seats.low_utilization_hazard_multiplier,
            churn_ratio,
            _ci_ratio(churn_ratio, churn_se),
            sample(stats.churn_event_count[:, 0], stats.churn_exposure_days[:, 0]),
        ),
        (
            "Seat-removal hazard, low utilization vs not",
            cfg.seats.low_utilization_hazard_multiplier,
            removal_ratio,
            _ci_ratio(removal_ratio, removal_se),
            sample(removal_events, removal_exposure),
        ),
        (
            "Pooled Starter/Standard-to-Premium upgrade, gated attempt vs not",
            cfg.upgrades.gated_feature_multiplier,
            pooled_ratio,
            _ci_ratio(pooled_ratio, pooled_se),
            sample(pooled_upgrade_events, pooled_upgrade_exposure),
        ),
        (
            "Standard-to-Premium upgrade, gated attempt vs not",
            cfg.upgrades.gated_feature_multiplier,
            std_ratio,
            _ci_ratio(std_ratio, std_se),
            sample(stats.upgrade_event_count["standard"], stats.upgrade_exposure_days["standard"]),
        ),
        (
            "Starter-to-Premium upgrade, gated attempt vs not (same mechanism, v3)",
            cfg.upgrades.gated_feature_multiplier,
            st_ratio,
            _ci_ratio(st_ratio, st_se),
            sample(stats.upgrade_event_count["starter"], stats.upgrade_exposure_days["starter"]),
        ),
        (
            "Voluntary churn hazard, high-uplift legacy vs not (repricing response)",
            cfg.migration.high_uplift_churn_multiplier,
            uplift_ratio,
            _ci_ratio(uplift_ratio, uplift_se),
            sample(stats.churn_event_count[0, :], stats.churn_exposure_days[0, :]),
        ),
        (
            "Personal-first creators with a shared machine key",
            cfg.people.same_machine_share,
            machine_share,
            "",
            f"{round(machine_share * machine_n)} of {machine_n} (from device_registrations)",
        ),
    ]
    lines += [
        "",
        "## Planted mechanisms",
        "",
        "Hazard ratios are events per exposure-day, group vs comparison group. Churn ratios "
        "hold the other multiplier at 1 (low utilization among non-high-uplift tailnets, and "
        "the reverse). 95% intervals use a log-normal approximation.",
        "",
        "| mechanism | configured | measured | 95% interval | check | sample |",
        "|---|---:|---:|---|---|---|",
    ]
    for name, configured, measured, ci, check_sample in rows:
        lines.append(
            f"| {name} | {configured:g} | {measured:.3f} | {ci} | "
            f"{_flag(measured, configured)} | {check_sample} |"
        )

    # Seats ---------------------------------------------------------------------------------
    deciles = np.arange(1, 10) / 10
    lines += ["", "## Seat utilization", ""]
    for label, parts in (
        ("Seat-based plans (occupied / held), paid tailnet-days", stats.utilization_seat),
        (
            "v3 per-active-user plans (30-day active / logged-in users), paid tailnet-days",
            stats.utilization_mau,
        ),
    ):
        values = np.concatenate(parts) if parts else np.zeros(0)
        lines.append(
            f"**{label}:** {values.size:,} tailnet-days; "
            f"{np.mean(values < cfg.seats.low_utilization_threshold):.1%} below "
            f"{cfg.seats.low_utilization_threshold:.0%}."
        )
        lines.append("")
        lines.append("| " + " | ".join(f"p{int(d * 100)}" for d in deciles) + " |")
        lines.append("|" + "---:|" * len(deciles))
        q = np.quantile(values, deciles) if values.size else [float("nan")] * 9
        lines.append("| " + " | ".join(f"{v:.2f}" for v in q) + " |")
        lines.append("")
    lines.append(
        f"Auto seats: {stats.auto_seat_tailnet_days:,} tailnet-days with an auto seat, "
        f"{stats.auto_seat_tailnet_days / max(stats.seat_tailnet_days, 1):.2%} of "
        f"{stats.seat_tailnet_days:,} live seat-based tailnet-days and "
        f"{stats.auto_seat_tailnet_days / max(stats.live_tailnet_days, 1):.2%} of all "
        f"{stats.live_tailnet_days:,} live business tailnet-days."
    )

    # Totals --------------------------------------------------------------------------------
    paid_states = [State.STARTER, State.STANDARD, State.PREMIUM, State.ENTERPRISE]
    business_paid = np.unique(
        tr["tailnet"][(tr["domain"] == 1) & np.isin(tr["to_state"], paid_states)]
    )
    business_paid = business_paid[b.kind[business_paid] != 1]
    plus_ever = np.unique(
        tr["tailnet"][(tr["domain"] == 0) & (tr["to_state"] == State.PERSONAL_PLUS)]
    )
    lines += [
        "",
        "## Totals",
        "",
        f"- Paying tailnets ever: {business_paid.size:,} business (SPEC 4.5: about 1,000) "
        f"plus {plus_ever.size:,} Personal Plus.",
        f"- Enterprise contracts closed: {enterprise_close_count} "
        f"(SPEC 4.5: about 60), with {int(np.sum(trig == Trigger.SIGNUP_ENTERPRISE_TAILNET))} "
        "extra tailnets for multi-tailnet contracts.",
        f"- Enterprise lead funnel: {int(b.lead.sum())} reached "
        f"{cfg.enterprise.lead_seat_threshold} seats; "
        f"{int(np.sum(b.close_day >= 0))} were selected to close at "
        f"{cfg.enterprise.lead_to_close:g}; "
        f"{late_pipeline_count} had close dates after "
        f"{cfg.end_date}; {int(np.sum(trig == Trigger.ENTERPRISE_CLOSE))} PLG and "
        f"{int(np.sum(trig == Trigger.SIGNUP_DIRECT_ENTERPRISE))} direct closed by the end.",
        f"- Business users created: {sim.users.n:,}.",
        "",
        "## Source and truth row counts",
        "",
        "| table | rows |",
        "|---|---:|",
        *[f"| {name} | {n:,} |" for name, n in row_counts.items()],
        "",
        "## Stage runtimes",
        "",
        "| stage | seconds |",
        "|---|---:|",
        *[f"| {name} | {sec:.2f} |" for name, sec in timings.items()],
        f"| **total** | {sum(timings.values()):.2f} |",
        "",
    ]
    return "\n".join(lines)


def _shared_machine_share(sim, devices) -> tuple[float, int]:
    """Share of bring-to-work creators whose business devices include a machine key from
    their personal tailnet, measured from the device registrations."""
    b, p = sim.b, sim.pop.personal
    linked = np.flatnonzero(b.personal_first & (b.kind == KIND_TRIAL) & (b.creator_user >= 0))
    if linked.size == 0:
        return float("nan"), 0
    personal_creator = np.flatnonzero(p.user_is_creator)
    by_user: dict[tuple[int, int], set[int]] = {}
    for dom, user, machine in zip(
        devices.domain.tolist(), devices.user.tolist(), devices.machine.tolist(), strict=True
    ):
        by_user.setdefault((dom, user), set()).add(machine)
    shared = 0
    for i in linked.tolist():
        business = by_user.get((1, int(b.creator_user[i])), set())
        personal = by_user.get((0, int(personal_creator[b.origin_personal[i]])), set())
        shared += bool(business & personal)
    return shared / linked.size, int(linked.size)


def write_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
