# Orb billing validation: seed 42 default run

Source: `make data` with `config/simulation.yml`; invoice versions are reduced to their latest version for counts. Task 1.5 acceptance ran with `make test-gen` (72 passed) and `make lint` (passed). The 23 CI-scale Parquet files matched byte for byte across two runs and different `PYTHONHASHSEED` values. Actual CI generation also ran with network and child processes blocked.

Default timed stages: Orb render 2.18 s, Orb Parquet write 0.48 s, combined 2.66 s against the 60 s limit. All stages totaled 8.05 s. Runtime varies by host and remains outside generated data.

Latest invoice statuses: 23,724 paid, 180 issued (recorded failures), and 15 external. Unique invoices: 23,919; invoice version rows: 47,643. Credit notes: 180, each linked to a recorded dunning expiry. Invoice line rows: 26,733; daily revenue rows: 834,525.

## Invoice counts by issue month and line type

Each type column counts distinct invoices containing at least one line of that type; one invoice can appear in several columns. The invoice column counts unique invoices. October 2026 invoices cover September arrears or proration.

| Issue month | Invoices | Fixed | Usage | Proration | Add-on | One-time | Discount |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2023-02 | 9 | 1 | 8 | 0 | 0 | 0 | 1 |
| 2023-03 | 25 | 4 | 21 | 0 | 1 | 0 | 3 |
| 2023-04 | 36 | 5 | 31 | 0 | 1 | 0 | 3 |
| 2023-05 | 54 | 10 | 44 | 0 | 2 | 0 | 4 |
| 2023-06 | 66 | 14 | 52 | 0 | 4 | 0 | 4 |
| 2023-07 | 76 | 14 | 62 | 0 | 5 | 0 | 4 |
| 2023-08 | 97 | 18 | 79 | 0 | 5 | 0 | 8 |
| 2023-09 | 114 | 22 | 92 | 0 | 7 | 0 | 9 |
| 2023-10 | 136 | 28 | 108 | 0 | 6 | 0 | 11 |
| 2023-11 | 151 | 33 | 118 | 0 | 10 | 0 | 12 |
| 2023-12 | 170 | 40 | 130 | 0 | 10 | 0 | 12 |
| 2024-01 | 190 | 44 | 146 | 0 | 9 | 0 | 17 |
| 2024-02 | 216 | 54 | 162 | 0 | 11 | 0 | 21 |
| 2024-03 | 227 | 58 | 169 | 0 | 11 | 0 | 23 |
| 2024-04 | 251 | 67 | 184 | 0 | 9 | 1 | 23 |
| 2024-05 | 273 | 78 | 195 | 0 | 11 | 0 | 26 |
| 2024-06 | 302 | 93 | 209 | 0 | 13 | 1 | 27 |
| 2024-07 | 345 | 110 | 234 | 1 | 10 | 1 | 30 |
| 2024-08 | 380 | 130 | 250 | 0 | 15 | 0 | 30 |
| 2024-09 | 407 | 144 | 263 | 0 | 13 | 1 | 31 |
| 2024-10 | 436 | 153 | 283 | 0 | 14 | 0 | 33 |
| 2024-11 | 471 | 164 | 307 | 0 | 17 | 2 | 38 |
| 2024-12 | 496 | 181 | 315 | 0 | 15 | 1 | 38 |
| 2025-01 | 521 | 192 | 329 | 0 | 20 | 0 | 39 |
| 2025-02 | 562 | 210 | 352 | 0 | 19 | 0 | 41 |
| 2025-03 | 593 | 228 | 364 | 1 | 24 | 1 | 43 |
| 2025-04 | 623 | 239 | 382 | 2 | 23 | 0 | 44 |
| 2025-05 | 655 | 250 | 403 | 2 | 22 | 0 | 45 |
| 2025-06 | 690 | 270 | 420 | 0 | 16 | 0 | 46 |
| 2025-07 | 733 | 286 | 446 | 1 | 26 | 1 | 49 |
| 2025-08 | 783 | 309 | 472 | 2 | 28 | 0 | 52 |
| 2025-09 | 828 | 327 | 501 | 0 | 27 | 1 | 53 |
| 2025-10 | 874 | 360 | 514 | 0 | 29 | 0 | 53 |
| 2025-11 | 916 | 378 | 537 | 1 | 29 | 2 | 53 |
| 2025-12 | 952 | 400 | 550 | 2 | 28 | 1 | 55 |
| 2026-01 | 998 | 427 | 571 | 0 | 36 | 0 | 57 |
| 2026-02 | 1067 | 471 | 594 | 2 | 35 | 5 | 59 |
| 2026-03 | 1126 | 503 | 623 | 0 | 38 | 0 | 60 |
| 2026-04 | 1194 | 547 | 647 | 0 | 45 | 0 | 64 |
| 2026-05 | 1169 | 524 | 645 | 0 | 49 | 1 | 63 |
| 2026-06 | 1103 | 489 | 614 | 23 | 53 | 1 | 65 |
| 2026-07 | 1000 | 422 | 577 | 30 | 56 | 0 | 67 |
| 2026-08 | 1012 | 457 | 552 | 38 | 64 | 0 | 68 |
| 2026-09 | 1024 | 490 | 532 | 42 | 73 | 2 | 69 |
| 2026-10 | 568 | 0 | 511 | 57 | 14 | 0 | 55 |

