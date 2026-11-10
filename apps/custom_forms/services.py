import copy
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError, RestrictedError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.models import AccountAudit
from apps.accounts.permissions import is_portal_admin
from apps.tickets.models import Ticket
from apps.tickets.services import create_ticket
from apps.tickets.uploads import private_storage, save_attachment

from .globals import global_kind
from .models import FormDefinition, FormSubmission
from .schema import validate_fields


def authorize(actor):
    if not is_portal_admin(actor):
        raise PermissionDenied


def available_forms(user):
    rows = FormDefinition.objects.filter(status=FormDefinition.Status.PUBLISHED, trashed_at__isnull=True)
    if not user.is_authenticated or not user.is_active:
        return rows.none()
    permitted = Q(audience_restricted=False) | Q(allowed_groups__in=user.groups.all())
    if is_portal_admin(user):
        # Administrative access to ordinary forms never bypasses sensitive audiences.
        permitted |= Q(is_sensitive=False)
    return rows.filter(permitted).distinct()


def standard_support(user):
    definition = FormDefinition.objects.filter(provision_key="support").first()
    if definition is None or (definition.trashed_at is None and definition.status == FormDefinition.Status.DRAFT
                              and definition.published_version == 0):
        return "legacy", None
    if available_forms(user).filter(pk=definition.pk).exists():
        return "custom", definition
    return "unavailable", None


def audit(actor, action, definition):
    AccountAudit.objects.create(actor=actor, action=action, changes={
        "form_id": str(definition.pk), "revision": definition.revision, "version": definition.published_version})


def locked(form_id, revision):
    definition = get_object_or_404(FormDefinition.objects.select_for_update(), pk=form_id)
    if definition.revision != revision:
        raise ValidationError("O formulário foi alterado em outra sessão. Recarregue a página antes de salvar.")
    return definition


def snapshot(definition):
    return {"title": definition.title, "description": definition.description, "icon": definition.icon,
            "display_order": definition.display_order, "version": definition.published_version,
            "fields": validate_fields(definition.fields), "is_sensitive": definition.is_sensitive}


def _publish(definition):
    if definition.trashed_at:
        raise ValidationError("Restaure o formulário da lixeira antes de publicá-lo.")
    fields = validate_fields(definition.fields)
    if definition.status == FormDefinition.Status.ARCHIVED:
        raise ValidationError("Formulário arquivado. Duplique-o para criar uma nova solicitação.")
    if definition.provision_key == "offboarding":
        definition.is_sensitive = True
    if definition.is_sensitive and not definition.draft_audience:
        raise ValidationError("Solicitação sensível exige grupos explícitos de acesso antes de publicar.")
    access_group_ids = set(definition.draft_audience)
    if definition.is_sensitive:
        # Keep legacy "approver" groups as access-only destinations for TI.
        access_group_ids.update(definition.draft_approver_groups)
    groups = list(Group.objects.filter(pk__in=access_group_ids))
    if len(groups) != len(access_group_ids):
        raise ValidationError("Um grupo selecionado não existe mais. Revise a disponibilidade.")
    definition.published_version += 1
    definition.fields = fields
    definition.published_snapshot = snapshot(definition)
    definition.status = FormDefinition.Status.PUBLISHED
    definition.audience_restricted = bool(definition.draft_audience)
    definition.allowed_groups.set(groups)


@transaction.atomic
def publish_form(*, actor, form_id, revision):
    authorize(actor)
    definition = locked(form_id, revision)
    _publish(definition)
    definition.revision += 1
    definition.save()
    audit(actor, "FORM_PUBLISHED", definition)
    return definition


@transaction.atomic
def save_definition(*, actor, form_id, cleaned, publish=False):
    authorize(actor)
    definition = locked(form_id, cleaned["revision"]) if form_id else FormDefinition()
    if definition.trashed_at:
        raise ValidationError("Restaure o formulário da lixeira antes de editá-lo.")
    if definition.status == FormDefinition.Status.ARCHIVED:
        raise ValidationError("Formulário arquivado. Duplique-o para editar uma nova versão.")
    for name in ("title", "description", "icon", "display_order"):
        setattr(definition, name, cleaned[name])
    definition.is_sensitive = definition.is_sensitive or definition.provision_key == "offboarding"
    definition.fields = validate_fields(cleaned["fields"])
    definition.draft_audience = [group.pk for group in cleaned["audience"]]
    definition.revision += 1 if form_id else 0
    definition.full_clean(exclude=["allowed_groups", "fields", "draft_audience", "draft_approver_groups", "published_snapshot"])
    definition.save()
    audit(actor, "FORM_UPDATED" if form_id else "FORM_CREATED", definition)
    if publish:
        _publish(definition)
        definition.save()
        audit(actor, "FORM_PUBLISHED", definition)
    return definition


