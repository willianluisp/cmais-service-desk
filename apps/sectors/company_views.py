from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import AccountAudit
from apps.planner_integration.admin_panel import administrator

from .company_forms import CompanyDeleteForm, CompanyForm
from .models import Company


def _snapshot(company):
    return {"id": company.pk, "name": company.name, "is_active": company.is_active,
            "display_order": company.display_order, "revision": company.revision}


def _audit(request, action, *, before=None, after=None):
    AccountAudit.objects.create(actor=request.user, action=action,
                                changes={"before": before, "after": after})


@administrator
@require_GET
def manage(request):
    return render(request, "companies/manage.html", {"companies": Company.objects.all(), "active_page": "companies"})


@administrator
@require_http_methods(["GET", "POST"])
def create(request):
    form = CompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                company = form.save()
                _audit(request, "COMPANY_CREATED", after=_snapshot(company))
            messages.success(request, "Empresa criada.")
            return redirect("companies:manage")
        except IntegrityError:
            form.add_error("name", "Já existe uma empresa com este nome.")
    return render(request, "companies/form.html", {"form": form, "active_page": "companies", "creating": True})


@administrator
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    status = 200
    with transaction.atomic():
        company = get_object_or_404(Company.objects.select_for_update(), pk=pk)
        before = _snapshot(company)
        form = CompanyForm(request.POST if request.method == "POST" else None, instance=company)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    changed = Company.objects.filter(pk=pk, revision=form.cleaned_data["revision"]).update(
                        name=form.cleaned_data["name"], is_active=form.cleaned_data["is_active"],
                        display_order=form.cleaned_data["display_order"], revision=F("revision") + 1,
                        updated_at=timezone.now(),
                    )
                    if changed:
                        company.refresh_from_db()
                        _audit(request, "COMPANY_UPDATED", before=before, after=_snapshot(company))
                        messages.success(request, "Empresa atualizada.")
                        return redirect("companies:manage")
                    form.add_error(None, "Esta empresa foi alterada por outra pessoa. Recarregue a página antes de salvar.")
                    status = 409
            except IntegrityError:
                form.add_error("name", "Já existe uma empresa com este nome.")
    return render(request, "companies/form.html", {"form": form, "company": company, "active_page": "companies"}, status=status)


@administrator
@require_http_methods(["GET", "POST"])
def delete(request, pk):
    status = 200
    with transaction.atomic():
        company = get_object_or_404(Company.objects.select_for_update(), pk=pk)
        form = CompanyDeleteForm(request.POST if request.method == "POST" else None,
                                initial={"revision": company.revision})
        if request.method == "POST" and form.is_valid():
            if form.cleaned_data["revision"] != company.revision:
                form.add_error(None, "Esta empresa foi alterada. Recarregue a página antes de excluir.")
                status = 409
            else:
                try:
                    with transaction.atomic():
                        before = _snapshot(company)
                        company.delete()
                        _audit(request, "COMPANY_DELETED", before=before)
                    messages.success(request, "Empresa excluída.")
                    return redirect("companies:manage")
                except ProtectedError:
                    form.add_error(None, "Esta empresa já está associada a chamados e não pode ser excluída. Você pode desativá-la.")
                    status = 409
    return render(request, "companies/delete.html", {"company": company, "form": form, "active_page": "companies"}, status=status)
