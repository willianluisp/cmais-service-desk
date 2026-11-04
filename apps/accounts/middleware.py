from django.http import JsonResponse
from django.shortcuts import redirect

from .models import LocalAccount


class RequirePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and LocalAccount.objects.filter(
            user=request.user, must_change_password=True,
        ).exists() and request.path not in {"/conta/senha/", "/logout/"}:
            if request.path.startswith("/api/") or request.headers.get("HX-Request"):
                return JsonResponse({"code": "PASSWORD_CHANGE_REQUIRED"}, status=403)
            return redirect("password_change")
        return self.get_response(request)
