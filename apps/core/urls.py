from django.urls import path
from django.views.generic import TemplateView

from apps.accounts import local_views

from . import health, views

urlpatterns = [
    path("conta/", views.account, name="account"),
    path("conta/senha/", local_views.PasswordChangeView.as_view(), name="password_change"),
    path("conta/recuperar/", local_views.PasswordResetView.as_view(), name="password_reset"),
    path("conta/recuperar/enviado/", TemplateView.as_view(template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("conta/redefinir/<uidb64>/<token>/", local_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("", views.home, name="home"),
    path("login/", views.login_unavailable, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("integracoes/", views.integrations, name="integrations"),
    path("health/live/", health.live, name="health-live"),
    path("health/ready/", health.ready, name="health-ready"),
]
