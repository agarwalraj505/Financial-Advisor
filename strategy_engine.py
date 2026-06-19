"""Evidence-gated strategy refresh; no market view is fabricated from weak inputs."""

from __future__ import annotations

from datetime import datetime, timezone


def get_current_strategy(settings: dict, targets: dict, holdings=None, candidates=None) -> dict:
    return {"strategy_name": f"{settings.get('risk_profile', 'Aggressive')} diversified strategy",
            "market_regime": "Neutral", "risk_profile": settings.get("risk_profile", "Aggressive"),
            "target_allocations": dict(targets), "preferred_themes": [], "reduced_themes": [],
            "overweight_underweight_plan": "Follow allocation drift; do not force trades.",
            "current_risks": ["Free internet prices can be delayed", "Confirm costs and compatibility before new buys"],
            "savings_plan_priorities": [], "rebalance_rules": ["Do not force trades", "Prefer fee-efficient savings plans"],
            "reasoning": "Baseline strategy from saved targets and risk settings.", "confidence": "Medium",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def refresh_market_strategy(holdings, candidates, targets, news_sentiment, market_research, settings) -> dict:
    current = get_current_strategy(settings, targets, holdings, candidates)
    regime = news_sentiment.get("market_regime", "Neutral")
    confidence = news_sentiment.get("confidence", "Low")
    preferred, reduced = [], []
    if confidence in {"Medium", "High"} and hasattr(market_research, "empty") and not market_research.empty:
        grouped = market_research.groupby("category")["momentum_score"].mean() if "category" in market_research else {}
        if hasattr(grouped, "items"):
            preferred = [str(name) for name, score in grouped.items() if score >= 7.5]
            reduced = [str(name) for name, score in grouped.items() if score <= 3.0]
    current.update({"market_regime": regime, "preferred_themes": preferred, "reduced_themes": reduced,
                    "savings_plan_priorities": preferred,
                    "current_risks": (["Risk regime is cautious; avoid forced tactical trades"]
                                      if regime in {"Cautious", "Risk-off", "Bearish"}
                                      else current["current_risks"]),
                    "reasoning": news_sentiment.get("explanation", "Insufficient evidence for strategy changes."),
                    "confidence": confidence, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return current


def redesign_strategy(current_strategy: dict, market_regime: dict, portfolio_drift,
                      scored_assets, settings: dict) -> dict:
    output = dict(current_strategy)
    if market_regime.get("confidence") in {"Medium", "High"}:
        output["market_regime"] = market_regime.get("market_regime", output.get("market_regime"))
        output["reasoning"] = market_regime.get("explanation", output.get("reasoning"))
        output["confidence"] = market_regime.get("confidence")
    output["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return output


def create_strategy_explanation(strategy: dict) -> str:
    return (f"{strategy.get('strategy_name')} in a {strategy.get('market_regime')} regime. "
            f"Preferred themes: {', '.join(strategy.get('preferred_themes', [])) or 'none confirmed'}. "
            f"Confidence: {strategy.get('confidence', 'Low')}. {strategy.get('reasoning', '')}")


def save_strategy_snapshot(strategy: dict) -> dict:
    return dict(strategy)
