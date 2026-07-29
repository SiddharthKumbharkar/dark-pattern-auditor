"""File path management for recorded journey artifacts (Layer 2).

Artifacts live under storage_dir/<audit_id>/ (the "episode folder") so
concurrent or sequential audits never collide on the same step filenames,
and a stored episode's screenshots/dom/manifest travel together.
"""

import os


class ArtifactStore:
    def __init__(self, storage_dir: str, audit_id: str):
        self.storage_dir = storage_dir
        self.audit_id = audit_id
        self.episode_dir = os.path.join(storage_dir, audit_id)
        self.screenshots_dir = os.path.join(self.episode_dir, "screenshots")
        self.dom_dir = os.path.join(self.episode_dir, "dom")
        self.ocr_dir = os.path.join(self.episode_dir, "ocr")

    def screenshot_path(self, step_id: int) -> str:
        return os.path.join(self.screenshots_dir, f"step_{step_id:03d}.png")

    def dom_path(self, step_id: int) -> str:
        return os.path.join(self.dom_dir, f"step_{step_id:03d}.html")

    def ocr_path(self, step_id: int) -> str:
        return os.path.join(self.ocr_dir, f"step_{step_id:03d}_ocr.txt")
