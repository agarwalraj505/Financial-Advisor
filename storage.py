"""Private screenshot storage backed by Supabase Storage."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4


class ScreenshotStorage:
    def __init__(self, gateway, user_id: str, bucket: str = "holdings-screenshots"):
        self.gateway, self.user_id, self.bucket = gateway, user_id, bucket

    def upload(self, filename: str, contents: bytes, content_type: str = "image/png") -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
        path = f"{self.user_id}/{uuid4()}-{safe}"
        return self.gateway.upload_private_file(self.bucket, path, contents, content_type)
