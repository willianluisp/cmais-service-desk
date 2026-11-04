"""Offline review of Microsoft 365 user exports; never creates Django users."""

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def fold(value):
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def prepare_rows(rows):
    reviewed = []
    usernames, emails = defaultdict(list), defaultdict(list)
    technical = {
        "admin", "administrator", "administrador", "suporte", "support", "helpdesk",
        "servicedesk", "service", "servico", "sistema", "sistemas", "scanner", "backup",
        "noreply", "naoresponda", "reuniao", "sala", "recepcao", "financeiro", "comercial",
        "contabilidade", "contabil", "fiscal", "societario", "rh", "ti", "teste", "test",
        "cmais", "contato", "atendimento", "diretoria", "departamento", "robot", "robo",
    }
    for line, source in enumerate(rows, start=2):
        reasons = []
        first = " ".join(source.get("First name", "").split())
        last = " ".join(source.get("Last name", "").split())
        display = " ".join(source.get("Display name", "").split())
        name = f"{first} {last}" if first and last else display
        parts = fold(name).split()
        username = re.sub(r"[^a-z0-9.]", "", f"{parts[0]}.{parts[-1]}") if len(parts) >= 2 else ""
        # SMTP (uppercase) denotes the primary transport address. Lowercase
        # smtp aliases must not silently replace the primary mailbox.
        # This Microsoft 365 export joins proxy entries with '+smtp:'; a '+'
        # inside the local part of one address remains valid and is preserved.
        proxies = re.sub(r"\+(?=(?:smtp|SMTP|sip|SIP|x500|X500):)", ";", source.get("Proxy addresses", ""))
        primary = re.findall(r"(?<![A-Za-z])SMTP:([^\s;,\]\[\"']+)", proxies)
        upn = source.get("User principal name", "").strip().casefold()
        email = primary[0].casefold() if len(primary) == 1 else upn
        if len(primary) != 1:
            reasons.append("SMTP_PRIMARIO_NAO_CONFIRMADO")
        if not re.fullmatch(r"[^\s@,;:]+@[^\s@,;:]+\.[^\s@,;:]+", email):
            reasons.append("EMAIL_INVALIDO")
        if "#ext#" in upn or source.get("MemberType", "").strip().lower() == "guest":
            reasons.append("CONVIDADO")
        block = source.get("Block credential", "").strip().lower()
        if block in {"true", "yes", "1", "sim"}:
            reasons.append("BLOQUEADA")
        elif block not in {"false", "no", "0", "nao", "não"}:
            reasons.append("BLOQUEIO_NAO_CONFIRMADO")
        if source.get("Soft deletion time stamp", "").strip():
            reasons.append("EXCLUSAO_LOGICA")
        if not re.fullmatch(r"[a-z0-9]+\.[a-z0-9]+", username) or len(username) > 150:
            reasons.append("NOME_COMPLETO_INSUFICIENTE")
        if first and last and fold(display) not in {fold(name), ""}:
            reasons.append("NOME_DE_EXIBICAO_DIVERGENTE")
        tokens = set(re.findall(r"[a-z]+", fold(name + " " + email.split("@")[0])))
        if tokens & technical or any(char.isdigit() for char in name):
            reasons.append("POSSIVEL_CONTA_TECNICA_OU_COMPARTILHADA")
        if source.get("Licenses", "").strip().lower() in {"", "unlicensed", "sem licenca", "sem licença"}:
            reasons.append("SEM_LICENCA_OU_NAO_INFORMADA")
        if email.endswith(".onmicrosoft.com"):
            reasons.append("DOMINIO_TECNICO_MICROSOFT")
        entry = {"line": line, "full_name": name, "email": email, "username": username, "reasons": reasons}
        usernames[username].append(entry)
        emails[email].append(entry)
        reviewed.append(entry)
    conflicts = []
    for key, group in usernames.items():
        if key and len(group) > 1:
            conflicts.append({"username": key, "lines": [entry["line"] for entry in group]})
            for entry in group:
                entry["reasons"].append("USERNAME_DUPLICADO")
    for key, group in emails.items():
        if key and len(group) > 1:
            for entry in group:
                entry["reasons"].append("EMAIL_DUPLICADO")
    candidates = [entry for entry in reviewed if not entry["reasons"]]
    summary = {
        "total": len(reviewed), "candidates_pending_approval": len(candidates),
        "needs_review": len(reviewed) - len(candidates),
        "reason_counts": dict(Counter(reason for entry in reviewed for reason in entry["reasons"])),
        "username_conflicts": conflicts,
        "accounts_created": 0,
        "warning": "Classificação por indícios. CSV não comprova colaborador ativo nem tipo de mailbox. UPN sem SMTP primário exige confirmação. Não importar antes da aprovação.",
    }
    return reviewed, candidates, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="Novo diretório privado fora do Git ou em .tmp ignorado.")
    args = parser.parse_args()
    with args.source.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"Display name", "User principal name", "Block credential", "Proxy addresses"}
        if not required.issubset(reader.fieldnames or []):
            parser.error("Cabeçalhos esperados da exportação Microsoft 365 não encontrados.")
        reviewed, candidates, summary = prepare_rows(reader)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for filename, entries, review in [("colaboradores_candidatos.csv", candidates, False), ("revisao.csv", reviewed, True)]:
        fields = ["full_name", "email", "username"]
        if review:
            fields = ["line", *fields, "reasons"]
        with (args.output / filename).open("x", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for entry in entries:
                writer.writerow({**entry, "reasons": ";".join(entry["reasons"])})
    (args.output / "validacao.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
