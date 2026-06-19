# Scalable Capital Wealth Portfolio Rebalancer

A local Streamlit valuation dashboard and explainable portfolio-rebalancing tool for a Germany-based Scalable Capital investor. It uses manually entered holdings plus optional Yahoo Finance estimates. It never signs in to Scalable Capital, connects to a broker account, or places trades. This is decision support, not financial advice.

## Privacy and price warning

- Screenshots remain on your computer in `data/uploads/`.
- Personal holdings remain in `data/portfolio_data.json` after you click **Save portfolio**.
- Daily snapshots remain in `data/valuation_history.csv`.
- All three paths are excluded from Git. Do not remove those `.gitignore` rules.
- Holdings and screenshots are never sent to Yahoo Finance. Only the individual **Price Symbol** strings are requested.
- Free internet quotes can be delayed, unavailable, in another currency, or different from the price at your venue. **Scalable Capital's live buy/sell prices are final for order execution.**

## Beginner setup on Windows

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/). Select **Add Python to PATH** during setup.
2. Open this project folder in File Explorer, click the address bar, type `powershell`, and press Enter.
3. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the local app:

   ```powershell
   python -m streamlit run app.py
   ```

5. Stop it later with `Ctrl+C` in PowerShell.

## First valuation, step by step

1. Open **Manual Holdings Table** and add or correct your holdings. You can also use **Upload Holdings Screenshots** as a local visual reference and confirm the values manually.
2. Add a Yahoo Finance **Price Symbol** for each market-traded holding. Symbols often include an exchange suffix, such as `.DE` or `.L`; verify that the result is the exact instrument and listing you own.
3. Enter a reliable **Manual current price** and currency. This is the fallback if the internet quote fails.
4. Open **Valuation Dashboard** and click **Refresh live prices**.
5. Review price sources, currencies, FX rates, warnings, charts, and insights. A row is marked `Live`, `Manual fallback`, or `Missing`.
6. Click **Save today's valuation snapshot** once per day. Saving again on the same day replaces that day's snapshot.
7. Daily gain compares with the latest prior-day snapshot. Weekly, monthly, and yearly gains compare with the snapshots closest to 7, 30, and 365 days ago. Until a prior snapshot exists, the card says **Not enough history yet**.

## Pages

- **Dashboard:** current totals, category allocation, targets, and drift.
- **Valuation Dashboard:** live/manual valuation, period gains, Plotly charts, insights, snapshots, and history export.
- **Upload Holdings Screenshots:** stores local screenshots and supports manual confirmation; no OCR or cloud upload.
- **Manual Holdings Table:** add, edit, delete, save, reset, and export holdings.
- **Rebalance Report:** immediate actions, sells-before-buys execution order, savings-plan adjustments, allocation, notes, and CSV exports.
- **Savings Plans:** editable monthly plans and simple drift-based suggestions.
- **Settings:** base currency, refresh interval, live-price toggle, targets, fee threshold, and cash range.

## How live valuation works

`market_data.py` asks yfinance for the latest price, previous close, currency, and 5-day/1-month/1-year daily histories. Non-EUR quotes use a Yahoo Finance FX estimate. `valuation.py` applies:

```text
value EUR = quantity × selected price × FX rate to EUR
```

The live price is selected when available. Otherwise the manual price is retained and the app warns: **Live price unavailable, using manual price.** Results are cached for the refresh interval configured in Settings. The last successful quote timestamp is shown on the valuation page.

Historical portfolio charts approximate past value using today's quantities; they are not transaction-aware performance or tax records. Snapshot gains also reflect deposits, withdrawals, and quantity changes, not just market movement.

## Rebalancing assumptions

- Preferred venue: EIX/gettex; avoid Xetra unless explicitly needed.
- Whole units for stocks, ETFs, ETCs, and ETPs; crypto may be fractional.
- Direct orders below the configurable €250 default threshold are normally avoided.
- A sub-threshold order warns about €0.99 buy plus €0.99 sell, or €1.98 round trip.
- No auto-trading or broker connection exists.

## Tests

Run:

```powershell
python -m pytest -q
```

Tests cover totals, allocation, drift, fees, local persistence, yfinance adapter behavior, live/manual valuation, EUR and non-EUR conversion, period gains, missing history, and insight generation.
