"""Per-ticket session mutex; never wrap remote HTTP in a DB transaction.

PostgreSQL connections must have session affinity (no transaction-mode pooler).
The SQLite fallback serializes threads only and is for local development/tests.
"""

import hashlib
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock, RLock
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection

logger = logging.getLogger(__name__)
_held = ContextVar('ticket_graph_locks', default=None)
_local_guard = Lock()
_local_locks = {}


class TicketGraphBusy(ValidationError):
    def __init__(self):
        super().__init__('Há uma operação do Planner em andamento neste chamado. Aguarde e tente novamente.')


def lock_key(ticket_id):
    digest = hashlib.blake2b(f'cmais:ticket-graph:{UUID(str(ticket_id))}'.encode(), digest_size=8).digest()
    return int.from_bytes(digest, 'big', signed=True)


@contextmanager
def ticket_graph_lock(ticket_id, *, timeout=None):
    timeout = max(0, min(float(timeout if timeout is not None else getattr(settings, 'PLANNER_TICKET_LOCK_TIMEOUT', 2)), 2))
    key = lock_key(ticket_id)
    connection.ensure_connection()
    session = connection.connection
    acquired = False
    local = None
    token = None
    try:
        if connection.vendor == 'postgresql':
            deadline = time.monotonic() + timeout
            while True:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_try_advisory_lock(%s)', [key])
                    acquired = cursor.fetchone()[0]
                if acquired:
                    break
                if time.monotonic() >= deadline:
                    raise TicketGraphBusy
                time.sleep(min(.025, max(0, deadline - time.monotonic())))
        else:
            with _local_guard:
                entry = _local_locks.setdefault(key, [RLock(), 0])
                entry[1] += 1
                local = entry[0]
            acquired = local.acquire(timeout=timeout)
            if not acquired:
                raise TicketGraphBusy
        token = _held.set({**(_held.get() or {}), key: session})
        yield
    finally:
        if token is not None:
            _held.reset(token)
        if acquired and connection.vendor == 'postgresql':
            try:
                if connection.connection is session:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_advisory_unlock(%s)', [key])
                        if not cursor.fetchone()[0]:
                            raise RuntimeError('Ticket mutex was lost')
                else:
                    connection.close()
            except Exception:
                # Closing the session releases its advisory locks even after DB errors.
                connection.close()
                logger.error('Failed to release ticket Graph mutex; connection closed')
        if local is not None:
            if acquired:
                local.release()
            with _local_guard:
                _local_locks[key][1] -= 1
                if not _local_locks[key][1]:
                    del _local_locks[key]


def assert_ticket_lock(ticket_id):
    if connection.connection is None or lock_key(ticket_id) not in (_held.get() or {}) or (_held.get() or {})[lock_key(ticket_id)] is not connection.connection:
        raise ValidationError('A sessão de proteção do chamado foi perdida. Tente novamente.')


def serialized_ticket(view):
    @wraps(view)
    def protected(*args, **kwargs):
        with ticket_graph_lock(kwargs['ticket_id']):
            return view(*args, **kwargs)
    return protected


def ensure_no_uncertain_writes(ticket):
    from .models import AttachmentPublication, PlannerTaskProvisioning

    row = PlannerTaskProvisioning.objects.filter(ticket=ticket).first()
    uncertain = row and (row.graph_write_inflight or row.description_write_inflight
        or (row.state == 'RECONCILIATION' and not ticket.planner_task_id and row.attempts)
        or (row.checklist_inflight_ids and not row.checklist_completed_at))
    if uncertain or AttachmentPublication.objects.filter(attachment__ticket=ticket, graph_write_inflight=True).exists():
        raise ValidationError('O envio ao Planner requer conferência após uma resposta incerta. Aguarde a recuperação ou solicite a conferência antes de arquivar/excluir.')


class JournaledGraphClient:
    """Durable uncertainty marker around writes, inside the session mutex only."""

    WRITES = {'create_task', 'update_task_details', 'patch_task_checklist',
              'upload_attachment', 'attach_reference'}

    def __init__(self, client, row, ticket_id):
        self.client, self.row, self.ticket_id = client, row, ticket_id

    def __getattr__(self, name):
        method = getattr(self.client, name)
        if name not in self.WRITES:
            return method

        @wraps(method)
        def write(*args, **kwargs):
            from apps.tickets.models import Ticket

            from .client import PlannerError

            assert_ticket_lock(self.ticket_id)
            if not Ticket.objects.filter(pk=self.ticket_id, archived_at__isnull=True, planner_deleted_at__isnull=True).exists():
                raise PlannerError('CANCELLED', 'Chamado arquivado; envio cancelado.', status=409)
            rows = type(self.row).objects.filter(pk=self.row.pk).exclude(state='CANCELLED')
            marker = 'description_write_inflight' if name == 'update_task_details' else 'graph_write_inflight'
            previous_uncertainty = rows.values_list(marker, flat=True).first()
            if not rows.update(**{marker: True}):
                raise PlannerError('CANCELLED', 'Envio cancelado.', status=409)
            try:
                result = method(*args, **kwargs)
            except PlannerError as exc:
                if not previous_uncertainty and exc.status in {400, 401, 403, 404, 409, 412, 429}:
                    rows.update(**{marker: False})
                raise
            # Unexpected exceptions/worker termination leave the marker for reconciliation.
            rows.update(**{marker: False})
            return result
        return write
