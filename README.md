# Financial Advisor / Wealth Portfolio Rebalancer

A production-style Streamlit web app for portfolio valuation, market research, candidate selection, rebalancing, and savings-plan optimization. It is designed for deployment from a private GitHub repository to Streamlit Community Cloud with permanent Supabase persistence.

This is decision support, not financial advice. The app never connects to Scalable Capital, never auto-trades, and never places orders. Internet prices are estimates; always check the final live price manually in Scalable Capital.

## Architecture

- Streamlit Community Cloud: online app hosting
- GitHub: source code only
- Supabase Postgres: holdings, candidates, plans, snapshots, recommendations, and settings
- yfinance: stocks, ETFs, ETCs, ETPs, price history, and FX
- CoinGecko: optional/public crypto prices
- Manual prices: reliable fallback when free APIs fail
- `st.secrets`: credentials and password gate

Production data is not stored in local JSON or CSV. CSV is used only for browser import/export.

## Deploy online

### 1. Create and push the GitHub repository

Create a private GitHub repository. From this project folder:

```powershell
git status
git add .
git commit -m "Deploy Financial Advisor app"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/YOUR-PRIVATE-REPO.git
git push -u origin main
```

Confirm that `.env`, `.streamlit/secrets.toml`, `data/`, uploads, personal CSVs, and cache folders are not staged.

### 2. Create a Supabase project

Create a project at [supabase.com](https://supabase.com). Choose an appropriate EU region and a strong database password.

### 3. Run the SQL schema

Open **Supabase → SQL Editor**, paste the entire contents of `supabase_schema.sql`, and run it once. It creates:

- `holdings`
- `candidate_assets`
- `savings_plans`
- `valuation_snapshots`
- `recommendations`
- `app_settings`
- indexes and MVP row-level security policies

The MVP uses `user_id = "default_user"` after successful Streamlit password login. Upgrade to Supabase Auth and `auth.uid()` policies before supporting multiple independent users.

### 4. Create the Streamlit Community Cloud app

Open [share.streamlit.io](https://share.streamlit.io), connect GitHub, select the private repository and `main` branch, and create the app.

### 5. Set the app file

Set the main file path to:

```text
app.py
```

### 6. Add Streamlit secrets

Copy `.streamlit/secrets.example.toml` into the Community Cloud Secrets editor and replace the required placeholders:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
APP_PASSWORD = "use-a-long-random-password"
COINGECKO_API_KEY = ""
TWELVE_DATA_API_KEY = ""
FMP_API_KEY = ""
OPENFIGI_API_KEY = ""
```

Only the first three are required. Optional provider keys may remain empty. Never use the Supabase service-role key and never commit real secrets.

### 7. Reboot the app

Save the secrets, then reboot or redeploy the Community Cloud app so the server reloads them.

### 8. Log in

Open the generated `https://YOUR-APP.streamlit.app` URL and enter `APP_PASSWORD`. No localhost is needed after deployment. No portfolio data is displayed before successful authentication.

### 9. Add holdings

Open **Current Portfolio**. Add/edit/delete rows with the data editor or import CSV. Add manual prices even when using live symbols so valuation has a fallback. Click **Save portfolio to Supabase**.

### 10. Add candidate assets

Open **Candidate Universe**. Add assets manually or import CSV. Complete Price Symbol, category, asset type, costs, compatibility, source URL, and confidence. Missing critical data remains manual-review/watchlist only.

### 11. Refresh live prices

Use **Refresh market data** on the valuation, current portfolio, candidate, or research pages. Prices are cached for 15 minutes, history for one hour, and FX for 12 hours. Crypto symbols such as `BTC-USD` try CoinGecko first. Failed live prices use the manual holding price and display a warning.

### 12. Save a valuation snapshot

Open **Valuation Dashboard** and click **Save today's valuation snapshot**. Daily, weekly, monthly, and yearly changes compare current value with the closest Supabase snapshot. Missing periods show **Not enough history yet**.

### 13. Generate the rebalance report

Review **Asset Quality Dashboard**, **Rebalance Engine**, **Savings Plan Optimizer**, and **Recommendation Report**. Export CSV if needed or save recommendations to Supabase.

## App pages

1. Dashboard
2. Valuation Dashboard
3. Current Portfolio
4. Candidate Universe
5. Market Research Dashboard
6. Asset Quality Dashboard
7. Rebalance Engine
8. Savings Plan Optimizer
9. Recommendation Report
10. Settings

## Scoring and recommendation rules

Total score is momentum 25%, asset quality 25%, cost 15%, portfolio fit 25%, and risk control 10%.

- 8.0–10: eligible for buy/add when critical data is complete
- 6.5–7.9: watchlist only
- Below 6.5: avoid/no buy
- Missing symbol/manual price, category, asset type, fund cost information, or Scalable compatibility: manual review only

Default targets are Core 25%, EM 15%, Growth 40%, Defence 5%, Commodities 10%, Crypto 5%, and Cash 0–2%.

Scalable Capital assumptions:

- Germany-based PRIME+ investor
- Prefer EIX/gettex; avoid Xetra unless explicitly needed
- Whole quantities for stocks, ETFs, ETCs, and ETPs
- Crypto may be fractional
- Direct trades below €250 are normally avoided
- Below-threshold fee warning: €0.99 buy + €0.99 sell = €1.98 round trip
- €250+ EIX/gettex PRIME+ orders may avoid order fees; verify manually
- Every execution action says **Check live Scalable price before execution**

## Local development (optional)

Create `.streamlit/secrets.toml` locally using the example file, then run:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The real secrets file is ignored by Git.

## Troubleshooting

### `ModuleNotFoundError`

Confirm the package is present in `requirements.txt`, push the change, and reboot the Community Cloud app.

### Supabase connection error

Check `SUPABASE_URL`, `SUPABASE_ANON_KEY`, project status, and whether `supabase_schema.sql` ran successfully. Use the anon key—not the service-role key.

### Blank data

Run the SQL schema, log in, add rows, and click the relevant Supabase save button. Empty databases initially show safe demo data that is not persisted until saved.

### Live prices missing

Add the exact Yahoo/CoinGecko Price Symbol or enter a manual price. Verify exchange suffixes such as `.DE`, `.L`, or `.AS`.

### Internet price differs from Scalable Capital

Free prices may be delayed or use another exchange/currency. Check the live Scalable bid/ask, spread, venue, taxes, and fees before execution.

## Tests

```powershell
python -m pytest -q
```

Tests do not require production credentials. They cover database payloads, valuation and snapshot gains, market-data fallbacks, scoring, missing-data watchlists, savings-plan budgets, optimizer order, storage paths, and fee warnings.
