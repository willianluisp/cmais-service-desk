"""All-or-nothing employee intake; passwords are returned only to the caller."""

import re
import secrets
import unicodedata

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction

from .models import AccountAudit, LocalAccount


def import_employees(*, actor, rows, apply=False, initial_password=None, single_name_usernames=()):
    homologation = initial_password is not None
    if homologation and not (
        getattr(settings, "ISOLATED_HOMOLOGATION_IMPORT_ENABLED", False)
        and settings.DEBUG and settings.PORTAL_BASE_URL == "http://localhost:8010"
        and not any(getattr(settings, flag, False) for flag in (
            "LDAP_ENABLED", "MICROSOFT_GRAPH_APPROVED", "PLANNER_ENABLED", "EMAIL_ENABLED",
        ))
    ):
        raise PermissionDenied("Senha inicial compartilhada permitida somente na homologação isolada autorizada.")
    if not homologation and (actor is None or not actor.is_active or not actor.is_superuser):
        raise PermissionDenied("Importação exige administrador autorizado.")
    if single_name_usernames and not homologation:
        raise PermissionDenied("Nomes únicos exigem lote de homologação explicitamente autorizado.")
    if apply and homologation and not initial_password:
        raise ValidationError("Informe a senha inicial pelo canal protegido.")
    users = get_user_model()
    normalized, errors, names, emails = [], [], set(), set()
    for index, row in enumerate(rows, start=2):
        full_name = " ".join(str(row.get("full_name", "")).split())
        email = str(row.get("email", "")).strip().casefold()
        parts = full_name.split()
        ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode().lower().split()
        username = re.sub(r"[^a-z0-9.]", "", f"{ascii_name[0]}.{ascii_name[-1]}") if len(ascii_name) >= 2 else ""
        override = str(row.get("username", "")).strip().lower()
        if override:
            username = override
        try:
            validate_email(email)
            single = len(parts) == 1 and username in single_name_usernames and username == ascii_name[0]
            if (len(parts) < 2 and not single) or not re.fullmatch(r"[a-z0-9]+(?:\.[a-z0-9]+)?", username) or len(username) > 150:
                raise ValidationError("Nome completo ou usuário inválido.")
            if not single and "." not in username:
                raise ValidationError("Usuário deve seguir o padrão nome.sobrenome.")
            if len(parts[0]) > 150 or len(" ".join(parts[1:])) > 150:
                raise ValidationError("Nome excede o limite.")
            if email in emails or username in names:
                raise ValidationError("E-mail ou usuário repetido no arquivo.")
            matches = list(users.objects.filter(email__iexact=email)[:2])
            existing = matches[0] if len(matches) == 1 else None
            if len(matches) > 1 or (existing and existing.username != username):
                raise ValidationError("E-mail existente com identidade divergente; revisão necessária.")
            if users.objects.filter(username__iexact=username).exclude(pk=existing.pk if existing else None).exists():
                raise ValidationError("Nome de usuário já utilizado; informe username explícito.")
            normalized.append((full_name, email, username, existing))
        except ValidationError as exc:
            errors.append({"line": index, "errors": exc.messages})
        names.add(username)
        emails.add(email)
    if errors or not apply:
        return {"errors": errors, "created": [], "existing": sum(bool(row[3]) for row in normalized), "ready": len(normalized)}
    created = []
    with transaction.atomic():
        # Serialize imports from all administrators, including competing email
        # insertions, without touching unrelated ticket data.
        list(users.objects.select_for_update().order_by("pk"))
        for full_name, email, username, existing in normalized:
            if existing:
                continue
            if users.objects.filter(email__iexact=email).exists():
                raise ValidationError("Cadastro alterado durante a importação; execute a prévia novamente.")
            password = initial_password if homologation else secrets.token_urlsafe(24)
            first, _, last = full_name.partition(" ")
            user = users.objects.create_user(username=username, email=email, first_name=first, last_name=last, password=password)
            LocalAccount.objects.create(user=user)
            user.groups.add(Group.objects.get_or_create(name="COLABORADOR")[0])
            AccountAudit.objects.create(actor=actor, target=user, action="EMPLOYEE_IMPORTED")
            created.append({"username": username, "email": email, "temporary_password": password})
    return {"errors": [], "created": created, "existing": sum(bool(row[3]) for row in normalized), "ready": len(normalized)}
