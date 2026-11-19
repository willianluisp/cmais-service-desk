from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from .directory import DirectoryUnavailable, lookup_guid
from .models import LocalAccount, UserProfile


class LocalBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not getattr(settings, "LOCAL_AUTH_ENABLED", False):
            return None
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            from .models import LocalAccount

            LocalAccount.objects.get_or_create(user=user)
        return user


class UnavailableBackend(ModelBackend):
    """Mantém a infraestrutura de sessão, sem aceitar senhas locais ou AD na Fase 1."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        return None


class ActiveDirectoryBackend(ModelBackend):
    """No local password fallback; database permissions follow verified AD roles."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not settings.LDAP_ENABLED or not username or not password:
            return None
        try:
            with transaction.atomic():
                return self._authenticate_directory(request, username, password)
        except (PermissionDenied, DirectoryUnavailable, IntegrityError):
            return None

    def _authenticate_directory(self, request, username, password):
        from .ldap_backend import DirectoryLDAPBackend

        return DirectoryLDAPBackend().authenticate(request, username=username, password=password)

    @transaction.atomic
    def provision(self, identity):
        model = get_user_model()
        try:
            profile = UserProfile.objects.select_for_update().select_related("user").get(
                object_guid=identity.object_guid,
            )
            user = profile.user
        except UserProfile.DoesNotExist:
            # An opaque local username prevents collisions with mutable AD names.
            user = model(username=f"ad_{identity.object_guid.hex}")
            profile = UserProfile(object_guid=identity.object_guid)
        user.first_name = identity.first_name
        user.last_name = identity.last_name
        user.email = identity.email
        user.is_active = True
        user.is_superuser = False
        # Portal administration is separate from the Django/AD administrative consoles.
        user.is_staff = False
        user.set_unusable_password()
        user.save()
        user.groups.set([Group.objects.get_or_create(name=role)[0] for role in sorted(identity.roles)])
        user.user_permissions.clear()
        profile.user = user
        for name in (
            "sam_account_name", "user_principal_name", "display_name", "department",
            "distinguished_name",
        ):
            setattr(profile, name, getattr(identity, name))
        profile.last_verified_at = timezone.now()
        profile.save()
        # Avoid returning stale related objects or cached permissions after revalidation.
        user.ad_profile = profile
        for cache_name in ("_perm_cache", "_group_perm_cache", "_user_perm_cache"):
            user.__dict__.pop(cache_name, None)
        return user

    def get_user(self, user_id):
        if not settings.LDAP_ENABLED:
            return None
        try:
            user = get_user_model().objects.select_related("ad_profile").get(pk=user_id, is_active=True)
            profile = user.ad_profile
        except (get_user_model().DoesNotExist, UserProfile.DoesNotExist):
            return None
        if timezone.now() - profile.last_verified_at < timedelta(seconds=settings.LDAP_REVALIDATE_SECONDS):
            return user
        try:
            identity = lookup_guid(profile.object_guid)
            if identity.object_guid != profile.object_guid:
                raise PermissionDenied
            return self.provision(identity)
        except (PermissionDenied, DirectoryUnavailable, OSError):
            with transaction.atomic():
                user.is_active = False
                user.save(update_fields=["is_active"])
                user.groups.clear()
                user.user_permissions.clear()
            return None


def normalize_login(username):
    """Aceita ``CMAIS\\nome.sobrenome``, ``nome.sobrenome@dominio`` e ``nome.sobrenome``."""
    value = (username or "").strip()
    if "\\" in value:
        value = value.split("\\", 1)[1].strip()
    return value


def _portal_roles_enabled():
    return bool(settings.LDAP_ENABLED and getattr(settings, "LDAP_ROLE_SOURCE", "ad") == "portal")


def password_managed_by_directory(user):
    """A senha desta conta é a do Windows (AD); o portal não a troca nem a recupera."""
    if not _portal_roles_enabled() or not getattr(user, "is_authenticated", False) or user.is_superuser:
        return False
    return UserProfile.objects.filter(user_id=user.pk).exists()


