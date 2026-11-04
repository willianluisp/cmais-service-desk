from apps.accounts.m365_preparation import prepare_rows


def row(name="Ana Souza", email="ana@example.test", **extra):
    return {"Display name": name, "User principal name": email, "Proxy addresses": "SMTP:" + email, "Block credential": "False", "Licenses": "Microsoft 365 Business Basic", **extra}


def test_candidates_keep_only_supplied_names_and_primary_smtp():
    reviewed, candidates, summary = prepare_rows([row("Ána Souza", "ana@example.test")])
    assert candidates[0]["username"] == "ana.souza"
    assert candidates[0]["full_name"] == "Ána Souza"
    assert summary["accounts_created"] == 0
    assert len(reviewed) == 1


def test_primary_smtp_separates_plus_joined_aliases_but_keeps_plus_tag():
    _, candidates, _ = prepare_rows([row(**{"Proxy addresses": "SMTP:ana+tag@example.test+smtp:alias@example.test"})])
    assert candidates[0]["email"] == "ana+tag@example.test"


def test_username_collision_quarantines_both_records():
    reviewed, candidates, summary = prepare_rows([row("Ana Souza", "one@example.test"), row("Ana Souza", "two@example.test")])
    assert not candidates
    assert summary["username_conflicts"] == [{"username": "ana.souza", "lines": [2, 3]}]
    assert all("USERNAME_DUPLICADO" in entry["reasons"] for entry in reviewed)


def test_blocked_technical_and_missing_smtp_need_review():
    reviewed, candidates, summary = prepare_rows([
        row("Ana Souza", **{"Block credential": "True"}),
        row("Suporte TI", "suporte@example.test"),
        row("Ana Silva", "ana.silva@example.test", **{"Proxy addresses": "smtp:alias@example.test"}),
    ])
    assert not candidates
    assert summary["needs_review"] == 3
    assert "BLOQUEADA" in reviewed[0]["reasons"]
    assert "POSSIVEL_CONTA_TECNICA_OU_COMPARTILHADA" in reviewed[1]["reasons"]
    assert "SMTP_PRIMARIO_NAO_CONFIRMADO" in reviewed[2]["reasons"]
