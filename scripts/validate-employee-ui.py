"""Visual checks against synthetic HTML; no portal DB or external requests.

Requires playwright Python and local Microsoft Edge. Capture HTML via
PORTAL_UI_CAPTURE_DIR when running tests/test_employee_experience.py.
"""

import base64
import json
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
captures = root / ".tmp" / "ui-preview"
output = root / ".tmp" / "ui-review"
output.mkdir(parents=True, exist_ok=True)
errors = []
screens = []
posts = []


def route_request(route):
    request = route.request
    path = urlsplit(request.url).path
    if request.method != "GET":
        posts.append(path)
        if "sincronizar" in path:
            return route.fulfill(status=503, body="Falha simulada")
        return route.fulfill(status=200, body=(captures / "detail-success.html").read_text(encoding="utf-8"), content_type="text/html")
    if path.startswith("/preview/"):
        name = path.split("/")[-1]
        if name not in {p.stem for p in captures.glob("*.html")}:
            return route.abort()
        return route.fulfill(body=(captures / f"{name}.html").read_text(encoding="utf-8"), content_type="text/html",
                             headers={"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'"})
    if path.startswith("/static/"):
        file = (root / path.lstrip("/")).resolve()
        if not file.is_relative_to(root / "static") or not file.is_file():
            return route.abort()
        return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(str(file))[0] or "application/octet-stream")
    return route.abort()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless=True)
    for size, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
        page = browser.new_page(viewport=viewport)
        page.route("**/*", route_request)
        page.on("pageerror", lambda error: errors.append(str(error)))
        for html in sorted(captures.glob("*.html")):
            page.goto(f"http://localhost:8010/preview/{html.stem}")
            page.wait_for_load_state("networkidle")
            assert page.locator("h1").count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"Horizontal overflow: {html.stem} {size}"
            page.screenshot(path=str(output / f"{html.stem}-{size}.png"), full_page=True)
            screens.append(f"{html.stem}-{size}")
        page.goto("http://localhost:8010/preview/create")
        before = len(posts)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
        page.locator('input[type="file"]').set_input_files([
            {"name": "imagem.png", "mimeType": "image/png", "buffer": png},
            {"name": "documento.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4\n%%EOF"},
        ])
        assert page.locator("#attachment-preview li").count() == 2
        page.get_by_role("button", name="Ampliar imagem imagem.png").focus()
        page.keyboard.press("Enter")
        assert page.locator("dialog").evaluate("element => element.open")
        assert page.locator("dialog img").evaluate("image => image.complete && image.naturalWidth > 0")
        page.screenshot(path=str(output / f"attachment-dialog-{size}.png"), full_page=True)
        page.keyboard.press("Escape")
        assert not page.locator("dialog").evaluate("element => element.open")
        assert page.get_by_role("button", name="Ampliar imagem imagem.png").evaluate("element => document.activeElement === element")
        page.get_by_role("button", name="Remover documento.pdf").click()
        assert page.locator('input[type="file"]').evaluate("input => input.files.length") == 1
        assert len(posts) == before, "Files were sent before confirmation"
        page.locator('input[name="title"]').fill("Solicitação simulada")
        assert page.locator('select[name="category"]').count() == 0
        page.locator('textarea[name="description"]').fill("Verificação de interface sem envio real.")
        page.locator("form[data-submit-feedback]").evaluate("form => form.addEventListener('submit', event => event.preventDefault())")
        page.get_by_role("button", name="Abrir chamado", exact=True).click()
        assert page.get_by_role("button", name="Enviando chamado…").is_disabled()
        assert page.locator("form[data-submit-feedback]").get_attribute("aria-busy") == "true"
        assert page.locator("form[data-submit-feedback]").evaluate("form => new FormData(form).getAll('attachments').length") == 1
        assert len(posts) == before
        page.goto("http://localhost:8010/preview/create")
        page.locator('input[type="file"]').set_input_files([
            {"name": f"arquivo-{i}.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4\n%%EOF"} for i in range(6)
        ])
        assert not page.locator('input[type="file"]').evaluate("input => input.validity.valid")
        assert page.locator("#attachment-preview li").count() == 6
        page.goto("http://localhost:8010/preview/detail-success")
        page.get_by_role("button", name="Atualizar status").click()
        page.wait_for_function("document.querySelector('#planner-feedback').textContent.includes('Não foi possível')")
        assert page.get_by_role("button", name="Atualizar status").is_enabled()
        page.close()
    browser.close()
assert not errors, errors
print(json.dumps({"screenshots": len(screens) + 2, "viewports": ["1440x1000", "390x844"],
                  "js_errors": errors, "previews_keyboard_removal_limits": "passed",
                  "external_requests": 0, "real_posts": 0}, ensure_ascii=False))
sys.exit(0)