class PortalRolesDirectoryBackend(ModelBackend):
    """O AD só valida a senha. Papéis, grupos, ``is_active`` e ``is_staff`` continuam no portal.

    A conta do portal é vinculada ao AD no primeiro login pelo ``username`` igual ao
    ``sAMAccountName`` (sem diferenciar maiúsculas). Depois disso o vínculo é pelo
    ``objectGUID``, então renomear o login no AD não troca de conta. Sem conta no portal,
    o login é negado: quem cadastra pessoas continua sendo o administrador do portal.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        login_name = normalize_login(username)
        if not _portal_roles_enabled() or not login_name or not password:
            return None
        try:
            with transaction.atomic():
                return self._authenticate_directory(request, login_name, password)
        except (PermissionDenied, DirectoryUnavailable, IntegrityError):
            return None

    def _authenticate_directory(self, request, username, password):
        from .ldap_backend import PortalLinkLDAPBackend

        return PortalLinkLDAPBackend().authenticate(request, username=username, password=password)

    @transaction.atomic
    def link(self, identity):
        model = get_user_model()
        profile = (
            UserProfile.objects.select_for_update().select_related("user")
            .filter(object_guid=identity.object_guid).first()
        )
        if profile is not None:
            user = profile.user
        else:
            candidates = list(
                model.objects.select_for_update().filter(username__iexact=identity.sam_account_name)
            )
            if len(candidates) != 1:
                raise PermissionDenied("Conta do portal não encontrada ou ambígua.")
            user = candidates[0]
            if UserProfile.objects.filter(user=user).exists():
                # Já vinculada a outro objectGUID (conta do AD recriada ou homônima).
                raise PermissionDenied("Conta do portal vinculada a outra identidade.")
            profile = UserProfile(user=user, object_guid=identity.object_guid)
        if not user.is_active:
            raise PermissionDenied("Conta desativada no portal.")
        for name in (
            "sam_account_name", "user_principal_name", "display_name", "department",
            "distinguished_name",
        ):
            setattr(profile, name, getattr(identity, name))
        profile.last_verified_at = timezone.now()
        profile.save()
        if not user.is_superuser and user.has_usable_password():
            # A senha local deixa de valer; só superusuários guardam a senha de emergência.
            user.set_unusable_password()
            user.save(update_fields=["password"])
        LocalAccount.objects.filter(user=user, must_change_password=True).update(
            must_change_password=False,
        )
        user.ad_profile = profile
        return user

    def get_user(self, user_id):
        if not _portal_roles_enabled():
            return None
        try:
            user = get_user_model().objects.select_related("ad_profile").get(pk=user_id, is_active=True)
            profile = user.ad_profile
        except (get_user_model().DoesNotExist, UserProfile.DoesNotExist):
            return None
        if timezone.now() - profile.last_verified_at < timedelta(seconds=settings.LDAP_REVALIDATE_SECONDS):
            return user
        try:
            identity = lookup_guid(profile.object_guid, require_roles=False)
            return self.link(identity)
        except (PermissionDenied, DirectoryUnavailable, OSError, IntegrityError):
            # Encerra a sessão sem mexer no cadastro do portal (o AD pode estar só fora do ar).
            return None


class LocalSuperuserBackend(ModelBackend):
    """Acesso de emergência com o AD ativo: só superusuários, com a senha local deles."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not _portal_roles_enabled() or not getattr(settings, "LDAP_LOCAL_SUPERUSER_FALLBACK", False):
            return None
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None or not user.is_superuser:
            return None
        return user

    def get_user(self, user_id):
        if not _portal_roles_enabled() or not getattr(settings, "LDAP_LOCAL_SUPERUSER_FALLBACK", False):
            return None
        user = super().get_user(user_id)
        return user if user is not None and user.is_superuser else None
