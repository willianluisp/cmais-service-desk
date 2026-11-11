"""Read-only directory enrichment; Planner assignment IDs remain authoritative."""

from hashlib import sha256
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

from .client import PlannerError, configured_read_client

UNAVAILABLE = "Responsável indisponível"


def _object_id(value):
    try:
        return str(UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def _display_name(value):
    return (
        isinstance(value, str) and 0 < len(value.strip()) <= 256
        and not _object_id(value.strip()) and value.strip() != UNAVAILABLE
    )


def resolve_assignee_names(ids, *, graph_client=None):
    # Separate tenants/apps and authorization strategies without caching secrets.
    scope = sha256("|".join(str(getattr(settings, key, "")) for key in (
        "GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_AUTH_STRATEGY",
    )).encode()).hexdigest()
    prefix = f"planner:directory:{scope}"
    names = []
    for raw_id in ids:
        user_id = _object_id(raw_id)
        if not user_id:
            names.append(UNAVAILABLE)
            continue
        key = f"{prefix}:{user_id}"
        name = cache.get(key)
        if name is None:
            name, ttl = UNAVAILABLE, 60
            if not cache.get(f"{prefix}:unavailable"):
                try:
                    graph_client = graph_client or configured_read_client()
                    profile = graph_client.get_user(user_id)
                    if (
                        isinstance(profile, dict) and _object_id(profile.get("id")) == user_id
                        and _display_name(profile.get("displayName"))
                    ):
                        name, ttl = profile["displayName"].strip(), 3600
                except PlannerError as exc:
                    if exc.status == 404:
                        ttl = 300
                    else:
                        # Stop a directory outage/permission error from causing N requests.
                        ttl = max(60, min(exc.retry_after or 60, 86400))
                        cache.set(f"{prefix}:unavailable", True, timeout=ttl)
            cache.set(key, name, timeout=ttl)
        names.append(name)
    return names


def ticket_assignee_names(ticket):
    """Repair legacy ID-as-name projections for display, without writing on GET."""
    ids = ticket.planner_assignee_ids
    stored = ticket.planner_assignee_names
    if not ids:
        return [name.strip() for name in stored if _display_name(name)]
    names = []
    for index, _user_id in enumerate(ids):
        name = stored[index] if index < len(stored) else None
        names.append(name.strip() if _display_name(name) else None)
    missing = [user_id for user_id, name in zip(ids, names, strict=True) if name is None]
    resolved = iter(resolve_assignee_names(missing))
    return [name if name is not None else next(resolved) for name in names]
