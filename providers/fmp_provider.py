"""Optional FMP adapter; disabled quietly when no key exists."""

from providers.base import BaseProvider


class FMPProvider(BaseProvider):
    name = "FMP"
    purpose = "Fundamentals"
    key_name = "FMP_API_KEY"
    key_required = True

    def get_fundamentals(self, symbol: str):
        return self.failure("FMP disabled: optional key not configured") if not self.enabled else self.failure("FMP adapter reserved for future use")
