"""Full-page screenshot capture from a live Playwright page."""

from playwright.sync_api import Page


def capture_screenshot(page: Page, output_path: str) -> str:
    if not output_path.endswith(".png"):
        raise ValueError(f"output_path must end in .png, got: {output_path}")

    page.screenshot(path=output_path, full_page=True)
    return output_path
