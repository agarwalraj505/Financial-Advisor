# Financial Advisor / Wealth Portfolio Rebalancer

A market-data-first Streamlit command center for portfolio valuation, research, strategy design, rebalancing, and savings-plan planning. It deploys from GitHub to Streamlit Community Cloud and stores private app data in Supabase.

This is decision support, not financial advice. It never connects to Scalable Capital, places orders, or changes broker savings plans. Internet prices are estimates; check the final live buy/sell price manually in Scalable Capital.

## Premium UI overview

Financial Hub uses a bright, high-contrast fintech design system without third-party branding or proprietary assets. The interface is intentionally calm and practical: white cards, readable typography, responsive KPI layouts, consistent Plotly charts, source-confidence badges, guided workflows, and restrained gain/loss colors. The layout adapts its columns for narrower mobile screens.

The presentation layer lives in:

- `styles.py`: light-mode design tokens, responsive CSS, readable sidebar states, cards, controls, tables, and disabled-button styling.
- `ui_components.py`: escaped page headers, hero summaries, metric cards, alerts, badges, news cards, recommendation cards, flow steps, empty states, and chart helpers.

## Navigation guide

The sidebar deliberately exposes only five destinations:

1. **Portfolio** — wealth overview, holdings editor, screenshot flow, analytics, and valuation snapshots.
2. **Market** — provider health, enrichment, candidate assets, research, repair center, news, and sentiment.
3. **Strategy** — current strategy, regime, target allocation, themes, risks, and saved snapshots.
4. **Rebalance** — the full superflow, recommendations, execution order, savings plans, and report.
5. **Settings** — app status, providers, strategy controls, Scalable assumptions, and confirmed danger-zone actions.

The sidebar also shows Supabase connectivity, live-data status, and the latest refresh time.

## Rebalancer Rulebook

`rebalancer_rulebook.py` is the single policy source for the confirmed portfolio baseline, base targets, broker assumptions, €250 direct-trade threshold, €0.99 below-threshold fee assumption, whole-unit direct execution, €300 monthly savings plan, theme/region review universe, workflow order, and required report sections. `rulebook_engine.py` applies those rules through validation, output formatting, execution ordering, and skip conditions.

Open **Settings → Rebalancer Rulebook** to inspect the active version, source, targets, workflow, and guardrails. Loading the confirmed holdings or savings plan requires an explicit confirmation and overwrites app records only—never broker positions. A full rebalance always starts from saved holdings, treats later unimplemented recommendations as unexecuted, refreshes evidence, and may conclude that no immediate trade is justified.

## Portfolio workflow

1. Open **Portfolio** and review the hero valuation and performance cards.
2. Scroll to **Current holdings** to edit records, import CSV, refresh prices, and save to Supabase.
3. Check the Live / Manual fallback / Missing and readiness labels before relying on a value.
4. Open **Detailed valuation analytics** only when you need performance history and deeper diagnostics.
5. Save a valuation snapshot to create daily, weekly, monthly, and yearly comparison history.

All valuation and performance figures remain estimates until confirmed against Scalable Capital.

## 1. Market Data Engine

The stabilized data path has one responsibility per module:

- `symbol_resolver.py` resolves and caches verified symbols and seven-day bad-symbol cooldowns.
- `providers/` contains provider-specific network calls.
- `market_data_engine.py` owns quick quote, FX, and deep-enrichment waterfalls.
- `market_data.py` is a compatibility facade; it contains no direct provider implementation.
- `valuation.py` is the only module that calculates position value and P/L.
- `app.py` triggers explicit refresh actions and renders cached results.

The app enriches every holding and candidate through a provider waterfall:

1. Preserve user-entered facts.
2. Map ISINs with unauthenticated OpenFIGI.
3. Use Alpha Vantage symbol search, quotes, daily history, and ETF profiles when its optional key is configured.
4. Search and test yfinance symbols, then use yfinance and Stooq as fallbacks.
5. Convert currencies using the ECB Data Portal, then Alpha Vantage and yfinance FX as fallbacks.
6. Try yfinance crypto symbols and optional public CoinGecko.
7. Search public web sources for unresolved metadata.
8. Safely scrape source-ranked, robots-permitted pages.
9. Request manual fallback after failed enrichment.

User-entered values are never silently overwritten. Conflicts are stored as suggestions with source, timestamp, method, and confidence.

### Price and valuation precedence

Every position exposes one explicit source: **Live market data**, a user-confirmed **Scalable screenshot**, **Manual fallback**, or **Missing**. Resolved market symbols are stored separately from entered symbols, so enrichment does not silently rewrite the portfolio record.

EUR values use ECB FX first, Alpha Vantage second when configured, and yfinance FX third. GBp/GBX quotes are treated as pence—one hundredth of GBP—which avoids the common 100× valuation error.

