# Market-Aware Wealth Manager — Streamlit Cloud + Supabase

A production-style Streamlit decision-support application for portfolio valuation, market research, candidate selection, rebalancing, and savings-plan optimization.

The deployed app runs at a `streamlit.app` URL. Supabase Postgres stores portfolio data permanently and a private Supabase Storage bucket stores optional screenshots. The app never connects to Scalable Capital, never places orders, and never auto-trades. Internet prices are estimates; check the final live price manually in Scalable Capital before execution.

## Architecture

- Streamlit frontend hosted by Streamlit Community Cloud
- Private GitHub repository for code only
- Supabase Postgres for holdings, candidates, plans, snapshots, recommendations, and settings
- Private Supabase Storage bucket for screenshots
- yfinance market-data adapter with manual-price fallback
- `st.secrets` for credentials and the password gate
- Pure Python valuation/scoring/optimizer modules covered by pytest

No production portfolio data is written to local JSON or CSV. CSV is used only for browser import/export.

## Online deployment

### 1. Create a private GitHub repository

Create an empty private repository on GitHub. Do not add portfolio files, screenshots, `.env`, or `secrets.toml`.

### 2. Push the code to GitHub

From this project folder:

```powershell
git add .
git commit -m "Deploy market-aware wealth manager"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/YOUR-PRIVATE-REPO.git
git push -u origin main
```

Review `git status` first. The repository should contain source code and `supabase_schema.sql`, but not `data/`, uploads, personal CSVs, `.env`, or `.streamlit/secrets.toml`.

### 3. Create a Supabase project

Create a project at [supabase.com](https://supabase.com). Choose a strong database password and a nearby EU region where appropriate. Wait for provisioning to finish.

### 4. Run the database schema

In Supabase, open **SQL Editor**, create a query, paste the complete contents of `supabase_schema.sql`, and run it once. This creates:

- `profiles`
- `holdings`
- `candidate_assets`
- `savings_plans`
- `valuation_snapshots`
- `recommendations`
- `app_settings`
- private `holdings-screenshots` Storage bucket
- indexes, unique constraints, and row-level security policies

The MVP uses a password-derived pseudonymous `x-user-id` header. RLS permits access only to rows and screenshot folders matching that identifier. Before supporting multiple people, replace the password gate with Supabase Auth or Streamlit OIDC and use `auth.uid()` policies.

### 5. Copy the Supabase URL and anon key

Open the Supabase project API settings and copy:

- Project URL
- Anon/publishable key

Never use or commit the service-role key. The app needs only the anon key.

### 6. Create the Streamlit Community Cloud app

Sign in at [share.streamlit.io](https://share.streamlit.io), select **Create app**, connect GitHub, choose the private repository and `main` branch, and set the main file to `app.py`.

### 7. Add Streamlit secrets

In the app's **Advanced settings → Secrets**, add:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR-ANON-KEY"
APP_PASSWORD = "USE-A-LONG-RANDOM-PASSWORD"
```

Do not place these values in source code. An optional stable identifier can be supplied as `APP_USER_ID`; otherwise one is derived from `APP_PASSWORD`. If no `APP_USER_ID` is set, changing `APP_PASSWORD` changes the derived data scope, so existing rows will appear inaccessible until migrated.

### 8. Deploy

Click **Deploy**. Community Cloud installs `requirements.txt`, starts `app.py`, and displays build logs. If setup is incomplete, the app gives a readable missing-secret or database error instead of writing data locally.

### 9. Open the online URL

Open the generated `https://YOUR-APP.streamlit.app` URL and enter `APP_PASSWORD`. No localhost is required after deployment.

### 10. Add holdings and save

Open **Current Portfolio**, enter or import holdings, and click **Save portfolio to Supabase**. Data remains available after closing the browser. Use **Candidate Universe**, **Savings Plan Optimizer**, and **Settings** to save their corresponding data.

### 11. Refresh live prices

Click **Refresh market data**. yfinance supplies estimated latest prices, previous close, histories, returns, volatility, drawdown, moving-average comparisons, and trend status. Failed prices use a manual holding price when available and show a warning.

### 12. Save a valuation snapshot

Open **Valuation Dashboard** and click **Save today's valuation snapshot**. Supabase upserts one snapshot per user and date. Daily, weekly, monthly, and yearly gains compare current value with the closest prior snapshot. Missing periods show **Not enough history yet**.

## Secrets for local development

Local development is optional. Create `.streamlit/secrets.toml` only on your own machine:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR-ANON-KEY"
APP_PASSWORD = "YOUR-PASSWORD"
```

Then run:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The secrets file is ignored by Git.

## Pages

1. Dashboard
2. Valuation Dashboard
3. Current Portfolio
4. Upload Holdings Screenshots
5. Candidate Universe
6. Market Research Dashboard
7. Asset Quality Dashboard
8. Rebalance Engine
9. Savings Plan Optimizer
10. Recommendation Report
11. Settings

## Scoring and safeguards

Total score uses momentum 25%, asset quality 25%, cost 15%, portfolio fit 25%, and risk control 10%.

- 8.0–10: eligible for buy/add only with complete critical data
- 6.5–7.9: watchlist only
- Below 6.5: avoid/no buy
- Missing Price Symbol, TER, fund size, or spread for fund products: manual review only

Recommendations show source, timestamp, reason, confidence, fee context, and **Check live Scalable price before execution**. Stocks, ETFs, ETCs, and ETPs use whole quantities; crypto may be fractional. Direct orders below €250 normally defer to savings plans and show the assumed €1.98 round-trip fee. EIX/gettex is preferred; avoid Xetra unless specifically needed.

## Privacy and security notes

- `.env`, `.streamlit/secrets.toml`, `data/`, `uploads/`, personal CSVs, caches, and bytecode are ignored.
- Supabase queries are filtered by `user_id`, and RLS independently checks the pseudonymous request header.
- Screenshots use a private bucket and user-specific folder policy.
- The password is compared server-side and is never stored in the database.
- This MVP is single-user. Use Supabase Auth or Streamlit OIDC before sharing access with multiple users.
- Rotate exposed credentials immediately. Never use a service-role key in this app.

## Tests

```powershell
python -m pytest -q
```

Tests run without real Supabase credentials. They cover database payloads and user scoping, private screenshot paths, valuation and snapshot gains, scoring, missing-data watchlist enforcement, savings-plan budgets, optimizer execution order, and sub-€250 fee warnings.
