"""Public/no-key news source configuration and supported market themes."""

RSS_SOURCES = [
    ("ECB", "https://www.ecb.europa.eu/rss/press.html", "ECB/rates"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "Fed/rates"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "Crypto"),
]

MARKET_THEMES = ["Global markets", "US equities", "Europe", "Germany", "ECB/rates", "Fed/rates",
                 "AI", "Semiconductors", "Cybersecurity", "Defence", "Emerging markets", "India",
                 "China", "Gold", "Silver", "Commodities", "Crypto"]

GDELT_QUERY = '(economy OR markets OR stocks OR "central bank" OR AI OR semiconductor OR defence OR gold OR crypto)'

