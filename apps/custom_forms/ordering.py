from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import AccountAudit

from .models import FormCardOrder, FormDefinition
from .services import authorize


def order_rows():
    definitions = list(FormDefinition.objects.filter(trashed_at__isnull=True))
    support = next((d for d in definitions if d.provision_key == "support"), None)
    rows = [{"key": "standard", "title": support.title if support else "Suporte técnico", "status": "Padrão · posição reservada"}]
    rows += [{"key": str(d.pk), "title": d.title, "status": d.get_status_display()} for d in definitions if d != support]
    return rows


def order_state():
    state, _ = FormCardOrder.objects.get_or_create(pk=1)
    rows = order_rows()
    rank = {value: index for index, value in enumerate(state.items)}
    rows.sort(key=lambda row: rank.get(row["key"], len(rank)))
    return state, rows


def card_rank():
    state = FormCardOrder.objects.filter(pk=1).first()
    return {value: index for index, value in enumerate(state.items)} if state else {}


@transaction.atomic
def save_order(*, actor, revision, items):
    authorize(actor)
    FormCardOrder.objects.get_or_create(pk=1)
    state = FormCardOrder.objects.select_for_update().get(pk=1)
    if state.revision != revision:
        raise ValidationError("A ordem foi alterada em outra sessão. Recarregue antes de salvar.")
    list(FormDefinition.objects.select_for_update().filter(trashed_at__isnull=True).values_list("pk", flat=True))
    expected = {row["key"] for row in order_rows()}
    if (not isinstance(items, list) or any(not isinstance(item, str) for item in items)
            or len(items) != len(expected) or set(items) != expected):
        raise ValidationError("A lista de formulários mudou ou contém itens repetidos. Recarregue a ordenação.")
    state.items = items
    state.revision += 1
    state.save(update_fields=["items", "revision"])
    AccountAudit.objects.create(actor=actor, action="FORM_CARDS_REORDERED", changes={"revision": state.revision, "items": items})
