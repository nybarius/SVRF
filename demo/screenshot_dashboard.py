"""Screenshot the dashboard built from the sample receipts, for the README.

    pip install playwright && playwright install chromium   # once, local only
    python3 demo/screenshot_dashboard.py                    # writes docs/img/dashboard*.png

Optional tooling: nothing in the test suite or CI needs a browser.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from svrf import dashboard  # noqa: E402


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright && playwright install chromium", file=sys.stderr)
        return 2
    out = ROOT / "docs" / "img"
    with tempfile.TemporaryDirectory() as tmp:
        index = dashboard.build(ROOT / "demo" / "sample-receipts", Path(tmp), title="SVRF merge train (sample data)")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 1150}, color_scheme="light",
                                    device_scale_factor=1.5)
            page.goto(index.as_uri())
            page.wait_for_timeout(300)
            page.screenshot(path=str(out / "dashboard.png"))
            page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="dark",
                                    device_scale_factor=1.5)
            page.goto(index.as_uri())
            page.wait_for_timeout(300)
            top = page.locator("#timeline").bounding_box()
            bottom = page.locator("#bisection").bounding_box()
            page.screenshot(path=str(out / "dashboard-bisection-dark.png"), full_page=True,
                            clip={"x": top["x"] - 16, "y": top["y"] - 16, "width": top["width"] + 32,
                                  "height": bottom["y"] + bottom["height"] - top["y"] + 32})
            browser.close()
    for name in ("dashboard.png", "dashboard-bisection-dark.png"):
        print(out / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
