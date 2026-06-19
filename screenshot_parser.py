"""Manual-confirmation parser for pasted Scalable screenshot text."""

from __future__ import annotations

from datetime import datetime, timezone
import re


def normalize_euro_number(value) -> float | None:
    text = str(value or "").strip().replace("€", "").replace("%", "")
    text = re.sub(r"(?i)/\s*share|shares?|stück", "", text).strip().replace(" ", "")
    text = text.replace("+", "")
    if not text: return None
    if "," in text and "." in text: text = text.replace(".", "").replace(",", ".")
    elif "," in text: text = text.replace(",", ".")
    try: return float(text)
    except ValueError: return None


def calculate_spread_from_bid_ask(sell_price, buy_price) -> dict:
    sell, buy = float(sell_price or 0), float(buy_price or 0)
    spread = max(0.0, buy - sell); midpoint = (buy + sell) / 2
    return {"spread_eur": round(spread, 6), "spread_percent": round(spread / midpoint * 100, 4) if midpoint else 0.0}


def _label_number(text: str, labels: list[str]):
    pattern = r"(?:" + "|".join(labels) + r")\s*[:\-]?\s*([+\-]?[0-9\.]+(?:,[0-9]+)?\s*(?:€|%|/\s*Share)?)"
    match = re.search(pattern, text, re.I)
    return normalize_euro_number(match.group(1)) if match else None


def parse_scalable_text(text: str) -> dict:
    text = str(text or "")
    isin = re.search(r"\b[A-Z]{2}[A-Z0-9]{10}\b", text)
    wkn = re.search(r"\bWKN\s*[:\-]?\s*([A-Z0-9]{6})\b", text, re.I)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    data = {"instrument": lines[0] if lines else "", "isin": isin.group(0) if isin else "",
            "wkn": wkn.group(1).upper() if wkn else "",
            "quantity": _label_number(text, ["Number of shares", "Quantity", "Anzahl", "Stück"]),
            "current_value_eur": _label_number(text, ["Current position value", "Position value", "Aktueller Wert", "Wert"]),
            "buy_in_value_eur": _label_number(text, ["Buy-in value", "Einstandswert"]),
            "current_price_eur": _label_number(text, ["Current price per share", "Current price", "Aktueller Preis"]),
            "buy_in_price_eur": _label_number(text, ["Buy-in price per share", "Buy-in price", "Einstandskurs"]),
            "pl_eur": _label_number(text, ["Absolute P/L", "Profit/Loss", "Rendite absolut"]),
            "pl_pct": _label_number(text, ["Relative P/L", "Rendite relativ", "Performance"]),
            "sell_price_eur": _label_number(text, ["Sell price", "Verkaufen"]),
            "buy_price_eur": _label_number(text, ["Buy price", "Kaufen"]),
            "screenshot_captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "Scalable screenshot"}
    data.update(calculate_spread_from_bid_ask(data["sell_price_eur"], data["buy_price_eur"]))
    return data


def create_holding_from_screenshot_data(data: dict) -> dict:
    quantity = float(data.get("quantity") or 0); value = float(data.get("current_value_eur") or 0)
    return {"instrument": data.get("instrument", ""), "isin": data.get("isin", ""), "wkn": data.get("wkn", ""),
            "quantity": quantity, "manual_current_price": data.get("current_price_eur") or (value / quantity if quantity else 0),
            "current_value_eur": value, "buy_in_value_eur": float(data.get("buy_in_value_eur") or 0),
            "pl_eur": float(data.get("pl_eur") or 0), "pl_pct": float(data.get("pl_pct") or 0),
            "sell_price_eur": data.get("sell_price_eur"), "buy_price_eur": data.get("buy_price_eur"),
            "spread_eur": data.get("spread_eur"), "spread_percent": data.get("spread_percent"),
            "screenshot_captured_at": data.get("screenshot_captured_at"), "source": "Scalable screenshot",
            "user_confirmed": False}


def validate_screenshot_holding(data: dict) -> list[str]:
    errors = []
    if not data.get("instrument"): errors.append("Instrument name missing")
    if not data.get("isin"): errors.append("ISIN missing")
    if not float(data.get("quantity") or 0): errors.append("Quantity missing")
    return errors


def update_holding_by_isin(holdings: list[dict], update: dict, confirmed_fields: set[str] | None = None) -> list[dict]:
    """Preserve category/type/symbol unless explicitly confirmed."""
    protected = {"category", "asset_type", "price_symbol"}; confirmed_fields = confirmed_fields or set()
    output, found = [], False
    for holding in holdings:
        if update.get("isin") and holding.get("isin") == update.get("isin"):
            merged = dict(holding)
            for key, value in update.items():
                if key not in protected or key in confirmed_fields:
                    if value not in (None, ""): merged[key] = value
            output.append(merged); found = True
        else: output.append(dict(holding))
    if not found: output.append(dict(update))
    return output
