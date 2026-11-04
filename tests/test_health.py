from unittest.mock import patch

import pytest
from django.db import DatabaseError
from redis.exceptions import ConnectionError as RedisConnectionError


def test_liveness_needs_no_database_or_redis(client):
    response = client.get("/health/live/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_readiness_queries_real_database_and_redis_ping(client):
    with patch("redis.Redis.ping", return_value=True):
        response = client.get("/health/ready/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_failed_redis_ping_returns_unavailable(client):
    with patch("redis.Redis.ping", return_value=False):
        response = client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [RedisConnectionError, TimeoutError])
def test_redis_failure_is_sanitized(client, failure):
    with patch("redis.Redis.ping", side_effect=failure("redis://user:secret@internal")):
        response = client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret" not in response.content.decode()


def test_database_failure_is_sanitized(client):
    with patch("django.db.connection.cursor", side_effect=DatabaseError("password=secret")):
        response = client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret" not in response.content.decode()


def test_health_endpoints_reject_post(client):
    assert client.post("/health/live/").status_code == 405
