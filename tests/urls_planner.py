from django.urls import include, path

urlpatterns = [path("", include("apps.planner_integration.urls"))]
