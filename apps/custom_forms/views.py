import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.planner_integration.admin_panel import administrator

from .forms import DefinitionForm, PermanentDeleteForm, RequestForm
from .globals import global_kind
from .models import FormDefinition
from .ordering import card_rank, order_state, save_order
from .schema import FIELD_TYPES, ICONS
from .services import (
    available_forms,
    deletion_blockers,
    perform_action,
    permanently_delete_form,
    save_definition,
    standard_support,
    submit_request,
)


@require_GET
@never_cache
@administrator
def manage(request):
    rows = FormDefinition.objects.filter(trashed_at__isnull=True).annotate(usage_count=Count("submissions"))
    status = request.GET.get("status", "")
    if status in FormDefinition.Status.values:
        rows = rows.filter(status=status)
    return render(request, "custom_forms/manage.html", {"definitions": rows, "statuses": FormDefinition.Status.choices,
        "selected_status": status, "active_page": "forms"})


@require_http_methods(["GET", "POST"])
@never_cache
@administrator
def editor(request, pk=None):
    definition = get_object_or_404(FormDefinition, pk=pk, trashed_at__isnull=True) if pk else None
    initial = {"revision": definition.revision if definition else 0,
               "fields": definition.fields if definition else [],
               "audience": definition.draft_audience if definition else [],
               "is_sensitive": definition.is_sensitive if definition else False}
    form = DefinitionForm(request.POST if request.method == "POST" else None, instance=definition, initial=initial)
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "save")
        if action not in ("save", "publish"):
            return HttpResponseBadRequest("Ação inválida.")
        try:
            saved = save_definition(actor=request.user, form_id=pk, cleaned=form.cleaned_data, publish=action == "publish")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Formulário publicado." if action == "publish" else "Rascunho salvo. A publicação anterior permanece disponível até uma nova publicação.")
            return redirect("custom_forms:edit", pk=saved.pk)
    fields = form.cleaned_data.get("fields", []) if form.is_bound and hasattr(form, "cleaned_data") else initial["fields"]
    if form.is_bound and form.errors.get("fields"):
        try:
            raw = json.loads(request.POST.get("fields", "[]"))
            fields = raw if isinstance(raw, list) and all(isinstance(f, dict) for f in raw) and len(raw) <= 40 else []
        except (ValueError, TypeError):
            fields = []
    fields = [field for field in fields if not global_kind(field)]
    return render(request, "custom_forms/editor.html", {"form": form, "definition": definition, "builder_fields": fields,
        "field_types": FIELD_TYPES, "active_page": "forms"})


@require_http_methods(["GET", "POST"])
@never_cache
@administrator
def ordering(request):
    if request.method == "POST":
        try:
            revision = int(request.POST.get("revision", ""))
            items = json.loads(request.POST.get("items", ""))
            save_order(actor=request.user, revision=revision, items=items)
        except (ValueError, TypeError):
            messages.error(request, "Ordem inválida. Recarregue e tente novamente.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Ordem dos cards salva. As publicações não foram alteradas.")
        return redirect("custom_forms:ordering")
    state, rows = order_state()
    return render(request, "custom_forms/ordering.html", {"state": state, "rows": rows, "active_page": "forms"})


@require_POST
@never_cache
@administrator
def action(request, pk):
    try:
        revision = int(request.POST.get("revision", ""))
    except ValueError:
        return HttpResponseBadRequest("Revisão inválida.")
    try:
        result = perform_action(actor=request.user, form_id=pk, revision=revision, action=request.POST.get("action"))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        if FormDefinition.objects.filter(pk=pk, trashed_at__isnull=False).exists():
            return redirect("custom_forms:trash")
        return redirect("custom_forms:edit", pk=pk)
    messages.success(request, "Ação concluída.")
    if result and result.trashed_at:
        return redirect("custom_forms:trash")
    return redirect("custom_forms:edit", pk=result.pk) if result else redirect("custom_forms:manage")


@require_GET
@never_cache
@administrator
def trash(request):
    definitions = FormDefinition.objects.filter(trashed_at__isnull=False).select_related("trashed_by").order_by("-trashed_at", "pk")
    return render(request, "custom_forms/trash.html", {"definitions": definitions, "active_page": "forms"})


@require_http_methods(["GET", "POST"])
@never_cache
@administrator
def permanent_delete(request, pk):
    definition = get_object_or_404(FormDefinition, pk=pk, trashed_at__isnull=False)
    form = PermanentDeleteForm(request.POST if request.method == "POST" else None, initial={"revision": definition.revision})
    if request.method == "POST" and form.is_valid():
        try:
            permanently_delete_form(actor=request.user, form_id=pk, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Formulário excluído definitivamente. O registro de auditoria foi preservado.")
            return redirect("custom_forms:trash")
    return render(request, "custom_forms/permanent_delete.html", {"definition": definition, "form": form,
        "blockers": deletion_blockers(definition), "active_page": "forms"})


@require_POST
@never_cache
@administrator
def preview(request):
    form = DefinitionForm(request.POST)
    if not form.is_valid():
        return render(request, "custom_forms/preview.html", {"editor_errors": form.errors, "active_page": "forms"}, status=400)
    data = form.cleaned_data
    published = {key: data[key] for key in ("title", "description", "fields", "icon")}
    published["version"] = 1
    published["is_sensitive"] = False
    return render(request, "custom_forms/preview.html", {"form": RequestForm(published), "snapshot": published,
        "active_page": "forms"})


@require_GET
@login_required
@never_cache
def choose(request):
    from apps.sectors.intake import intake_selection

    initial, response = intake_selection(request)
    if response is not None:
        return response
    available = list(available_forms(request.user))
    support_state, support = standard_support(request.user)
    standard = dict(support.published_snapshot) if support else {"title": "Suporte técnico",
        "description": "Computador, sistemas, acessos ou outra necessidade de tecnologia.", "icon": "support", "display_order": -1}
    standard.update(key="standard", standard=True, symbol=ICONS.get(standard["icon"], "◈"))
    cards = ([standard] if support_state != "unavailable" else []) + [dict(definition.published_snapshot, id=definition.pk, key=str(definition.pk), standard=False,
                  symbol=ICONS.get(definition.published_snapshot.get("icon"), "＋")) for definition in available if definition.provision_key != "support"]
    rank = card_rank()
    cards.sort(key=lambda card: (rank.get(card["key"], len(rank)), card.get("display_order", 0), card["title"]))
    return render(request, "custom_forms/choose.html", {"cards": cards, "intake_query": f"company={initial['company']}&sector={initial['sector']}", "active_page": "new_ticket"})


@require_http_methods(["GET", "POST"])
@login_required
@never_cache
def request_form(request, pk):
    definition = get_object_or_404(available_forms(request.user), pk=pk)
    published = definition.published_snapshot
    initial = {}
    if request.method == "GET":
        from apps.sectors.intake import intake_selection

        initial, response = intake_selection(request)
        if response is not None:
            return response
    form = RequestForm(published, request.POST if request.method == "POST" else None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = submit_request(actor=request.user, form_id=pk, cleaned=form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Chamado {ticket.number} registrado com sucesso.")
            return redirect("tickets:detail", pk=ticket.pk)
    return render(request, "custom_forms/request.html", {"form": form, "snapshot": published, "active_page": "new_ticket"})
