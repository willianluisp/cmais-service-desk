"""Experimental read-only task chat. Cache only; no message/read-state models."""

import time
from hashlib import sha256
from html.parser import HTMLParser
from time import time as clock
from urllib.parse import parse_qsl, quote, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.utils.dateparse import parse_datetime

from .client import PlannerError, configured_read_client
from .configuration import selected_plan_id
from .models import MicrosoftGraphConnection

FRESH_SECONDS = 120
RETAIN_SECONDS = 3600
GLOBAL_COOLDOWN = 'planner-observations:throttle:v1'


def enabled():
    try:
        url = urlsplit(settings.PORTAL_BASE_URL)
        isolated = (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1'}
                    and url.port == 8010)
        # Explicit approval flags authorize the existing reader in HTTPS deployments
        # too. Binding it to localhost hid every conversation on the real portal.
        approved_origin = ((isolated or (url.scheme == 'https' and bool(url.hostname)))
                           and url.path in {'', '/'} and not url.username and not url.password
                           and not url.query and not url.fragment)
    except ValueError:
        approved_origin = False
    return bool(getattr(settings, 'PLANNER_OBSERVATIONS_ENABLED', False) and approved_origin
                and settings.MICROSOFT_GRAPH_APPROVED and settings.GRAPH_DELEGATED_OAUTH_ENABLED
                and settings.GRAPH_AUTH_STRATEGY == 'delegated')


def context(request):
    return {'observations_enabled': request.user.is_authenticated and request.user.is_active and enabled()}


class MessageText(HTMLParser):
    """Readable plain text, discarding active content rather than trusting remote HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.hidden += 1
        elif not self.hidden and tag in {'p', 'div', 'br', 'li', 'ul', 'ol', 'blockquote'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {'p', 'div', 'li', 'blockquote'}:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalize(item):
    if not isinstance(item, dict):
        raise ValueError
    identifier, content, created = item.get('id'), item.get('content'), item.get('createdDateTime')
    deleted = bool(item.get('deletedTime') or item.get('deletedDateTime'))
    if deleted:
        content = ''
    if not isinstance(identifier, str) or not identifier or len(identifier) > 1024:
        raise ValueError
    if not isinstance(content, str) or not isinstance(created, str):
        raise ValueError
    timestamp = parse_datetime(created)
    if not timestamp or timestamp.utcoffset() is None:
        raise ValueError
    parser = MessageText()
    parser.feed(content)
    parser.close()
    identity = item.get('createdBy') or {}
    user = identity.get('user') or {} if isinstance(identity, dict) else {}
    author = user.get('displayName') if isinstance(user, dict) else None
    return {'id': identifier, 'created_at': timestamp.isoformat(),
            'author': author[:200] if isinstance(author, str) and author.strip() else 'Equipe de suporte',
            'content': 'Mensagem removida no Planner.' if deleted else ''.join(parser.parts).strip()}


def fetch_messages(graph, task_id, plan_id):
    """Return a complete ordered snapshot, or raise. Never return partial pages."""
    started, original_timeout = time.monotonic(), graph.timeout
    path = '/beta/planner/tasks/' + quote(task_id, safe='') + '/messages'
    url = 'https://graph.microsoft.com' + path
    messages, seen = {}, set()
    try:
        graph.timeout = min(original_timeout, 4)
        task = graph.get_task(task_id)
        if not isinstance(task, dict) or task.get('id') != task_id or task.get('planId') != plan_id:
            raise PlannerError('INVALID_TASK', 'Observações indisponíveis.')
        for _ in range(25):
            if time.monotonic() - started >= 12 or url in seen:
                raise ValueError
            seen.add(url)
            parsed = urlsplit(url)
            query = parse_qsl(parsed.query, keep_blank_values=True)
            if (parsed.scheme != 'https' or parsed.netloc != 'graph.microsoft.com'
                    or parsed.path != path or parsed.fragment
                    or any(key.lower() != '$skiptoken' for key, _ in query)):
                raise ValueError
            graph.timeout = max(1, min(4, 12 - (time.monotonic() - started)))
            data = graph._request_json(url)
            if not isinstance(data, dict) or not isinstance(data.get('value'), list):
                raise ValueError
            for raw in data['value']:
                item = normalize(raw)
                messages[item['id']] = item
                if len(messages) > 2000:
                    raise ValueError
            next_link = data.get('@odata.nextLink')
            # Observed in the authorized beta tenant: its empty terminal page
            # points to itself. Only accept that exact empty self-cursor as EOF;
            # empty pages with a different cursor must still be followed.
            if not next_link or (not data['value'] and next_link == url and len(seen) > 1):
                return sorted(messages.values(), key=lambda m: (parse_datetime(m['created_at']), m['id']))
            if not isinstance(next_link, str) or len(next_link) > 16384:
                raise ValueError
            url = next_link
        raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise PlannerError('INVALID_PAYLOAD', 'Observações temporariamente indisponíveis.') from None
    finally:
        graph.timeout = original_timeout


def _key(ticket):
    # A changed account/tenant/plan cannot reuse another connection's cached chat.
    identity = MicrosoftGraphConnection.objects.filter(is_active=True).values_list(
        'pk', 'tenant_id', 'microsoft_user_id', 'scopes').first()
    value = repr((settings.GRAPH_CLIENT_ID, settings.GRAPH_TENANT_ID, identity,
                  selected_plan_id(), ticket.planner_plan_id, ticket.planner_task_id))
    return 'planner-observations:v1:' + sha256(value.encode()).hexdigest()


def read_observations(ticket, *, refresh=True, graph_client=None):
    empty = {'messages': [], 'complete': False, 'available': False, 'checked_at': None}
    if not enabled() or ticket.is_sensitive or not ticket.planner_task_id:
        return empty
    plan_id = selected_plan_id()
    if not plan_id or ticket.planner_plan_id != plan_id:
        return empty
    # Cache unavailability must not create unbounded remote requests.
    try:
        key, now = _key(ticket), clock()
        snapshot = cache.get(key)
        if snapshot and now - snapshot['checked_at'] < FRESH_SECONDS:
            return {**snapshot, 'complete': True, 'available': True}
        fallback = {**(snapshot or empty), 'complete': False, 'available': False}
        retry = cache.get(GLOBAL_COOLDOWN) or cache.get(key + ':retry')
        if retry:
            return {**fallback, 'retry_after': max(1, int(retry - now))}
        if not refresh:
            return fallback
        if not cache.add(key + ':lock', True, timeout=30):
            return fallback
        try:
            graph = graph_client or configured_read_client()
            messages = fetch_messages(graph, ticket.planner_task_id, plan_id)
            result = {'messages': messages, 'checked_at': clock()}
            cache.set(key, result, timeout=RETAIN_SECONDS)
            return {**result, 'complete': True, 'available': True}
        except PlannerError as exc:
            wait = max(30, min(exc.retry_after or 120, 86400))
            cache.set(key + ':retry', now + wait, timeout=wait)
            if exc.status == 429:
                cache.set(GLOBAL_COOLDOWN, now + wait, timeout=wait)
            return {**fallback, 'retry_after': wait}
        finally:
            cache.delete(key + ':lock')
    except Exception:
        # Database/cache/transport details are never returned to the collaborator.
        return empty
