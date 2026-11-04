# Private Attachments Implementation Plan

> **For agentic workers:** implement task-by-task with test-first changes; do not commit, push or deploy.

**Goal:** Keep up to five validated 2 MB PDF/PNG/JPEG attachments private and persistent in Django, expose them only to the requester or `ADMIN_PORTAL`, and mention only their count in Planner task text.

**Architecture:** Reuse `Attachment`, `FileSystemStorage`, the existing private Docker volume and Django authorization boundary. Add a separate inline-preview response for approved MIME types, keep downloads forced, and stop creating SharePoint publication intents for new uploads. `visible_tickets()` remains requester-only except for active portal administrators.

**Tech Stack:** Django 5.2 templates, PostgreSQL, Docker named volumes, pytest, Ruff.

**Spec:** User request of 2026-11-03 in this chat.

## Global Constraints

- No SharePoint, public URLs, e-mail or automatic Planner processing.
- Do not alter the two existing `PENDING` rows or port 8000.
- No real Planner task in automated tests.
- Preserve existing attachment and database data.

## Review Focus

- IDOR across detail, preview and download endpoints.
- MIME/extension/signature mismatches and files over 2 MB.
- Inline responses executing active content or being cached publicly.
- Planner descriptions leaking file names or URLs.
- Docker volume persistence and restorable backup instructions.

### Task 1: Authorization and private responses

**Files:** `apps/tickets/permissions.py`, `apps/tickets/views.py`, `apps/tickets/urls.py`, `tests/test_tickets.py`, `tests/test_portal_admin_role.py`

- [ ] Add failing requester/admin/stranger tests for detail, download and preview.
- [ ] Grant read-only visibility only to authenticated active `ADMIN_PORTAL`/superusers.
- [ ] Add inline preview for PDF/PNG/JPEG with strict headers; retain forced download.
- [ ] Run focused authorization tests.

### Task 2: Intake and Planner projection

**Files:** `apps/tickets/uploads.py`, `apps/planner_integration/services.py`, `tests/test_tickets.py`, `tests/test_planner_intake.py`, `tests/test_planner_attachments.py`

- [ ] Add failing limit/type/count and Planner-description tests.
- [ ] Stop creating SharePoint publication intents for new attachments.
- [ ] Add the exact attachment-count notice without file names, file URLs or binary upload.
- [ ] Run focused intake/Planner tests with mocked Graph clients only.

### Task 3: Detail interface and backup documentation

**Files:** `templates/tickets/detail.html`, `static/css/portal.css`, `docs/access-and-attachments.md`, `docs/planner-attachments.md`, `README.md`, `tests/test_employee_experience.py`, `tests/test_compose.py`

- [ ] Add failing template and persistent-volume documentation tests where appropriate.
- [ ] Render image thumbnails and separate preview/download controls; render PDF metadata and preview link.
- [ ] Reuse existing C+ tokens and responsive spacing.
- [ ] Document named-volume backup/restore outside Git and OneDrive.

### Task 4: Verification

- [ ] Run focused tests after each task.
- [ ] Run full pytest suite, Ruff, Django check and migration check.
- [ ] Verify volume mount and live flags/counts read-only on 8010.
- [ ] Verify desktop/mobile rendering without altering production data.
