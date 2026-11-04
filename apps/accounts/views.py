from hashlib import sha256

from django.conf import settings
from django.contrib.auth import login, logout
from django.core.cache import cache
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .forms import DomainAuthenticationForm

LOGIN_ERROR = "Não foi possível entrar. Verifique o acesso ou tente novamente."


def _login_attempt_allowed(request):
    # REMOTE_ADDR is the direct peer. Never trust client-supplied forwarding headers.
    ip = request.META.get("REMOTE_ADDR", "unknown")
    username = request.POST.get("username", "").strip().casefold()
    keys = [sha256(f"ip:{ip}".encode()).hexdigest(), sha256(f"user:{username}".encode()).hexdigest()]
    allowed = True
    for digest in keys:
        key = f"portal:login:{digest}"
        if cache.add(key, 1, timeout=300):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                # If a counter expires between add/incr, retry on the next request.
                return False
        if count > 10:
            allowed = False
    return allowed


@sensitive_post_parameters("password")
@never_cache
@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request):
    local_enabled = getattr(settings, "LOCAL_AUTH_ENABLED", False)
    enabled = settings.LDAP_ENABLED or local_enabled
    form = DomainAuthenticationForm(request=request) if enabled else None
    status = 200
    error = ""
    target = request.POST.get("next", request.GET.get("next", ""))
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        target = settings.LOGIN_REDIRECT_URL
    if request.method == "POST":
        if not enabled:
            status = 503
        else:
            try:
                allowed = _login_attempt_allowed(request)
            except Exception:
                # Cache failures must not turn distributed throttling into an authentication bypass.
                allowed = False
                status = 503
            if not allowed:
                status = status if status == 503 else 429
                error = LOGIN_ERROR
            else:
                form = DomainAuthenticationForm(request=request, data=request.POST)
                if form.is_valid():
                    login(request, form.get_user())
                    if local_enabled and form.get_user().local_account.must_change_password:
                        return redirect("password_change")
                    return redirect(target)
    return TemplateResponse(request, "accounts/login.html", {
        "active_page": "login", "ldap_enabled": enabled, "local_enabled": local_enabled,
        "form": form, "login_error": error, "next": target,
    }, status=status)


@never_cache
@csrf_protect
@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")
