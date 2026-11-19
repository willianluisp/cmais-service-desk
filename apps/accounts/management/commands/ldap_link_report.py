"""Prévia somente leitura: quais contas do portal vão casar com uma conta do AD."""

from collections import Counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.directory import DirectoryUnavailable, identity_from_attributes, lookup_login
from apps.accounts.models import UserProfile

STATUS = {
    "VINCULADA": "já vinculada ao AD (objectGUID)",
    "VAI_VINCULAR": "existe no AD com o mesmo login; vincula no primeiro acesso",
    "SEM_CONTA_AD": "não existe no AD com esse login; não vai conseguir entrar",
    "DESATIVADA_AD": "existe no AD, mas está desativada",
    "AMBIGUA": "mais de uma conta no AD com esse login",
    "SO_LOCAL": "superusuário sem conta no AD; entra só pelo acesso de emergência",
}


class Command(BaseCommand):
    help = "Lista o vínculo previsto de cada conta ativa do portal com o AD. Não altera nada."

    def handle(self, *args, **options):
        if not settings.LDAP_ENABLED or getattr(settings, "LDAP_ROLE_SOURCE", "ad") != "portal":
            raise CommandError("Ative LDAP_ENABLED, LDAP_APPROVED e LDAP_ROLE_SOURCE=portal antes da prévia.")
        linked = set(UserProfile.objects.values_list("user_id", flat=True))
        counts = Counter()
        users = get_user_model().objects.filter(is_active=True).order_by("username")
        for user in users:
            status = self._status(user, user.pk in linked)
            counts[status] += 1
            self.stdout.write(f"{status:<14} {user.username}")
        self.stdout.write("")
        for status, description in STATUS.items():
            if counts[status]:
                self.stdout.write(f"{counts[status]:>4}  {status}: {description}")

    def _status(self, user, already_linked):
        if already_linked:
            return "VINCULADA"
        try:
            results = lookup_login(user.username)
        except DirectoryUnavailable:
            raise CommandError("AD indisponível ou certificado não confiável; nada foi alterado.") from None
        if not results:
            return "SO_LOCAL" if user.is_superuser else "SEM_CONTA_AD"
        if len(results) > 1:
            return "AMBIGUA"
        dn, attrs = results[0]
        try:
            identity_from_attributes(attrs, dn, (), require_roles=False)
        except PermissionDenied:
            return "DESATIVADA_AD"
        return "VAI_VINCULAR"
