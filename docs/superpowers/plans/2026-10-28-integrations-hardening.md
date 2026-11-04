# C+ Help Desk Integrations Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the safe, testable integration contracts for LDAPS, Microsoft Graph, Planner and Graph Mail without contacting corporate services.

**Architecture:** Keep all credentials in environment-backed settings; clients remain dependency-injectable for mock tests. Django persists work in the existing Planner and notification outboxes, while external integration flags remain deny-by-default.

**Tech Stack:** Django, Celery, PostgreSQL, Redis, ldap3-compatible configuration, Microsoft Graph REST.

**Spec:** User request dated 2026-10-28.

## Global Constraints

- Do not access AD, Microsoft Graph, Planner or Outlook without explicit approval.
- Do not change port 8000, commit, push, deploy or expose credentials.
- Validate TLS for LDAPS; do not infer Entra identities from names.

## Review Focus

- Missing LDAPS CA or binding configuration must fail closed.
- Graph token failures and 429 responses must never expose credentials.
- Planner retries must not duplicate a task after an ambiguous failure.
- Mail outbox retries must retain deduplication identity.
- Identity mapping must require immutable directory and Entra identifiers.

### Task 1: Identity configuration and mapping

**Files:** `apps/accounts/*`, `config/ldap.py`, `tests/test_ldap_*.py`

- [ ] Write failing tests for explicit immutable AD/Entra mapping and disabled-user handling.
- [ ] Implement only the identity fields/service required by those tests.
- [ ] Run relevant tests.

### Task 2: Graph clients and outboxes

**Files:** `apps/planner_integration/*`, `apps/notifications/*`, `tests/test_planner.py`, `tests/test_notifications.py`

- [ ] Write failing tests for safe token caching/error mapping and outbox retry/deduplication.
- [ ] Implement the minimal Graph client/outbox behavior.
- [ ] Run API integration tests.

### Task 3: Operational configuration and evidence

**Files:** `.env.example`, `README.md`, `docs/*.md`, `compose.isolated.yaml`

- [ ] Document exact environment variables, Entra permissions, AD/Planner discovery and isolated verification.
- [ ] Run migrations/check/lint and integration tests in the isolated Compose stack.
