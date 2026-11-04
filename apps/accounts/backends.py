from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from .directory import DirectoryUnavailable, lookup_guid
from .models import UserProfile


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
