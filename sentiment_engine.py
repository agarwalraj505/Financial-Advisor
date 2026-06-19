"""Explainable lexicon sentiment and market-regime summaries."""

from __future__ import annotations

POSITIVE = {"gain", "growth", "strong", "record", "rally", "upgrade", "beat", "optimism", "cut rates", "cooling inflation"}
NEGATIVE = {"loss", "weak", "fall", "decline", "downgrade", "miss", "risk", "recession", "war", "inflation surge"}


def classify_sentiment(text: str) -> dict:
    lower = str(text or "").lower()
    positive = sum(term in lower for term in POSITIVE); negative = sum(term in lower for term in NEGATIVE)
    score = (positive - negative) / max(1, positive + negative)
    label = "Bullish" if score > .45 else "Mildly bullish" if score > .1 else "Bearish" if score < -.45 else "Cautious" if score < -.1 else "Neutral"
    confidence = "High" if positive + negative >= 4 else "Medium" if positive + negative >= 2 else "Low"
    return {"sentiment": label, "score": round(score, 3), "confidence": confidence,
            "explanation": f"Detected {positive} positive and {negative} negative evidence terms."}


def score_news_sentiment(news_items: list[dict]) -> dict:
    if not news_items:
        return {"sentiment": "Neutral", "score": 0.0, "confidence": "Low",
                "explanation": "No usable news was available; strategy should not change from news alone."}
    results = [classify_sentiment(item.get("title", "") + " " + item.get("summary", "")) for item in news_items]
    score = sum(item["score"] for item in results) / len(results)
    label = "Bullish" if score > .35 else "Mildly bullish" if score > .08 else "Bearish" if score < -.35 else "Cautious" if score < -.08 else "Neutral"
    confidence = "High" if len(results) >= 15 else "Medium" if len(results) >= 5 else "Low"
    return {"sentiment": label, "score": round(score, 3), "confidence": confidence,
            "explanation": f"Aggregate of {len(results)} deduplicated public-news items."}


def score_theme_sentiment(news_items: list[dict], theme: str) -> dict:
    relevant = [item for item in news_items if str(theme).lower() in
                (item.get("title", "") + " " + item.get("summary", "") + " " + item.get("category", "")).lower()]
    return score_news_sentiment(relevant)


def score_market_regime(market_data, news_sentiment: dict) -> dict:
    momentum = 0.0
    if hasattr(market_data, "empty") and not market_data.empty and "momentum_score" in market_data:
        momentum = float(market_data["momentum_score"].fillna(0).mean())
    combined = (momentum - 5) / 5 * .6 + float(news_sentiment.get("score", 0)) * .4
    regime = "Risk-on" if combined > .25 else "Constructive" if combined > .05 else "Risk-off" if combined < -.25 else "Cautious" if combined < -.05 else "Neutral"
    return {"market_regime": regime, "score": round(combined, 3),
            "confidence": news_sentiment.get("confidence", "Low"),
            "explanation": f"Combined average momentum {momentum:.2f}/10 with news sentiment."}


def create_market_sentiment_summary(news_items: list[dict], market_data) -> dict:
    news = score_news_sentiment(news_items); regime = score_market_regime(market_data, news)
    return {**news, **regime}
