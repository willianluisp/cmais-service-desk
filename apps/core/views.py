from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST


@require_GET
def home(request):
    if request.user.is_authenticated:
        from apps.custom_forms.services import available_forms
        from apps.tickets.models import Ticket
        from apps.tickets.permissions import visible_tickets

        tickets = visible_tickets(request.user, Ticket.objects.all())
        return render(request, "portal/dashboard.html", {
            "active_page": "home", "ticket_total": tickets.count(),
            "ticket_open": tickets.filter(status=Ticket.Status.ABERTO).count(),
            "ticket_progress": tickets.filter(status__in=Ticket.PORTAL_STATUS_GROUPS["EM_ATENDIMENTO"]).count(),
            "ticket_resolved": tickets.filter(status__in=Ticket.PORTAL_STATUS_GROUPS["RESOLVIDO"]).count(),
            "recent_tickets": tickets.select_related("category")[:5],
            "quick_forms": available_forms(request.user)[:3],
        })
    return render(request, "portal/home.html", {"active_page": "home"})


@require_GET
@login_required
@never_cache
def account(request):
    """Read-only presentation of the current user's own existing account data."""
    return render(request, "accounts/account.html", {
        "active_page": "account", "account_groups": request.user.groups.order_by("name"),
    })


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login_unavailable(request):
    from apps.accounts.views import login_view

    return login_view(request)


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


@require_GET
@login_required
def integrations(request):
    from apps.planner_integration.admin_panel import panel

    return panel(request)
