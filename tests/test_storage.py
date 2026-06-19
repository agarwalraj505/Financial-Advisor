from storage import ScreenshotStorage


class FakeGateway:
    def __init__(self):
        self.call = None

    def upload_private_file(self, bucket, path, contents, content_type):
        self.call = (bucket, path, contents, content_type)
        return path


def test_screenshot_upload_uses_private_user_folder_and_safe_name():
    gateway = FakeGateway()
    path = ScreenshotStorage(gateway, "user-hash").upload("../private screenshot.png", b"image", "image/png")
    assert path.startswith("user-hash/")
    assert path.endswith("private_screenshot.png")
    assert gateway.call[0] == "holdings-screenshots"
    assert gateway.call[2] == b"image"