## Billings by service month and channel

Signed invoice lines are grouped by line service start month (ADR-009), including negative discounts. A next-cycle proration belongs to the prior service month. The table converts each local line at the committed FX rate on its service start date, a Proposed reporting choice in ADR-025; the source invoices remain in customer currency.

| Service month | Stripe USD | AWS USD | Azure USD | Total USD |
|---|---:|---:|---:|---:|
| 2023-01 | 72.00 | 0.00 | 0.00 | 72.00 |
| 2023-02 | 482.17 | 0.00 | 0.00 | 482.17 |
| 2023-03 | 900.87 | 0.00 | 0.00 | 900.87 |
| 2023-04 | 1,400.82 | 0.00 | 0.00 | 1,400.82 |
| 2023-05 | 2,011.33 | 0.00 | 0.00 | 2,011.33 |
| 2023-06 | 2,444.08 | 0.00 | 0.00 | 2,444.08 |
| 2023-07 | 2,760.99 | 0.00 | 0.00 | 2,760.99 |
| 2023-08 | 3,751.61 | 0.00 | 0.00 | 3,751.61 |
| 2023-09 | 4,707.00 | 0.00 | 0.00 | 4,707.00 |
| 2023-10 | 5,244.01 | 0.00 | 0.00 | 5,244.01 |
| 2023-11 | 5,502.49 | 0.00 | 0.00 | 5,502.49 |
| 2023-12 | 16,259.59 | 0.00 | 0.00 | 16,259.59 |
| 2024-01 | 8,034.71 | 0.00 | 0.00 | 8,034.71 |
| 2024-02 | 7,721.49 | 0.00 | 0.00 | 7,721.49 |
| 2024-03 | 8,990.02 | 0.00 | 0.00 | 8,990.02 |
| 2024-04 | 58,348.79 | 0.00 | 0.00 | 58,348.79 |
| 2024-05 | 29,725.76 | 0.00 | 0.00 | 29,725.76 |
| 2024-06 | 10,823.15 | 17,047.36 | 0.00 | 27,870.51 |
| 2024-07 | 68,213.90 | 0.00 | 0.00 | 68,213.90 |
| 2024-08 | 33,062.50 | 10,000.00 | 0.00 | 43,062.50 |
| 2024-09 | 54,106.28 | 0.00 | 0.00 | 54,106.28 |
| 2024-10 | 29,080.53 | 0.00 | 0.00 | 29,080.53 |
| 2024-11 | 64,289.82 | 0.00 | 0.00 | 64,289.82 |
| 2024-12 | 47,057.13 | 40,658.62 | 0.00 | 87,715.75 |
| 2025-01 | 17,497.36 | 0.00 | 0.00 | 17,497.36 |
| 2025-02 | 39,345.81 | 0.00 | 0.00 | 39,345.81 |
| 2025-03 | 78,046.83 | 0.00 | 0.00 | 78,046.83 |
| 2025-04 | 100,728.69 | 0.00 | 0.00 | 100,728.69 |
| 2025-05 | 55,500.85 | 152.17 | 0.00 | 55,653.02 |
| 2025-06 | 182,025.96 | 10,152.26 | 0.00 | 192,178.22 |
| 2025-07 | 89,834.72 | 10,000.00 | 0.00 | 99,834.72 |
| 2025-08 | 68,473.93 | 11,900.24 | 0.00 | 80,374.17 |
| 2025-09 | 127,426.24 | 0.00 | 0.00 | 127,426.24 |
| 2025-10 | 54,674.31 | 0.00 | 0.00 | 54,674.31 |
| 2025-11 | 97,701.77 | 0.00 | 0.00 | 97,701.77 |
| 2025-12 | 106,677.88 | 44,543.44 | 0.00 | 151,221.32 |
| 2026-01 | 34,020.48 | 0.00 | 0.00 | 34,020.48 |
| 2026-02 | 261,712.45 | 298.36 | 0.00 | 262,010.81 |
| 2026-03 | 86,233.50 | 0.00 | 0.00 | 86,233.50 |
| 2026-04 | 121,497.91 | 0.00 | 0.00 | 121,497.91 |
| 2026-05 | 146,058.76 | 20,000.00 | 0.00 | 166,058.77 |
| 2026-06 | 205,926.65 | 12,084.83 | 0.00 | 218,011.48 |
| 2026-07 | 94,760.27 | 10,545.66 | 0.00 | 105,305.93 |
| 2026-08 | 142,295.69 | 11,990.17 | 0.00 | 154,285.86 |
| 2026-09 | 187,229.48 | 0.00 | 43,974.69 | 231,204.17 |

## Calibration context

58 enterprise closes: 28 PLG and 30 direct from 32 scheduled prospects. Two direct opportunities remain open beyond 2026-09-30. Pooled gated-feature upgrade hazard ratio: 3.423, from 113 gated upgrades / 122,600 exposure-days versus 48 / 178,253. Starter: 3.455 from 109 vs 44 events; Standard: 2.852 from four vs four. These are descriptive estimates, not tuned acceptance thresholds.
