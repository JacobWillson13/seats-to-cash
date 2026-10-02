# SETUP

Accounts, environment, and commands. Do section 1 before Day 1. Do sections 2 to 5 on Day 3. Check each vendor's current docs if a screen or flag has moved.

## 1. Local toolchain (home server or laptop)

### 1.1 Python and project dependencies

```bash
# uv (skip if already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12

# inside the repo, after task 1.1 creates pyproject.toml
uv add numpy pandas pyarrow duckdb faker pydantic pyyaml free-email-domains
uv add "dbt-core<2" dbt-duckdb "dbt-snowflake<2" snowflake-connector-python
uv add --dev pytest ruff sqlfluff sqlfluff-templater-dbt pre-commit lkml
uv run dbt --version
```

### 1.2 Node (Evidence build only; you write SQL and Markdown, not JavaScript)

```bash
# install nvm from github.com/nvm-sh/nvm, then:
nvm install --lts
node --version
```

### 1.3 Free email domain seed

```bash
mkdir -p seeds
uv run python -c "
import csv
from free_email_domains import whitelist
with open('seeds/free_email_domains.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['domain'])
    for d in sorted(whitelist):
        w.writerow([d])
"
wc -l seeds/free_email_domains.csv
```

### 1.4 FX rates

`scripts/fetch_fx.py` (task 1.2) downloads the ECB historical reference rates (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip), keeps EUR and GBP, converts to USD per unit, and writes `seeds/fx_rates.csv`. Commit the CSV so the demo never needs the network.

### 1.5 Environment file

```bash
cat > .env.example <<'EOF'
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_PRIVATE_KEY_PATH=~/.snowflake/seats_to_cash_rsa.p8
RAW_DATABASE=raw
EOF
cp .env.example .env
```

## 2. Snowflake (start on Day 3)

Sign up for the trial at signup.snowflake.com. Choose Enterprise edition on AWS in the region closest to you. The 30 days start now.

### 2.1 Key pairs for service users

Use key-pair authentication for dbt and Hightouch rather than passwords.

```bash
mkdir -p ~/.snowflake && cd ~/.snowflake
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out seats_to_cash_rsa.p8 -nocrypt
openssl rsa -in seats_to_cash_rsa.p8 -pubout -out seats_to_cash_rsa.pub
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out hightouch_rsa.p8 -nocrypt
openssl rsa -in hightouch_rsa.p8 -pubout -out hightouch_rsa.pub
chmod 600 *.p8
# public key bodies, without header/footer lines, for the SQL below
grep -v "PUBLIC KEY" seats_to_cash_rsa.pub | tr -d '\n'; echo
grep -v "PUBLIC KEY" hightouch_rsa.pub | tr -d '\n'; echo
```

### 2.2 Warehouse, databases, roles, users

Run in a Snowsight worksheet as ACCOUNTADMIN:

```sql
use role accountadmin;

create warehouse if not exists transform_wh
  warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true;

create resource monitor if not exists trial_guard
  with credit_quota = 50
  triggers on 80 percent do notify
           on 100 percent do suspend;
alter warehouse transform_wh set resource_monitor = trial_guard;

create database if not exists raw;
create database if not exists analytics;

create role if not exists transformer;
grant usage on warehouse transform_wh to role transformer;
grant all on database raw to role transformer;
grant all on database analytics to role transformer;

create role if not exists reporter;
grant usage on warehouse transform_wh to role reporter;
grant usage on database analytics to role reporter;
grant usage on future schemas in database analytics to role reporter;
grant select on future tables in database analytics to role reporter;
grant select on future views in database analytics to role reporter;

create user if not exists svc_dbt
  type = service default_role = transformer default_warehouse = transform_wh
  rsa_public_key = '<seats_to_cash_rsa.pub body>';
grant role transformer to user svc_dbt;

create user if not exists svc_hightouch
  type = service default_role = reporter default_warehouse = transform_wh
  rsa_public_key = '<hightouch_rsa.pub body>';
grant role reporter to user svc_hightouch;
```

If Hightouch's faster sync engine asks for a writable schema, create `analytics.hightouch_planner` and grant it to `reporter`.

### 2.3 dbt profile

`~/.dbt/profiles.yml` (keep it out of the repo):

```yaml
seats_to_cash:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: data/seats_to_cash.duckdb
      threads: 4
    snowflake:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: svc_dbt
      private_key_path: "{{ env_var('SNOWFLAKE_PRIVATE_KEY_PATH') }}"
      role: transformer
      warehouse: transform_wh
      database: analytics
      schema: dbt
      threads: 8
```

In `sources.yml`, set each raw source's `database` to `"{{ env_var('RAW_DATABASE', target.database) }}"`, so DuckDB reads its own file and Snowflake reads `raw`. Keep the schema names (`raw_app`, `raw_orb`, and so on) identical on both targets.

