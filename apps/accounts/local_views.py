import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import MinimumLengthValidator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template import loader

from apps.notifications.models import NotificationOutbox

from .models import AccountAudit, LocalAccount


class CompletePasswordForm(SetPasswordForm):
    def clean_new_password1(self):
        password = self.cleaned_data["new_password1"]
        if LocalAccount.objects.filter(user=self.user, must_change_password=True).exists():
            _validate_initial_password_replacement(self.user, password)
        return password

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            LocalAccount.objects.update_or_create(user=user, defaults={"must_change_password": False})
            AccountAudit.objects.create(target=user, action="PASSWORD_CHANGED")
        return user


def _validate_initial_password_replacement(user, password):
    MinimumLengthValidator(min_length=8).validate(password, user)
    if user.check_password(password):
        raise ValidationError("Escolha uma senha diferente da senha inicial.", code="password_unchanged")


class FirstAccessPasswordForm(SetPasswordForm):
    """Extra first-access requirements; the configured Django validators still run."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Nova senha"
        self.fields["new_password2"].label = "Confirmar nova senha"
        for name, field in self.fields.items():
            field.widget.attrs.update(minlength=8, autocomplete="new-password", required=True)
            field.widget.attrs["aria-describedby"] = f"password-requirements {name}-errors"

    def clean_new_password1(self):
        password = self.cleaned_data["new_password1"]
        _validate_initial_password_replacement(self.user, password)
        return password


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_form.html"
    success_url = "/"

    def get_form_class(self):
        if LocalAccount.objects.filter(user=self.request.user, must_change_password=True).exists():
            return FirstAccessPasswordForm
        return super().get_form_class()

    def get_template_names(self):
        if self.get_form_class() is FirstAccessPasswordForm:
            return ["accounts/first_access.html"]
        return super().get_template_names()

    @transaction.atomic
    def form_valid(self, form):
        # Concurrent submissions must not overwrite a password already changed
        # by another authenticated session of this user.
        current = get_user_model().objects.select_for_update().get(pk=self.request.user.pk)
        if current.password != self.request.user.password:
            logout(self.request)
            return redirect("login")
        response = super().form_valid(form)
        LocalAccount.objects.update_or_create(user=self.request.user, defaults={"must_change_password": False})
        AccountAudit.objects.create(actor=self.request.user, target=self.request.user, action="PASSWORD_CHANGED")
        messages.success(self.request, "Senha atualizada com sucesso. Seu acesso ao C+ Service Desk está liberado.")
        return response


class QueuedPasswordResetForm(PasswordResetForm):
    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        # Recovery must never write usable tokens to console logs or derive a
        # recovery origin from an untrusted incoming Host header.
        from urllib.parse import urlsplit

        base = urlsplit(settings.PORTAL_BASE_URL)
        if base.scheme not in {"http", "https"} or not base.netloc:
            return
        context.update(domain=base.netloc, protocol=base.scheme)
        body = loader.render_to_string("accounts/password_reset_email.txt", context)
        key = hashlib.sha256(f"reset:{context['uid']}:{context['token']}".encode()).hexdigest()
        NotificationOutbox.objects.get_or_create(
            idempotency_key=key,
            defaults={"recipient": to_email, "subject": "C+ Service Desk — Recuperação de senha", "body_text": body, "template_key": "password-reset"},
        )


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_form.html"
    form_class = QueuedPasswordResetForm
    success_url = "/conta/recuperar/enviado/"

    def post(self, request, *args, **kwargs):
        key = hashlib.sha256(f"reset:{request.META.get('REMOTE_ADDR', '')}".encode()).hexdigest()
        try:
            if not cache.add(key, True, timeout=60):
                return HttpResponse("Aguarde antes de tentar novamente.", status=429)
        except Exception:
            return HttpResponse("Tente novamente mais tarde.", status=503)
        return super().post(request, *args, **kwargs)


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_form.html"
    form_class = CompletePasswordForm
    success_url = "/login/"
