from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import AccountAudit
from apps.planner_integration.admin_panel import administrator

from .forms import SectorDeleteForm, SectorForm
from .models import Sector


def _snapshot(sector):
    return {"id": sector.pk, "name": sector.name, "is_active": sector.is_active,
            "display_order": sector.display_order, "revision": sector.revision}


def _audit(request, action, *, before=None, after=None):
    AccountAudit.objects.create(actor=request.user, action=action,
                                changes={"before": before, "after": after})


@administrator
@require_GET
def manage(request):
    return render(request, "sectors/manage.html", {"sectors": Sector.objects.all(), "active_page": "sectors"})


@administrator
@require_http_methods(["GET", "POST"])
def create(request):
    form = SectorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                sector = form.save()
                _audit(request, "SECTOR_CREATED", after=_snapshot(sector))
            messages.success(request, "Setor criado.")
            return redirect("sectors:manage")
        except IntegrityError:
            form.add_error("name", "Já existe um setor com este nome.")
    return render(request, "sectors/form.html", {"form": form, "active_page": "sectors", "creating": True})


@administrator
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    status = 200
    with transaction.atomic():
        sector = get_object_or_404(Sector.objects.select_for_update(), pk=pk)
        before = _snapshot(sector)
        form = SectorForm(request.POST if request.method == "POST" else None, instance=sector)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    changed = Sector.objects.filter(pk=pk, revision=form.cleaned_data["revision"]).update(
                        name=form.cleaned_data["name"], is_active=form.cleaned_data["is_active"],
                        display_order=form.cleaned_data["display_order"], revision=F("revision") + 1,
                        updated_at=timezone.now(),
                    )
                    if changed:
                        sector.refresh_from_db()
                        _audit(request, "SECTOR_UPDATED", before=before, after=_snapshot(sector))
                        messages.success(request, "Setor atualizado.")
                        return redirect("sectors:manage")
                    form.add_error(None, "Este setor foi alterado por outra pessoa. Recarregue a página antes de salvar.")
                    status = 409
            except IntegrityError:
                form.add_error("name", "Já existe um setor com este nome.")
    return render(request, "sectors/form.html", {"form": form, "sector": sector, "active_page": "sectors"}, status=status)


@administrator
@require_http_methods(["GET", "POST"])
def delete(request, pk):
    status = 200
    with transaction.atomic():
        sector = get_object_or_404(Sector.objects.select_for_update(), pk=pk)
        form = SectorDeleteForm(request.POST if request.method == "POST" else None,
                                initial={"revision": sector.revision})
        if request.method == "POST" and form.is_valid():
            if form.cleaned_data["revision"] != sector.revision:
                form.add_error(None, "Este setor foi alterado. Recarregue a página antes de excluir.")
                status = 409
            else:
                try:
                    with transaction.atomic():
                        before = _snapshot(sector)
                        sector.delete()
                        _audit(request, "SECTOR_DELETED", before=before)
                    messages.success(request, "Setor excluído.")
                    return redirect("sectors:manage")
                except ProtectedError:
                    form.add_error(None, "Este setor já está associado a chamados e não pode ser excluído. Você pode desativá-lo.")
                    status = 409
    return render(request, "sectors/delete.html", {"sector": sector, "form": form, "active_page": "sectors"}, status=status)
