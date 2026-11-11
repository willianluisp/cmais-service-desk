"""Responsive detail layout on a disposable server; external requests blocked."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("RUN_TICKET_STATUS_BROWSER") != "1", reason="Opt-in isolated Edge UI test")
@pytest.mark.django_db(transaction=True)
def test_ticket_status_browser(live_server, client, django_user_model):
    from apps.tickets.models import Category, Ticket

    owner = django_user_model.objects.create_user("ticket-status-browser")
    ticket = Ticket.objects.create(
        number="SD-STATUS-UI", title="Solicitação fictícia", description="Banco descartável pytest.",
        requester=owner, category=Category.objects.create(name="Teste"),
        planner_task_id="task", planner_plan_id="plan",
        planner_assignee_ids=["11111111-1111-4111-8111-111111111111"],
        planner_assignee_names=["Ana Contadora"],
    )
    client.force_login(owner)
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ, "STATUS_UI_URL": live_server.url,
        "STATUS_UI_COOKIE_NAME": "sessionid", "STATUS_UI_TICKET": str(ticket.pk),
        "STATUS_UI_SESSION": client.cookies["sessionid"].value,
    }
    result = subprocess.run(
        [shutil.which("node"), str(root / "scripts/validate-ticket-status-ui.mjs")],
        cwd=root, env=environment, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