@transaction.atomic
def perform_action(*, actor, form_id, revision, action):
    authorize(actor)
    definition = locked(form_id, revision)
    if action == "delete":
        # Compatibility: the old shortcut may never bypass explicit permanent deletion.
        action = "trash"
    if definition.trashed_at:
        if action != "restore":
            raise ValidationError("O formulário está na lixeira. Restaure-o antes de alterar suas configurações.")
        definition.status = FormDefinition.Status.DRAFT
        definition.trashed_at = None
        definition.trashed_by = None
        definition.trashed_by_label = ""
        definition.revision += 1
        definition.save()
        audit(actor, "FORM_RESTORED", definition)
        return definition
    if action == "restore":
        raise ValidationError("Somente formulários na lixeira podem ser restaurados.")
    if action == "trash":
        definition.trashed_at = timezone.now()
        definition.trashed_by = actor
        definition.trashed_by_label = (actor.get_full_name() or actor.get_username())[:300]
        definition.revision += 1
        definition.save()
        audit(actor, "FORM_TRASHED", definition)
        return definition
    if action == "duplicate":
        clone = FormDefinition.objects.create(title=f"{definition.title[:110]} (cópia)",
            description=definition.description, icon=definition.icon, display_order=definition.display_order,
            fields=copy.deepcopy(definition.fields), draft_audience=list(definition.draft_audience),
            is_sensitive=definition.is_sensitive, draft_approver_groups=list(definition.draft_approver_groups))
        audit(actor, "FORM_DUPLICATED", clone)
        return clone
    if action == "archive":
        definition.status = FormDefinition.Status.ARCHIVED
    elif action == "unarchive" and definition.status == FormDefinition.Status.ARCHIVED:
        definition.status = FormDefinition.Status.DRAFT
    elif action == "unpublish" and definition.status == FormDefinition.Status.PUBLISHED:
        definition.status = FormDefinition.Status.DRAFT
    else:
        raise ValidationError("Ação indisponível para este formulário.")
    definition.revision += 1
    definition.save()
    labels = {"archive": "FORM_ARCHIVED", "unarchive": "FORM_UNARCHIVED", "unpublish": "FORM_UNPUBLISHED"}
    audit(actor, labels[action], definition)
    return definition


def deletion_blockers(definition):
    """Fail closed for every reverse dependency, including future CASCADE/SET_NULL links.

    The definition's own forward M2M to groups is configuration and may be removed;
    the group rows themselves are never deleted. Submissions retain all ticket/file links.
    """
    if definition.submissions.exists():
        return ["Há chamados ou respostas vinculados. Seus snapshots e anexos devem ser preservados."]
    owned_through_models = {field.remote_field.through for field in definition._meta.local_many_to_many
                            if field.remote_field.through._meta.auto_created}
    for relation in definition._meta.get_fields(include_hidden=True):
        if (not relation.auto_created or relation.concrete or relation.related_model in owned_through_models
                or not (relation.one_to_many or relation.one_to_one or relation.many_to_many)):
            continue
        if relation.related_model._base_manager.filter(**{relation.field.name: definition}).exists():
            return ["Há outras dependências vinculadas que precisam ser preservadas."]
    return []


@transaction.atomic
def permanently_delete_form(*, actor, form_id, revision, confirmation_name, confirm):
    authorize(actor)
    definition = locked(form_id, revision)
    if not definition.trashed_at:
        raise ValidationError("Mova o formulário para a lixeira antes de excluir definitivamente.")
    if confirmation_name != definition.title or confirm is not True:
        raise ValidationError("Digite o nome exato e confirme explicitamente a exclusão definitiva.")
    blockers = deletion_blockers(definition)
    if blockers:
        raise ValidationError(blockers)
    audit(actor, "FORM_PERMANENTLY_DELETED", definition)
    try:
        definition.delete()
    except (ProtectedError, RestrictedError):
        raise ValidationError("Exclusão bloqueada por dependências que precisam ser preservadas.") from None


