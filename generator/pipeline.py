"""Run the generator stages in order, timing each one."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from generator import app_db, calibration, emit
from generator.activity import Devices, PersonalActivity, device_registrations, personal_monthly
from generator.clock import Calendar
from generator.config import SimulationConfig
from generator.population import build_population
from generator.reference import Seeds
from generator.simulate import Simulation
from generator.tables import APP_TABLES


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

    cal = Calendar(config.sim_start_date, config.end_date)
    with stage("population"):
        pop = build_population(config, cal, internal=defects)
        sim = Simulation(config, seeds, pop, cal)
    with stage("personal lifecycle (monthly)"):
        sim.run_personal()
    with stage("business lifecycle, seats, activity (daily)"):
        sim.run_business()
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
    result = RunResult(sim, personal, devices, row_counts, timings)
    if report:
        result.report_path = out_dir / "reports" / "calibration.md"
        calibration.write_report(
            result.report_path, calibration.build_report(sim, devices, timings, row_counts)
        )
    return result
