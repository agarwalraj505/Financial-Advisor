"""Local-only JSON and screenshot storage helpers."""

import json
import re
from pathlib import Path

import pandas as pd

from rebalancer import HOLDING_COLUMNS, holdings_to_dataframe

DATA_DIR = Path("data")
UPLOAD_DIR = DATA_DIR / "uploads"
PORTFOLIO_FILE = DATA_DIR / "portfolio_data.json"
VALUATION_HISTORY_FILE = DATA_DIR / "valuation_history.csv"
VALUATION_HISTORY_COLUMNS = ["date", "timestamp", "total_value_eur", "cash_eur", "invested_value_eur",
                             "unrealized_pl_eur", "daily_gain_eur", "weekly_gain_eur",
                             "monthly_gain_eur", "yearly_gain_eur"]


def save_portfolio(holdings: pd.DataFrame, path: str | Path = PORTFOLIO_FILE) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    clean = holdings_to_dataframe(holdings.to_dict("records"))
    destination.write_text(json.dumps(clean.to_dict("records"), indent=2, ensure_ascii=False), encoding="utf-8")
    return destination


def load_portfolio(path: str | Path = PORTFOLIO_FILE, fallback=None) -> pd.DataFrame:
    source = Path(path)
    records = json.loads(source.read_text(encoding="utf-8")) if source.exists() else (fallback or [])
    return holdings_to_dataframe(records) if records else pd.DataFrame(columns=HOLDING_COLUMNS)


def save_uploaded_file(filename: str, contents: bytes, upload_dir: str | Path = UPLOAD_DIR) -> Path:
    folder = Path(upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    destination = folder / safe_name
    destination.write_bytes(contents)
    return destination


def load_valuation_history(path: str | Path = VALUATION_HISTORY_FILE) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=VALUATION_HISTORY_COLUMNS)
    frame = pd.read_csv(source)
    for column in VALUATION_HISTORY_COLUMNS:
        if column not in frame:
            frame[column] = "" if column in {"date", "timestamp"} else 0.0
    return frame[VALUATION_HISTORY_COLUMNS]


def save_valuation_snapshot(snapshot: dict, path: str | Path = VALUATION_HISTORY_FILE) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    history = load_valuation_history(destination)
    row = {column: snapshot.get(column, "" if column in {"date", "timestamp"} else 0.0)
           for column in VALUATION_HISTORY_COLUMNS}
    # One closing snapshot per local calendar day; saving again replaces today's row.
    history = history[history["date"].astype(str) != str(row["date"])]
    history = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
    history.to_csv(destination, index=False)
    return destination


def clear_valuation_history(path: str | Path = VALUATION_HISTORY_FILE) -> None:
    source = Path(path)
    if source.exists():
        source.unlink()
