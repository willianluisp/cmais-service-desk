from django.urls import include, path

from apps.core.admin import portal_admin

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.tickets.urls")),
    path("", include("apps.custom_forms.urls")),
    path("administracao/setores/", include("apps.sectors.urls")),
    path("", include("apps.planner_integration.urls")),
    path("admin/", portal_admin.urls),
]
