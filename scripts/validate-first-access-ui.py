"""Browser checks against synthetic first-access HTML, with all requests intercepted."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
html = (root / ".tmp/first-access-ui/welcome.html").read_text(encoding="utf-8")
output = root / ".tmp/first-access-review"
output.mkdir(parents=True, exist_ok=True)
errors = []


def route_request(route):
    path = urlsplit(route.request.url).path
    assert route.request.method == "GET", "No password submission permitted during visual review"
    if path == "/preview/welcome":
        return route.fulfill(body=html, content_type="text/html")
    if path.startswith("/static/"):
        file = (root / path.lstrip("/")).resolve()
        if file.is_relative_to(root / "static") and file.is_file():
            return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(str(file))[0] or "application/octet-stream")
    return route.abort()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless=True)
    for name, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
        page = browser.new_page(viewport=viewport)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", route_request)
        page.goto("http://localhost:8010/preview/welcome")
        dialog = page.locator("#first-access-dialog")
        assert dialog.evaluate("element => element.matches(':modal')")
        bounds = dialog.bounding_box()
        assert abs(bounds["x"] + bounds["width"] / 2 - viewport["width"] / 2) < 2
        assert abs(bounds["y"] + bounds["height"] / 2 - viewport["height"] / 2) < 2
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.keyboard.press("Escape")
        assert dialog.evaluate("element => element.open")
        page.mouse.click(2, 2)
        assert dialog.evaluate("element => element.open")
        first = page.locator('[name="new_password1"]')
        second = page.locator('[name="new_password2"]')
        first.fill("Lago!Horizonte-8437")
        page.locator('[data-password-toggle="id_new_password1"]').click()
        assert first.get_attribute("type") == "text"
        page.locator('[data-password-toggle="id_new_password1"]').click()
        assert first.get_attribute("type") == "password"
        second.fill("different")
        assert not second.evaluate("input => input.validity.valid")
        second.fill("Lago!Horizonte-8437")
        assert page.locator("[data-rule].is-met").count() == 3
        # Empty fields in captures: do not expose even synthetic passwords.
        first.fill("")
        second.fill("")
        for _ in range(12):
            page.keyboard.press("Tab")
            assert page.evaluate("document.querySelector('#first-access-dialog').contains(document.activeElement)")
        dialog.evaluate("element => element.scrollTop = 0")
        page.screenshot(path=str(output / f"welcome-{name}.png"), full_page=True)
        page.close()
    page = browser.new_page(java_script_enabled=False, viewport={"width": 390, "height": 844})
    page.route("**/*", route_request)
    page.goto("http://localhost:8010/preview/welcome")
    assert page.locator('input[name="new_password1"]').is_visible()
    assert page.locator('button[type="submit"]').first.is_visible()
    page.screenshot(path=str(output / "welcome-no-js-mobile.png"), full_page=True)
    browser.close()
assert not errors, errors
print(json.dumps({"desktop": "passed", "mobile": "passed", "no_javascript": "passed", "escape_backdrop_focus_toggle_requirements": "passed", "javascript_errors": errors}))
