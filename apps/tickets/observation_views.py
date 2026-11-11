"""Read-only authorized views for the experimental support observations."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.planner_integration.configuration import selected_plan_id
from apps.planner_integration.observations import enabled, read_observations

from .models import Ticket
from .permissions import visible_tickets
from .views import _ticket


@login_required
@require_GET
@never_cache
def observations(request, pk):
    ticket = _ticket(request, pk)
    if not enabled() or ticket.is_sensitive:
        raise Http404
    return JsonResponse(read_observations(ticket))


@login_required
@require_GET
@never_cache
def summaries(request):
    if not enabled():
        raise Http404
    raw = request.GET.get('ids', '')
    if len(raw) > 800:
        return JsonResponse({'tickets': {}}, status=400)
    try:
        identifiers = {UUID(value) for value in raw.split(',') if value}
    except ValueError:
        return JsonResponse({'tickets': {}}, status=400)
    if len(identifiers) > 20:
        return JsonResponse({'tickets': {}}, status=400)
    tickets = list(visible_tickets(request.user, Ticket.objects.filter(pk__in=identifiers, is_sensitive=False)))
    snapshots = [(ticket, read_observations(ticket, refresh=False)) for ticket in tickets]
    # Warm at most one task per request; cache the rest. Rotate oldest first.
    plan_id = selected_plan_id()
    eligible = [(t, s) for t, s in snapshots if t.planner_task_id and t.planner_plan_id == plan_id
                and not s['complete'] and not s.get('retry_after')]
    if eligible:
        ticket, _ = min(eligible, key=lambda pair: pair[1]['checked_at'] or 0)
        updated = read_observations(ticket)
        snapshots = [(t, updated if t.pk == ticket.pk else s) for t, s in snapshots]
    result = {str(t.pk): {'ids': [m['id'] for m in s['messages']], 'complete': s['complete'],
                         'checked_at': s['checked_at']} for t, s in snapshots}
    pending = any(t.planner_task_id and t.planner_plan_id == plan_id and not s['complete']
                  and not s.get('retry_after') for t, s in snapshots)
    return JsonResponse({'tickets': result, 'pending': pending})