### Free-source waterfall

- Identifiers: entered values → unauthenticated OpenFIGI mapping/name search → bounded Yahoo candidates → public search → permitted issuer/aggregator pages → manual repair.
- Prices: entered fallback → cached live quote → Alpha Vantage provider symbol → exact yfinance symbol → cached symbol candidates → conservative Stooq fallback → crypto yfinance/CoinGecko → manual fallback.
- Public price fallback: permitted issuer/exchange/product pages are checked after yfinance and Stooq. Low-confidence snippets are never used for valuation.
- FX: ECB Data Portal → Alpha Vantage exchange rate → yfinance pair → confirmed manual FX.
- Fund facts: entered facts → Alpha Vantage ETF profile → issuer factsheet/KID HTML or PDF → yfinance metadata → permitted ETF aggregator → manual confirmation.
- News: public GDELT DOC API → configured RSS → yfinance asset news → relevance ranking and transparent sentiment.

Sources can time out, rate-limit, omit fields, or disagree. The app therefore maximizes legal free coverage but never claims completeness or invents a value.

## Data Coverage Dashboard

The **Market → Data Coverage** section calculates price, metadata, TER/cost, FX, factsheet, news, valuation-ready, and recommendation-ready percentages from cached data. It does not make network calls. The Data Gap Report lists every unresolved field, sources already tried, last attempt, failure reason, and suggested next action.

Coverage guardrails:

- Price coverage below 90% displays a valuation caution.
- Metadata coverage below 75% reduces strategy/scoring confidence.
- TER coverage below 75% blocks buy/add for ETF candidates that are not recommendation-ready.
- Existing holdings may remain Hold / Review when TER is missing; missing metadata alone never forces a sale.

## Deep Data Scan

Deep scans are deliberately chunked for Streamlit Community Cloud. The default chunk processes at most five incomplete/stale assets with up to four workers. Fresh complete assets are skipped. Symbol resolution, price/history, FX, OpenFIGI, safe factsheet metadata, news inputs, source audit, failures, and job progress are saved after each completed asset. Use **Continue Deep Scan** for the next chunk.

Streamlit Cloud does not guarantee durable background jobs. Keep the Market page open while a chunk runs; closing or rerunning the page does not lose already saved results.

## Caching, timeouts, and rate limits

- Prices: stale after 15 minutes.
- FX: stale after 12 hours.
- Metadata: stale after 7 days.
- TER/factsheets: stale after 30 days.
- News: stale after 60 minutes.
- Bad symbols: not retried for 7 days.
- Price/provider timeout target: 8 seconds; web search: 10 seconds; scrape: 12 seconds per URL.
- OpenFIGI unauthenticated requests: batches of at most five ISINs and at most 20 requests per minute.
- Web scraping: at most one request per second per domain, subject to robots/access checks.

Ordinary page visits load last-known Supabase values. Use **Quick refresh prices**, **Repair missing symbols**, **Deep metadata scan**, or **Refresh news & sentiment** only when needed.

## 2. No paid API key mode

