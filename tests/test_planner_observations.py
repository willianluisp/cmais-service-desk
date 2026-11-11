import json
from io import BytesIO
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.planner_integration.client import GraphClient, PlannerError
from apps.tickets.models import Category, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated(settings):
    settings.PLANNER_OBSERVATIONS_ENABLED = True
    settings.PORTAL_BASE_URL = 'http://localhost:8010'
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_AUTH_STRATEGY = 'delegated'
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    settings.PLANNER_PLAN_ID = 'plan'
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ticket(django_user_model):
    return Ticket.objects.create(number='SD-OBS-1', title='Teste', description='Teste',
        requester=django_user_model.objects.create_user('observations-owner'),
        category=Category.objects.create(name='Teste'), planner_task_id='task', planner_plan_id='plan')


def message(identifier='m1', date='2026-11-10T10:00:00Z', **kwargs):
    return dict(id=identifier, content='<p>Olá<br>Atualização sem prefixo</p>',
        createdDateTime=date, createdBy={'user': {'displayName': 'Técnico'}}, **kwargs)


def remote(*pages):
    graph = GraphClient(token_provider=lambda: 'mock-token')
    graph.get_task = Mock(return_value={'id': 'task', 'planId': 'plan'})
    graph._request_json = Mock(side_effect=pages)
    return graph


def test_real_transport_paginates_sorts_and_removes_unsafe_html(ticket):
    from apps.planner_integration.observations import fetch_messages
    first = message('new', '2026-11-10T12:00:00Z')
    first['content'] = '<p>Texto</p><script>secret()</script><img src=x onerror=bad()>'
    graph = remote({'value': [first], '@odata.nextLink': 'https://graph.microsoft.com/beta/planner/tasks/task/messages?$skipToken=next'},
                   {'value': [message('old'), first]})
    result = fetch_messages(graph, 'task', 'plan')
    assert [m['id'] for m in result] == ['old', 'new']
    assert result[0]['author'] == 'Técnico'
    assert 'Atualização sem prefixo' in result[0]['content']
    assert result[1]['content'] == 'Texto'
    assert graph._request_json.call_count == 2
    assert all(not call.kwargs for call in graph._request_json.call_args_list)


@pytest.mark.parametrize('link', [
    'https://evil.test/messages', 'https://graph.microsoft.com.evil.test/messages',
    'https://graph.microsoft.com/beta/planner/tasks/other/messages?$skipToken=x',
    'http://graph.microsoft.com/beta/planner/tasks/task/messages?$skipToken=x',
    'https://graph.microsoft.com/beta/planner/tasks/task/messages?$top=100',
])
def test_rejects_untrusted_pagination_without_requesting_it(link):
    from apps.planner_integration.observations import fetch_messages
    graph = remote({'value': [message()], '@odata.nextLink': link})
    with pytest.raises(PlannerError):
        fetch_messages(graph, 'task', 'plan')
    graph._request_json.assert_called_once()


def test_plan_mismatch_never_reads_messages():
    from apps.planner_integration.observations import fetch_messages
    graph = remote({'value': []})
    with pytest.raises(PlannerError):
        fetch_messages(graph, 'task', 'other-plan')
    graph._request_json.assert_not_called()


def test_observed_beta_empty_terminal_cursor_and_deleted_datetime():
    from apps.planner_integration.observations import fetch_messages
    link = 'https://graph.microsoft.com/beta/planner/tasks/task/messages?$skiptoken=end'
    item = message(deletedDateTime='2026-11-10T13:00:00Z')
    graph = remote({'value': [item], '@odata.nextLink': link}, {'value': [], '@odata.nextLink': link})
    result = fetch_messages(graph, 'task', 'plan')
    assert result[0]['content'] == 'Mensagem removida no Planner.'
    assert graph._request_json.call_count == 2


def test_nonempty_cursor_cycle_is_not_accepted():
    from apps.planner_integration.observations import fetch_messages
    link = 'https://graph.microsoft.com/beta/planner/tasks/task/messages?$skiptoken=end'
    graph = remote({'value': [message()], '@odata.nextLink': link}, {'value': [message()], '@odata.nextLink': link})
    with pytest.raises(PlannerError):
        fetch_messages(graph, 'task', 'plan')


def test_deleted_message_without_content_does_not_expose_removed_text():
    from apps.planner_integration.observations import fetch_messages
    item = message(deletedDateTime='2026-11-10T13:00:00Z')
    item['content'] = None
    assert fetch_messages(remote({'value': [item]}), 'task', 'plan')[0]['content'] == 'Mensagem removida no Planner.'


