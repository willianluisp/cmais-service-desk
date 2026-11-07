import uuid
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.accounts.models import AccountAudit
from apps.custom_forms.models import FormDefinition

pytestmark = pytest.mark.django_db


@pytest.fixture
def preset_admin(django_user_model):
    actor = django_user_model.objects.create_user("fictional-preset-admin")
    actor.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    return actor


def test_preset_command_creates_only_seven_audited_drafts(preset_admin):
    call_command("provision_cmais_forms", actor=preset_admin.username, stdout=StringIO())
    rows = list(FormDefinition.objects.order_by("display_order"))
    assert [row.provision_key for row in rows] == [
        "support", "access", "printers", "microsoft365", "equipment", "software", "offboarding",
    ]
    assert all(row.status == "DRAFT" and row.published_version == 0 for row in rows)
    assert all(not row.published_snapshot and not row.allowed_groups.exists() for row in rows)
    audits = AccountAudit.objects.filter(action="FORM_PROVISIONED", actor=preset_admin)
    assert audits.count() == 7
    assert {entry.changes["form_id"] for entry in audits} == {str(row.pk) for row in rows}
    offboarding = rows[-1]
    assert offboarding.is_sensitive
    assert offboarding.draft_audience == offboarding.draft_approver_groups == []
    assert offboarding.audience_restricted
    assert not any(row.is_sensitive for row in rows[:-1])


def test_preset_rerun_preserves_every_existing_record(preset_admin):
    call_command("provision_cmais_forms", actor=preset_admin.username, stdout=StringIO())
    for index, row in enumerate(FormDefinition.objects.order_by("display_order")):
        row.title = f"Edited fictional title {index}"
        row.fields = []
        row.status = "ARCHIVED" if index % 2 else "PUBLISHED"
        row.trashed_at = timezone.now() if index % 2 else None
        row.revision = 23
        row.save()
    before = list(FormDefinition.objects.order_by("pk").values())
    call_command("provision_cmais_forms", actor=preset_admin.username, stdout=StringIO())
    assert list(FormDefinition.objects.order_by("pk").values()) == before
    assert AccountAudit.objects.filter(action="FORM_PROVISIONED").count() == 7


def test_preset_rerun_only_recreates_missing_keys(preset_admin):
    call_command("provision_cmais_forms", actor=preset_admin.username, stdout=StringIO())
    FormDefinition.objects.get(provision_key="printers").delete()
    before = list(FormDefinition.objects.order_by("pk").values())
    call_command("provision_cmais_forms", actor=preset_admin.username, stdout=StringIO())
    assert list(FormDefinition.objects.exclude(provision_key="printers").order_by("pk").values()) == before
    assert FormDefinition.objects.count() == 7
    assert AccountAudit.objects.filter(action="FORM_PROVISIONED").count() == 8


def test_preset_failure_rolls_back_forms_and_audits(preset_admin, monkeypatch):
    from django.core.exceptions import ValidationError

    from apps.custom_forms.management.commands import provision_cmais_forms
    from apps.custom_forms.presets import get_cmais_presets

    presets = get_cmais_presets()
    presets[-1]["fields"][0]["type"] = "unsafe-invalid-kind"
    monkeypatch.setattr(provision_cmais_forms, "get_cmais_presets", lambda: presets)
    with pytest.raises(ValidationError):
        call_command("provision_cmais_forms", actor=preset_admin.username, stdout=StringIO())
    assert not FormDefinition.objects.exists()
    assert not AccountAudit.objects.exists()


def test_preset_dry_run_does_not_create_forms_audits_or_groups(preset_admin):
    groups_before = Group.objects.count()
    output = StringIO()
    call_command("provision_cmais_forms", actor=preset_admin.username, dry_run=True, stdout=output)
    assert not FormDefinition.objects.exists()
    assert not AccountAudit.objects.exists()
    assert Group.objects.count() == groups_before
    assert "7" in output.getvalue()


@pytest.mark.parametrize("mode", ["missing", "unknown", "employee", "inactive"])
def test_preset_command_requires_active_authorized_actor(mode, django_user_model):
    options = {"stdout": StringIO()}
    if mode == "unknown":
        options["actor"] = "nonexistent-fictional-actor"
    elif mode in {"employee", "inactive"}:
        actor = django_user_model.objects.create_user("fictional-employee", is_active=mode != "inactive")
        if mode == "inactive":
            actor.is_superuser = True
            actor.save()
        options["actor"] = actor.username
    with pytest.raises(CommandError):
        call_command("provision_cmais_forms", **options)
    assert not FormDefinition.objects.exists()
    assert not AccountAudit.objects.exists()


def test_superuser_can_provision_without_admin_group(django_user_model):
    actor = django_user_model.objects.create_user("fictional-superuser", is_superuser=True)
    call_command("provision_cmais_forms", actor=actor.username, stdout=StringIO())
    assert FormDefinition.objects.count() == 7


def test_preset_schemas_are_valid_stable_and_contain_only_specific_fields():
    from apps.custom_forms.presets import get_cmais_presets
    from apps.custom_forms.schema import validate_fields

    first = get_cmais_presets()
    assert first == get_cmais_presets()
    assert [len(item["fields"]) for item in first] == [5, 5, 4, 4, 5, 5, 8]
    identifiers = []
    for item in first:
        assert validate_fields(item["fields"]) == item["fields"]
        identifiers.extend(field["id"] for field in item["fields"])
    assert len(identifiers) == len(set(identifiers))
    assert all(uuid.UUID(identifier).version == 5 for identifier in identifiers)
    equipment = next(item for item in first if item["provision_key"] == "equipment")
    assert equipment["fields"][1]["type"] == "integer"
    offboarding = first[-1]
    assert offboarding["fields"][1]["type"] == "sector"
    assert offboarding["fields"][3]["type"] == "datetime"
    first[0]["fields"].clear()
    assert len(get_cmais_presets()[0]["fields"]) == 5