Only these Streamlit secrets are required:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
APP_PASSWORD = "use-a-long-random-password"
```

yfinance, unauthenticated OpenFIGI, ECB, RSS, and permitted public pages require no paid key. `OPENFIGI_API_KEY` and `COINGECKO_API_KEY` are optional. FMP and Twelve Data remain disabled unless their optional keys exist; their absence never blocks the app.

### Optional Alpha Vantage setup

1. Go to Streamlit Community Cloud.
2. Open **Manage app → Settings → Secrets**.
3. Add `ALPHA_VANTAGE_API_KEY = "your-key"` without committing it to GitHub.
4. Reboot the app.
5. Open **Settings** to confirm that Alpha Vantage is enabled.

Alpha Vantage improves provider-specific symbol search, quotes, daily history, FX fallback, and ETF profile data. Its responses can be rate-limited or end-of-day; the engine automatically continues through yfinance, Stooq, and manual fallback. Always check the final live price in Scalable Capital before execution.

Free sources often do not provide dependable ETF TER data. A candidate ETF/ETC/ETP cannot become buy/add eligible until cost data is confirmed or extracted from a high-confidence source. Existing holdings can still be valued when TER is absent.

## 3. Internet enrichment and scraping

The app ranks official issuer/factsheet pages first, then official exchanges, accessible ETF aggregators, and finance portals. It respects `robots.txt` where possible and does not bypass paywalls, logins, captchas, or anti-bot controls. It never scrapes Scalable Capital.

Accessible factsheet and KID PDFs are capped at 40 pages and 12 MB and parsed with `pypdf`. High confidence requires a reliable source, the expected ISIN, and a clearly labelled value. Search snippets remain low confidence and cannot make a candidate buy-ready.

> Web-scraped data may be incomplete or outdated. Confirm important data from the issuer factsheet before investing.

## 4. Missing Data Repair Center

Open **Market → Missing Data Repair** to find absent symbols, TER/cost, asset type, category, factsheets, compatibility confirmations, conflicts, failed scrapes, and OpenFIGI rate limits. Use **Auto repair selected asset** or **Retry public web search** before entering a fallback value.

Readiness has two levels:

- Valuation ready: quantity, a live or fallback price, and usable currency/FX.
- Recommendation ready: valuation ready plus category, asset type, source/confidence, confirmed Scalable compatibility for candidates, and verified fund cost data where applicable.

## 5. Market news and sentiment

**Market** presents provider status, missing-data repair, enrichment audit, public news, sentiment, and candidate research as readable vertical sections. It fetches legal public RSS and available yfinance headlines. Provider or news failure does not crash valuation or rebalancing.

## 6. Strategy refresh

The **Strategy** section shows targets, risk profile, regime, preferred/reduced themes, risks, and savings-plan implications. Strategy changes are evidence-gated: weak news evidence does not manufacture a new market view. Save strategy snapshots to Supabase for history.

## 7. Full rebalance pipeline

**Rebalance → Run full rebalance** performs the complete workflow: price refresh, ISIN/ticker enrichment, missing-metadata repair, news, sentiment, strategy redesign, valuation, drift, scoring, portfolio optimization, savings-plan optimization, recommendation report, manual execution checklist, and Supabase snapshots.

Recommendations use Scalable Capital PRIME+ assumptions:

- Prefer EIX/gettex and avoid Xetra unless specifically needed.
- Use whole quantities for stocks, ETFs, ETCs, and ETPs; crypto may be fractional.
- Direct buys below €250 are usually fee-inefficient.
- Direct trades below €250 are normally avoided; the rulebook assumes a €0.99 trading fee.
- Every execution recommendation says to check the live Scalable price.

## 8. Using Scalable screenshots

Open **Portfolio → Add or update a holding from a Scalable screenshot**. Upload an image, paste its visible text, parse European-formatted values, and confirm/correct every field. The image is stored privately in Supabase Storage—not GitHub. Existing category, asset type, and price symbol are preserved unless explicitly confirmed.

## 9. Updating savings plans in the app

The optimizer can add, pause, increase, reduce, or remove app records while keeping the configured monthly budget. Export the Scalable execution checklist and apply it manually in the broker.

> Changes saved here do not update actual Scalable Capital savings plans.

## 10. Deployment on Streamlit Community Cloud

1. Create a private GitHub repository and push this code.
2. Confirm `.env`, `.streamlit/secrets.toml`, `data/`, `uploads/`, screenshots, and CSV exports are not staged.
3. Create a Supabase project, preferably in an appropriate EU region.
4. Run all of `supabase_schema.sql` in Supabase SQL Editor.
5. Create a Streamlit Community Cloud app from the GitHub repository.
6. Set the main file to `app.py`.
7. Add the three required secrets shown above. Optionally add `ALPHA_VANTAGE_API_KEY`.
8. Reboot the app and log in with `APP_PASSWORD`.
9. Add holdings and candidates, then save them to Supabase.
10. Refresh prices/metadata and save a valuation snapshot.
11. Review strategy and run the full rebalance.

No localhost is needed after deployment.

## 11. Supabase setup

`supabase_schema.sql` creates holdings, candidate assets, savings plans, valuation snapshots, recommendations, settings, market news, strategy snapshots, rebalance runs, rulebook versions, guardrail checks, indexes, MVP row-level policies, and a private screenshot bucket.

The password-gated MVP uses `user_id = "default_user"` and passes it from the private Streamlit server in an `x-user-id` header. Before supporting multiple users, migrate to Supabase Auth and `auth.uid()`-based RLS. Never use or expose the Supabase service-role key.

## 12. Troubleshooting

- `ModuleNotFoundError`: confirm the package is in `requirements.txt`, push, and reboot Streamlit Cloud.
- Supabase error: verify URL, anon key, project status, and that the latest SQL schema ran.
- Blank data: save rows from the app; demo data is not persisted automatically.
- Live price missing: verify the Yahoo exchange suffix and run Data Enrichment; then provide a fallback price if every route fails.
- TER missing: add an official factsheet URL or confirmed cost note. Missing TER blocks new fund buy/add eligibility, not existing-holding valuation.
- OpenFIGI 429: wait and retry; the engine continues through yfinance and web enrichment.
- Internet price mismatch: free prices can be delayed or use a different venue/currency. Check Scalable bid/ask and spread before execution.

## Local development and tests

Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml`, fill local development credentials, then run:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
python -m pytest -q
```

The real secrets file is ignored by Git. Tests do not require production credentials or paid market-data keys.
