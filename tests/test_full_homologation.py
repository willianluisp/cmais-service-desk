"""Full portal flow with stateful, in-memory Microsoft doubles, never a tenant."""

import copy
from urllib.request import OpenerDirector

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.notifications.models import NotificationOutbox
from apps.notifications.services import DeliveryError, process_pending
from apps.planner_integration.client import PlannerError
from apps.planner_integration.models import AttachmentPublication, PlannerConfiguration
from apps.planner_integration.services import process_pending_provisioning, sync_ticket
from apps.tickets.models import Category, Ticket, TicketAccess

pytestmark = pytest.mark.django_db(transaction=True)


class MicrosoftSimulator:
    def __init__(self, mode):
        self.mode = mode
        self.create_calls = 0
        self.tasks = {}
        self.descriptions = {}
        self.read_timeout = False
        self.details_failed = False

    def create_task(self, *, plan_id, bucket_id, title):
        self.create_calls += 1
        assert plan_id == "simulated-plan" and bucket_id == "simulated-pending"
        if self.mode == "throttle" and self.create_calls == 1:
            raise PlannerError("THROTTLED", "Simulated 429", retry_after=60)
        task = {"id": "simulated-task", "planId": plan_id, "bucketId": bucket_id,
                "title": title, "percentComplete": 0, "@odata.etag": "1"}
        self.tasks[task["id"]] = task
        if self.mode == "timeout" and self.create_calls == 1:
            raise PlannerError("GRAPH_UNAVAILABLE", "Simulated timeout after acceptance")
        return copy.deepcopy(task)

    def list_plan_tasks(self, plan_id):
        return copy.deepcopy(list(self.tasks.values()))

    def update_task_details(self, task_id, *, description, etag):
        self.descriptions[task_id] = description
        if self.mode == "details" and not self.details_failed:
            self.details_failed = True
            raise PlannerError("GRAPH_UNAVAILABLE", "Simulated details PATCH timeout")

    def get_task(self, task_id):
        if self.read_timeout:
            raise PlannerError("GRAPH_UNAVAILABLE", "Simulated read outage")
        return copy.deepcopy(self.tasks[task_id])

    def get_task_details(self, task_id):
        return {"checklist": {"verify": {"title": "Verificação simulada", "isChecked": True}},
                "@odata.etag": "details", "references": {}}


@pytest.fixture
def environment(settings, monkeypatch, tmp_path, django_user_model):
    def forbid_network(*args, **kwargs):
        pytest.fail("Unexpected HTTP request: Microsoft is forbidden in homologation")

    monkeypatch.setattr(OpenerDirector, "open", forbid_network)
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    settings.PLANNER_PLAN_ID = "simulated-plan"
    settings.PORTAL_BASE_URL = "http://localhost:8010"
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    # Test-process settings only: all HTTP is blocked above, clients injected.
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.PLANNER_ENABLED = True
    settings.PLANNER_ATTACHMENTS_ENABLED = False
    settings.GRAPH_ATTACHMENTS_STORAGE_APPROVED = False
    settings.EMAIL_ENABLED = False
    PlannerConfiguration.objects.create(plan_id="simulated-plan", bucket_mapping={
        "PLANNER_INTAKE_BUCKET_ID": "simulated-pending",
        "PLANNER_IN_PROGRESS_BUCKET_ID": "simulated-working",
        "PLANNER_COMPLETED_BUCKET_ID": "simulated-finished",
    })
    owner = django_user_model.objects.create_user("homologation.owner", email="owner@example.test")
    other = django_user_model.objects.create_user("homologation.other", email="other@example.test")
    technician = django_user_model.objects.create_user("homologation.technician")
    technician.groups.add(Group.objects.get_or_create(name="TECNICO_TI")[0])
    category = Category.objects.create(name="Homologação descartável")
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    return owner, other, technician, category, client