### 2.4 Load and build

`generator/load.py --target snowflake` writes each Parquet file with `snowflake.connector.pandas_tools.write_pandas` (use `auto_create_table=True` and `use_logical_type=True` so timestamps keep their types). Then:

```bash
set -a; source .env; set +a
make snowflake      # load raw, dbt build --target snowflake, parity check
```

### 2.5 Cost hygiene

- Keep the warehouse at XSMALL with 60-second auto-suspend.
- Check Admin, Cost Management, in Snowsight once a day.
- After the screenshots and parity report are captured, suspend the warehouse.

## 3. Salesforce Developer Edition

1. Sign up at developer.salesforce.com/signup. Data storage is capped at 5 MB, so sync a few hundred accounts at most.
2. Go to Setup, Object Manager, Account, Fields and Relationships, New. Create:

| Field label | API name | Type |
|---|---|---|
| Tailnet ID | Tailnet_ID__c | Text(32), External ID, Unique |
| Seats Purchased | Seats_Purchased__c | Number(8, 0) |
| Seat Utilization | Seat_Utilization__c | Percent(3, 1) |
| ARR | ARR__c | Currency(16, 2) |
| PQL Score | PQL_Score__c | Number(3, 0) |
| Migration Risk | Migration_Risk__c | Picklist: High, Medium, Low |
| Signals Updated At | Signals_Updated_At__c | Date/Time |

3. Add the fields to the Account page layout so they appear in the screenshot.

## 4. Hightouch

The free plan allows two active syncs a month. A sync that ran this month counts even if you delete it.

1. Sign up at hightouch.com.
2. Add a Snowflake source: account identifier, user `svc_hightouch`, role `reporter`, warehouse `transform_wh`, database `analytics`, key-pair auth with `hightouch_rsa.p8`.
3. Add destinations: Salesforce (OAuth into the Developer Edition org) and Slack (OAuth, with a `#month-end-close` channel).
4. Sync 1, account signals:
   - Model: `select * from analytics.dbt.fct_account_signals where sync_eligible`
   - Destination object: Account. Mode: upsert. Match `Tailnet_ID__c` to `tailnet_id`.
   - Map seats_purchased, seat_utilization, arr_usd, pql_score, migration_risk_tier, signals_updated_at.
   - Schedule: manual or daily.
5. Sync 2, close summary:
   - Model: the latest row of `analytics.dbt.close_summary`.
   - Destination: Slack message to `#month-end-close`, with a template showing period, ARR, revenue, restatement count, and test status.
6. Run both. Screenshot the Salesforce Account page and the Slack message into `docs/img/`.

## 5. Fivetran (optional, task 3.7)

1. Create a Google Sheet named "Wirefern Finance Manual Adjustments" and import `data/raw/finance/manual_adjustments.csv`. Define a named range over the data.
2. In Fivetran (Free plan), add a Snowflake destination using key-pair auth and database `raw`.
3. Add a Google Sheets connector pointing at the named range, with destination schema `raw_finance` and table `manual_adjustments`.
4. Sync. The initial sync doesn't count against usage.

## 6. Evidence and GitHub Pages

```bash
mkdir -p reports && cd reports
npx degit evidence-dev/template .
npm install
npm run sources     # pull data from configured sources
npm run dev         # local preview at http://localhost:3000
npm run build       # static site in reports/build
```

- Configure a DuckDB source pointing at `../data/seats_to_cash.duckdb`. Evidence reads it at build time, so the published site doesn't need a live warehouse.
- For GitHub Pages under a subpath, set Evidence's base path (see "Base paths" in Evidence's docs) to `/seats-to-cash/report`. `make report BASE_PATH=` builds a root-path copy for the Funnel mirror.
- Pages workflow on main: build dbt docs with `dbt docs generate --static` into `/docs/`, build Evidence into `/report/`, then upload one Pages artifact and deploy it.

## 7. Tailscale Funnel mirror (optional, task 4.6)

On the home server, after `make report BASE_PATH=`:

```bash
cd ~/seats-to-cash/reports/build
python3 -m http.server 8080 --bind 127.0.0.1 &
sudo tailscale funnel --bg 8080
tailscale funnel status          # prints the public https://<machine>.<tailnet>.ts.net URL

# stop it
sudo tailscale funnel reset
kill %1
```

If Funnel isn't enabled for the tailnet, the CLI prints a link to turn it on in the admin console. Serve only the static build through Funnel, never a database or a dev server. Use `tmux` or a systemd user service if it needs to survive logout.

## 8. Before going public

```bash
git log -p | grep -i -E "password|private_key|BEGIN .*KEY|token=" | head
git ls-files | grep -E "\.env$|\.p8$|profiles\.yml$"
```

Both should return nothing. Then set the repo to public and check every README link from a logged-out browser.