def test_empty_page_with_new_cursor_is_not_the_end():
    from apps.planner_integration.observations import fetch_messages
    base = 'https://graph.microsoft.com/beta/planner/tasks/task/messages?$skiptoken='
    graph = remote({'value': [], '@odata.nextLink': base + '1'},
                   {'value': [], '@odata.nextLink': base + '2'}, {'value': [message()]})
    assert len(fetch_messages(graph, 'task', 'plan')) == 1


def test_lock_and_cache_outage_do_not_trigger_remote_requests(ticket, monkeypatch):
    from apps.planner_integration.observations import _key, read_observations
    graph = remote()
    cache.add(_key(ticket) + ':lock', True, timeout=30)
    assert not read_observations(ticket, graph_client=graph)['complete']
    graph.get_task.assert_not_called()
    monkeypatch.setattr(cache, 'get', Mock(side_effect=ConnectionError('unavailable')))
    assert not read_observations(ticket, graph_client=graph)['complete']
    graph.get_task.assert_not_called()


def test_global_throttle_blocks_other_tasks(ticket):
    from apps.planner_integration.observations import read_observations
    graph = remote()
    graph.get_task.side_effect = PlannerError('THROTTLED', 'private', status=429, retry_after=240)
    assert read_observations(ticket, graph_client=graph)['retry_after'] == 240
    ticket.planner_task_id = 'other-task'
    assert not read_observations(ticket, graph_client=graph)['complete']
    assert graph.get_task.call_count == 1


def test_wrong_plan_and_unlinked_have_no_pending_poll_loop(ticket, client, monkeypatch):
    from apps.planner_integration import observations
    monkeypatch.setattr(observations, 'configured_read_client', lambda: pytest.fail('Graph called'))
    ticket.planner_plan_id = 'other'
    ticket.save(update_fields=['planner_plan_id'])
    client.force_login(ticket.requester)
    response = client.get(reverse('tickets:observation-summaries'), {'ids': str(ticket.pk)})
    assert not response.json()['pending']


def test_batch_limits_input_and_refreshes_only_one_task(ticket, client, monkeypatch):
    from apps.planner_integration import observations
    graph = remote({'value': []})
    monkeypatch.setattr(observations, 'configured_read_client', lambda: graph)
    other = Ticket.objects.create(number='SD-OBS-2', title='Other', description='Test',
        requester=ticket.requester, category=ticket.category, planner_task_id='task2', planner_plan_id='plan')
    client.force_login(ticket.requester)
    response = client.get(reverse('tickets:observation-summaries'), {'ids': f'{ticket.pk},{other.pk}'})
    assert response.status_code == 200
    assert graph.get_task.call_count == 1
    assert client.get(reverse('tickets:observation-summaries'), {'ids': 'not-a-uuid'}).status_code == 400
    assert client.get(reverse('tickets:observation-summaries'), {'ids': 'x'*801}).status_code == 400


def test_sensitive_and_archived_tickets_never_expose_chat(ticket, client, monkeypatch):
    from django.utils import timezone

    from apps.planner_integration import observations
    monkeypatch.setattr(observations, 'configured_read_client', lambda: pytest.fail('Graph called'))
    client.force_login(ticket.requester)
    ticket.is_sensitive = True
    ticket.save(update_fields=['is_sensitive'])
    assert client.get(reverse('tickets:observations', args=[ticket.pk])).status_code == 404
    ticket.is_sensitive = False
    ticket.archived_at = timezone.now()
    ticket.save(update_fields=['is_sensitive', 'archived_at'])
    assert client.get(reverse('tickets:observations', args=[ticket.pk])).status_code == 404


def test_cache_prevents_repeated_graph_requests_and_retains_last_good_result(ticket):
    from apps.planner_integration.observations import read_observations
    graph = remote({'value': [message()]})
    first = read_observations(ticket, graph_client=graph)
    second = read_observations(ticket, graph_client=graph)
    assert first['messages'] == second['messages'] and first['complete']
    graph._request_json.assert_called_once()
    # Force only the freshness clock forward; leave cache retention intact.
    from unittest.mock import patch
    with patch('apps.planner_integration.observations.clock', return_value=10**12):
        graph.get_task.side_effect = PlannerError('THROTTLED', 'private', status=429, retry_after=300)
        fallback = read_observations(ticket, graph_client=graph)
        assert fallback['messages'] == first['messages']
        assert not fallback['complete']
        read_observations(ticket, graph_client=graph)
    assert graph.get_task.call_count == 2


