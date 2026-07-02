"""File path management for recorded journey artifacts (Layer 2)."""

import os


class ArtifactStore:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.screenshots_dir = os.path.join(storage_dir, "screenshots")
        self.dom_dir = os.path.join(storage_dir, "dom")
        self.ocr_dir = os.path.join(storage_dir, "ocr")

    def screenshot_path(self, step_id: int) -> str:
        return os.path.join(self.screenshots_dir, f"step_{step_id:03d}.png")

    def dom_path(self, step_id: int) -> str:
        return os.path.join(self.dom_dir, f"step_{step_id:03d}.html")

    def ocr_path(self, step_id: int) -> str:
        return os.path.join(self.ocr_dir, f"step_{step_id:03d}_ocr.txt")
