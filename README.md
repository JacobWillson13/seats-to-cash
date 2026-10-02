# seats-to-cash

{{CI_BADGE}}

A finance data stack for a fictional product-led networking company, built as an analytics engineering work sample.

**All data is synthetic.** Pricing mechanics are modeled on Tailscale's public pricing page as of October 2026. I'm not affiliated with Tailscale and used no Tailscale data.

**Report:** {{PAGES_URL}}/report | **dbt docs:** {{PAGES_URL}}/docs | **4-minute walkthrough:** {{LOOM_URL}}

## The 60-second version

{{Write this last. Three or four sentences that lead with results, for example: "ARR grew X% from January to September 2026. Y points of that came from repricing during the move to seat-based plans, not expansion. The test suite caught N of 13 planted defects, and billings, revenue, and cash tie out every month."}}

## The three questions

1. **ARR:** What is ARR, and how much of 2026 growth is repricing rather than real expansion?
2. **Close:** Do bookings, billings, revenue, and cash tie out at month-end, and what changed after the books closed?
3. **Growth and risk:** Where does paid growth come from, and which accounts are exposed when legacy pricing ends?

## What's here

- **Synthetic sources in real shapes:** a product database, Orb billing exports, Stripe, Salesforce, marketplace disbursement reports, and a Finance Google Sheet, landed the way Fivetran and Orb land them.
- **A hidden answer key and 13 planted defects:** the generator knows the true ARR, the true revenue, and the true identity map, so the models can be scored rather than eyeballed.
- **Repricing as its own ARR movement:** a price-volume decomposition keeps the legacy-to-seat migration from showing up as expansion.
- **A month-end close command:** `make close PERIOD=2026-09` rebuilds the books as of the close date, reconciles, and logs anything that changes afterward as a restatement with a reason.
- **An inherited-query refactor:** a messy legacy ARR report replaced by modular models, compared row by row, with every difference traced to a bug.
- **Bring-to-work attribution:** which business accounts started as someone's personal account, synced to Salesforce through Hightouch.

## Results

| Check | Result |
|---|---|
| ARR matches the answer key (customer-months, to the cent) | {{}} |
| Planted defects detected | {{}} of 13 |
| Planted defects fully handled | {{}} of 13 |
| Restatements logged across 6 closes | {{}} |
| DuckDB vs Snowflake parity | {{}} |
| Bring-to-work precision / recall (machine key) | {{}} / {{}} |
| PQL top-decile conversion lift | {{}}x |

The defect the suite misses, and why: {{one or two sentences}}.

## Run it

```bash
git clone {{REPO_URL}} && cd seats-to-cash
make demo        # under 10 minutes: generate data, build, test, score, render the report
```

Requires uv and Node. See `docs/SETUP.md`.

## How it's built

```
product DB, Orb, Stripe, Salesforce, marketplaces, Finance sheet  (synthetic, vendor-shaped)
        -> DuckDB (dev) / Snowflake (prod)
        -> dbt: staging -> intermediate -> marts, plus audit models against the answer key
        -> Evidence report, LookML views
        -> Hightouch -> Salesforce Account fields, Slack close summary
```

Stack: Python (uv), DuckDB, Snowflake, dbt Core 1.x, Evidence, Hightouch, Fivetran (one Google Sheet), GitHub Actions.

## Decisions

Every judgment call is in [docs/DECISIONS.md](docs/DECISIONS.md), including the ones that belong to Finance rather than to analytics engineering (refund timing, marketplace gross vs net). Those are dbt vars with documented defaults.

## Known limitations

- Orb's role and its export field names are assumptions (ADR-002, ADR-005).
- Legacy (pre-April 2026) prices are illustrative.
- The causal patterns in the data were planted on purpose, so the analysis rediscovers known effects. The point is the pipeline, not the findings.
- The LookML is parse-checked but untested against a live Looker instance.
- The Snowflake run happened during a 30-day trial; the parity report and screenshots are in `docs/img/`.

## What I'd look at first on a real team

These are questions, not claims about any real company's data:

1. How does ARR reporting separate repricing from expansion as legacy plans migrate over the next year?
2. Are vacant seats, which are still billed under seat pricing, watched as an early contraction signal?
3. How do marketplace and invoice-paid revenue reconcile with Stripe collections at close?

## Author

Jacob Willson | {{LINKEDIN_URL}} | {{EMAIL}}