def submit_request(*, actor, form_id, cleaned):
    saved_keys = []
    try:
        with transaction.atomic():
            get_user_model().objects.select_for_update(no_key=True).get(pk=actor.pk)
            definition = get_object_or_404(FormDefinition.objects.select_for_update(), pk=form_id)
            if not available_forms(actor).filter(pk=form_id).exists():
                raise Http404
            key = cleaned.get("submission_key")
            previous = Ticket.objects.filter(submission_key=key).first() if key else None
            if previous:
                if (previous.requester_id != actor.pk or previous.archived_at or previous.planner_deleted_at
                        or not FormSubmission.objects.filter(ticket=previous, definition=definition).exists()):
                    raise ValidationError("Envio já utilizado. Abra uma nova solicitação.")
                return previous
            if definition.published_version != cleaned["form_version"]:
                raise ValidationError("O formulário foi atualizado. Recarregue esta página e confira os campos antes de enviar.")
            published = copy.deepcopy(definition.published_snapshot)
            from apps.sectors.models import Company, Sector

            # Match standard intake's company -> sector lock order.
            company = Company.objects.select_for_update().filter(pk=cleaned["company"].pk, is_active=True).first()
            if company is None:
                raise ValidationError({"company": "Selecione uma empresa ativa."})

            selected = {cleaned["sector"].pk}
            selected.update(cleaned[f"cf_{field['id']}"].pk for field in published["fields"]
                if field["type"] == "sector" and not global_kind(field) and cleaned.get(f"cf_{field['id']}") is not None)
            locked_sectors = list(Sector.objects.select_for_update().filter(pk__in=selected, is_active=True).order_by("pk"))
            if len(locked_sectors) != len(selected):
                raise ValidationError("Um setor selecionado foi desativado. Recarregue o formulário.")
            ticket = create_ticket(actor=actor, title=cleaned["title"], priority=cleaned["priority"],
                description=f"Solicitação pelo formulário {published['title']}. As respostas estão disponíveis no portal.",
                submission_key=key, company=company, sector=cleaned["sector"],
                is_sensitive=published.get("is_sensitive", False),
                restricted_group_ids=list(definition.allowed_groups.values_list("pk", flat=True)))
            answers = {}
            for field in published["fields"]:
                role = global_kind(field)
                value = cleaned.get(role) if role else cleaned.get(f"cf_{field['id']}")
                if role == "sector" or field["type"] == "sector":
                    if value is not None:
                        current_sector = Sector.objects.select_for_update().filter(pk=value.pk, is_active=True).first()
                        if current_sector is None:
                            raise ValidationError("O setor selecionado foi desativado. Recarregue o formulário.")
                        value = {"id": current_sector.pk, "name": current_sector.name}
                if field["type"] == "attachment" and value:
                    attachment = save_attachment(ticket=ticket, actor=actor, upload=value)
                    saved_keys.append(attachment.storage_key)
                    value = str(attachment.pk)
                elif isinstance(value, (date, Decimal)):
                    value = str(value)
                answers[field["id"]] = value
            FormSubmission.objects.create(ticket=ticket, definition=definition,
                schema_snapshot=published, answers=answers)
            return ticket
    except Exception:
        for key in saved_keys:
            private_storage().delete(key)
        raise


def answer_rows(submission, attachments):
    rows = []
    for field in submission.schema_snapshot["fields"]:
        if global_kind(field):
            continue
        value = submission.answers.get(field["id"])
        attachment = None
        if field["type"] == "attachment":
            attachment = next((a for a in attachments if str(a.pk) == value), None)
            value = attachment.original_name if attachment else "Não informado"
        elif field["type"] == "checkbox":
            value = "Sim" if value else "Não"
        elif isinstance(value, list):
            value = ", ".join(value)
        elif isinstance(value, dict) and "name" in value:
            value = value["name"]
        rows.append({"label": field["label"], "value": value if value not in (None, "") else "Não informado",
                     "attachment": attachment})
    return rows
