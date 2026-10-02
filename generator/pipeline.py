"""Run the generator stages in order, timing each one."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from generator import (
    app_db,
    billing_orb,
    billing_stripe,
    calibration,
    emit,
    salesforce_enterprise,
    truth,
)
from generator import defects as defects_module
from generator.activity import Devices, PersonalActivity, device_registrations, personal_monthly
from generator.clock import Calendar
from generator.config import SimulationConfig
from generator.population import build_population
from generator.reference import Seeds
from generator.simulate import Simulation
from generator.tables import APP_TABLES, ORB_TABLES, SF_TABLES, STRIPE_TABLES, TRUTH_TABLES


@dataclass
class RunResult:
    sim: Simulation
    personal_activity: PersonalActivity
    devices: Devices
    row_counts: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    report_path: Path | None = None


def run(config: SimulationConfig, seeds: Seeds, out_dir: Path, *, defects: bool = True,
        report: bool = True) -> RunResult:  # fmt: skip
    timings: dict[str, float] = {}

    @contextmanager
    def stage(name: str):
        start = time.perf_counter()  # timing only; never reaches the data
        yield
        timings[name] = time.perf_counter() - start

    cal = Calendar(config.sim_start_date, config.end_date, config.reporting_tz)
    with stage("population"):
        pop = build_population(config, cal, internal=defects)
        sim = Simulation(config, seeds, pop, cal)
    with stage("personal lifecycle (monthly)"):
        sim.run_personal()
    with stage("business lifecycle, seats, activity (daily)"):
        sim.run_business()
    with stage("direct sales lifecycle and activity (daily)"):
        sim.run_direct_sales()
    with stage("personal activity and devices"):
        personal = personal_monthly(sim)
        devices = device_registrations(sim, personal)
    with stage("render raw_app"):
        tables = app_db.render(sim, personal, devices)
    with stage("write raw_app Parquet"):
        row_counts = {
            name: emit.write(APP_TABLES[name], columns, out_dir / "raw")
            for name, columns in tables.items()
        }
    with stage("render enterprise Salesforce"):
        sf_tables, truth_tables = salesforce_enterprise.render(sim)
    with stage("render Orb billing"):
        orb = billing_orb.Builder(sim, personal)
        orb_tables = orb.build()
    with stage("render Stripe"):
        stripe_rows = billing_stripe.StripeBuilder(sim, orb).build()
    with stage("build answer key"):
        truth_tables |= truth.render(sim, orb, stripe_rows, sf_tables)
    with stage("inject defects"):
        manifest = defects_module.Manifest()
        sf_rows = {name: _rows(cols) for name, cols in sf_tables.items()}
        if defects:
            defects_module.inject(
                sim, orb.ids.business_tailnet, stripe_rows, sf_rows, manifest, orb.rows
            )
            orb_tables["credit_notes"] = _columns(
                ORB_TABLES["credit_notes"], orb.rows["credit_notes"]
            )
        truth_tables["defect_manifest"] = _columns(TRUTH_TABLES["defect_manifest"], manifest.rows)
    with stage("write Orb, Stripe, Salesforce, and truth Parquet"):
        for name, columns in orb_tables.items():
            row_counts[f"orb.{name}"] = emit.write(ORB_TABLES[name], columns, out_dir / "raw")
        for name, rows in stripe_rows.items():
            columns = _columns(STRIPE_TABLES[name], rows)
            row_counts[f"stripe.{name}"] = emit.write(STRIPE_TABLES[name], columns, out_dir / "raw")
        for name, rows in sf_rows.items():
            columns = _columns(SF_TABLES[name], rows)
            row_counts[f"salesforce.{name}"] = emit.write(SF_TABLES[name], columns, out_dir / "raw")
        for name, columns in truth_tables.items():
            row_counts[f"truth.{name}"] = emit.write(
                TRUTH_TABLES[name], columns, out_dir / "answer_key"
            )
    result = RunResult(sim, personal, devices, row_counts, timings)
    if report:
        result.report_path = out_dir / "reports" / "calibration.md"
        calibration.write_report(
            result.report_path, calibration.build_report(sim, devices, timings, row_counts)
        )
    return result


def _rows(columns: dict[str, list]) -> list[dict]:
    names = list(columns)
    return [dict(zip(names, values, strict=True)) for values in zip(*columns.values(), strict=True)]


def _columns(table, rows: list[dict]) -> dict[str, list]:
    return {c.name: [row.get(c.name) for row in rows] for c in table.columns}