def test_empty_missing_author_deleted_and_invalid_payload():
    from apps.planner_integration.observations import fetch_messages
    assert fetch_messages(remote({'value': []}), 'task', 'plan') == []
    item = message(deletedTime='2026-11-10T13:00:00Z')
    item['createdBy'] = {}
    result = fetch_messages(remote({'value': [item]}), 'task', 'plan')
    assert result[0]['author'] == 'Equipe de suporte'
    assert result[0]['content'] == 'Mensagem removida no Planner.'
    with pytest.raises(PlannerError):
        fetch_messages(remote({'value': 'invalid'}), 'task', 'plan')


def test_partial_collection_is_not_cached_as_complete(ticket):
    from apps.planner_integration.observations import read_observations
    graph = remote({'value': [message()], '@odata.nextLink': 'https://graph.microsoft.com/beta/planner/tasks/task/messages?$skipToken=next'},
                   PlannerError('GRAPH_UNAVAILABLE', 'private'))
    result = read_observations(ticket, graph_client=graph)
    assert not result['complete'] and result['messages'] == []


def test_authorized_detail_and_batch_do_not_leak_content(ticket, client, monkeypatch):
    from apps.planner_integration import observations
    graph = remote({'value': [message()]})
    monkeypatch.setattr(observations, 'configured_read_client', lambda: graph)
    client.force_login(ticket.requester)
    url = reverse('tickets:observations', args=[ticket.pk])
    response = client.get(url)
    assert response.status_code == 200 and response.json()['messages'][0]['id'] == 'm1'
    assert 'no-store' in response['Cache-Control']
    batch = client.get(reverse('tickets:observation-summaries'), {'ids': str(ticket.pk)})
    assert batch.json()['tickets'][str(ticket.pk)]['ids'] == ['m1']
    assert 'Atualização' not in batch.content.decode()
    assert client.post(url).status_code == 405


def test_other_user_and_anonymous_cannot_read_or_warm_cache(ticket, client, django_user_model, monkeypatch):
    from apps.planner_integration import observations
    graph = Mock(side_effect=AssertionError('remote access'))
    monkeypatch.setattr(observations, 'configured_read_client', graph)
    url = reverse('tickets:observations', args=[ticket.pk])
    assert client.get(url).status_code == 302
    client.force_login(django_user_model.objects.create_user('other-observations'))
    assert client.get(url).status_code == 404
    assert client.get(reverse('tickets:observation-summaries'), {'ids': str(ticket.pk)}).json()['tickets'] == {}
    graph.assert_not_called()


def test_disabled_or_non_isolated_never_calls_graph(ticket, client, settings, monkeypatch):
    from apps.planner_integration import observations
    monkeypatch.setattr(observations, 'configured_read_client', lambda: pytest.fail('Graph called'))
    client.force_login(ticket.requester)
    settings.PORTAL_BASE_URL = 'http://localhost:8000'
    assert client.get(reverse('tickets:observations', args=[ticket.pk])).status_code == 404
    assert 'data-observations-root' not in client.get(reverse('tickets:detail', args=[ticket.pk])).content.decode()


@pytest.mark.parametrize('status', [401, 403, 404, 429, 503])
def test_graph_failure_does_not_break_portal(ticket, client, monkeypatch, status):
    from apps.planner_integration import observations
    graph = remote()
    graph.get_task.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'token-secret', status=status)
    monkeypatch.setattr(observations, 'configured_read_client', lambda: graph)
    client.force_login(ticket.requester)
    response = client.get(reverse('tickets:observations', args=[ticket.pk]))
    assert response.status_code == 200 and not response.json()['complete']
    assert 'token-secret' not in response.content.decode()


def test_transport_actual_http_error_is_classified():
    response = BytesIO(json.dumps({'error': {'code': 'TooManyRequests'}}).encode())
    graph = GraphClient(token_provider=lambda: 'mock', opener=Mock(side_effect=HTTPError('https://graph.microsoft.com', 429, 'Limited', {'Retry-After': '30'}, response)))
    with pytest.raises(PlannerError) as caught:
        graph._request_json('https://graph.microsoft.com/beta/planner/tasks/task/messages')
    assert caught.value.status == 429 and caught.value.retry_after == 30
