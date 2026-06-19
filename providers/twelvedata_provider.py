"""Optional Twelve Data adapter; disabled quietly when no key exists."""

from providers.base import BaseProvider


class TwelveDataProvider(BaseProvider):
    name = "Twelve Data"
    purpose = "Backup prices"
    key_name = "TWELVE_DATA_API_KEY"
    key_required = True

    def get_price(self, symbol: str):
        return self.failure("Twelve Data disabled: optional key not configured") if not self.enabled else self.failure("Twelve Data adapter reserved for future use")