@pytest.mark.parametrize("mode", ["throttle", "timeout", "details"])
def test_full_homologation_with_failures_and_recovery(environment, monkeypatch, settings, mode):
    owner, other, technician, category, client = environment
    simulator = MicrosoftSimulator(mode)
    client.get("/chamados/novo/")
    csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
    response = client.post("/chamados/novo/", {
        "title": "[SIMULAÇÃO] Estação sem acesso", "description": "Solicitação descartável sem dados reais.",
        "category": category.pk, "priority": "NORMAL",
        "attachments": SimpleUploadedFile("evidencia.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"),
    }, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 302
    ticket = Ticket.objects.get(requester=owner)
    assert ticket.description == "Solicitação descartável sem dados reais."
    assert ticket.category.name == 'Atendimento geral'
    assert ticket.planner_provisioning.state == "PENDING"
    assert ticket.attachments.count() == 1
    assert not AttachmentPublication.objects.exists()
    assert ticket.events.get(event_type="CREATED")
    assert "Aberto" in client.get(response.url).content.decode()
    assert NotificationOutbox.objects.count() == 1

    # 429 or an accepted POST followed by timeout; original ticket survives.
    process_pending_provisioning(graph_client=simulator)
    provisioning = ticket.planner_provisioning
    provisioning.refresh_from_db()
    assert provisioning.last_error_code in {"THROTTLED", "GRAPH_UNAVAILABLE"}
    assert provisioning.available_at > timezone.now()
    assert process_pending_provisioning(graph_client=simulator) == 0
    provisioning.available_at = timezone.now()
    provisioning.save(update_fields=["available_at"])
    process_pending_provisioning(graph_client=simulator)
    ticket.refresh_from_db()
    assert ticket.planner_task_id == "simulated-task"
    assert ticket.sync_state == "SYNCED"
    assert ticket.sync_error_code == ""
    assert len(simulator.tasks) == 1
    assert simulator.create_calls == (2 if mode == "throttle" else 1)
    assert process_pending_provisioning(graph_client=simulator) == 0
    description = simulator.descriptions["simulated-task"]
    assert ticket.number in description and ticket.description in description
    assert str(provisioning.correlation_id) in description
    assert "Este chamado possui 1 anexo. Consulte-o no C+ Service Desk." in description
    assert "evidencia.pdf" not in description
    assert "sharepoint" not in description.lower()

    monkeypatch.setattr("apps.planner_integration.services.configured_read_client", lambda: simulator)
    monkeypatch.setattr("apps.planner_integration.views.enforce_rate_limit", lambda *args: None)
    sync_url = f"/chamados/{ticket.pk}/sincronizar/"
    for bucket, percent, label in [
        ("simulated-pending", 0, "Aberto"),
        ("simulated-working", 40, "Em andamento"),
        ("simulated-finished", 100, "Finalizado"),
    ]:
        simulator.tasks["simulated-task"].update(bucketId=bucket, percentComplete=percent)
        if percent == 40:
            simulator.read_timeout = True
            previous = ticket.status
            assert client.post(sync_url, HTTP_X_CSRFTOKEN=csrf).status_code == 503
            ticket.refresh_from_db()
            assert ticket.status == previous
            simulator.read_timeout = False
        result = client.post(sync_url, HTTP_X_CSRFTOKEN=csrf, HTTP_HX_REQUEST="true")
        assert result.status_code == 200 and label in result.content.decode()
        assert label in client.get(f"/chamados/{ticket.pk}/").content.decode()
        assert label in client.get("/chamados/").content.decode()
        assert label in client.get("/").content.decode()
        event_count = ticket.events.count()
        notice_count = NotificationOutbox.objects.count()
        sync_ticket(actor=owner, ticket_id=ticket.pk, graph_client=simulator)
        assert ticket.events.count() == event_count
        assert NotificationOutbox.objects.count() == notice_count
    assert NotificationOutbox.objects.count() == 3
    assert {n.subject.rsplit(" — ", 1)[1] for n in NotificationOutbox.objects.all()} == {"Recebido", "Em andamento", "Finalizado"}

    # E-mail sink in memory; explicit 429 fails once, then three messages only.
    delivered = {}
    fail_once = [True]

    def simulated_mail(notice):
        if fail_once[0]:
            fail_once[0] = False
            raise DeliveryError("MAIL_THROTTLED", retry_after=60)
        assert notice.recipient == owner.email
        assert notice.idempotency_key not in delivered
        delivered[notice.idempotency_key] = notice.subject

    process_pending(limit=1, provider=simulated_mail)
    assert NotificationOutbox.objects.filter(last_error_code="MAIL_THROTTLED", state="PENDING").exists()
    NotificationOutbox.objects.filter(state="PENDING").update(available_at=timezone.now())
    process_pending(provider=simulated_mail)
    assert process_pending(provider=simulated_mail) == 0
    assert len(delivered) == NotificationOutbox.objects.filter(state="SENT").count() == 3

    attachment = ticket.attachments.get()
    file_url = f"/chamados/{ticket.pk}/anexos/{attachment.pk}/"
    downloaded = client.get(file_url)
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == b"%PDF-1.4\n%%EOF"
    for stranger in (other, technician):
        forbidden = Client()
        forbidden.force_login(stranger)
        TicketAccess.objects.create(ticket=ticket, user=stranger)
        assert ticket.number not in forbidden.get("/chamados/").content.decode()
        assert ticket.number not in forbidden.get("/").content.decode()
        assert forbidden.get(f"/chamados/{ticket.pk}/").status_code == 404
        assert forbidden.get(file_url).status_code == 404
        assert forbidden.post(sync_url).status_code == 404
    assert connection.settings_dict["NAME"] != "service_desk"
