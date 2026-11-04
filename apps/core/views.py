from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST


@require_GET
def home(request):
    if request.user.is_authenticated:
        from apps.tickets.models import Ticket
        from apps.tickets.permissions import visible_tickets

        tickets = visible_tickets(request.user, Ticket.objects.all())
        return render(request, "portal/dashboard.html", {
            "active_page": "home", "ticket_total": tickets.count(),
            "ticket_open": tickets.filter(status=Ticket.Status.ABERTO).count(),
            "ticket_progress": tickets.filter(status__in=Ticket.PORTAL_STATUS_GROUPS["EM_ATENDIMENTO"]).count(),
            "ticket_resolved": tickets.filter(status__in=Ticket.PORTAL_STATUS_GROUPS["RESOLVIDO"]).count(),
            "recent_tickets": tickets.select_related("category")[:5],
        })
    return render(request, "portal/home.html", {"active_page": "home"})


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
