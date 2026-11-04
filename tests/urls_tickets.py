from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path("", include("apps.tickets.urls")),
    path("", include("apps.planner_integration.urls")),
    path("", lambda request: HttpResponse("home"), name="home"),
    path("logout/", lambda request: HttpResponse("logout"), name="logout"),
    path("login/", lambda request: HttpResponse("login"), name="login"),
    path("integracoes/", lambda request: HttpResponse("integrations"), name="integrations"),
]
