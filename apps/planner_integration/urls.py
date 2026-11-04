from django.urls import path

from . import admin_panel, views

app_name = "planner"
urlpatterns = [
    path("integracoes/microsoft/buckets/", admin_panel.refresh_buckets, name="buckets"),
    path("integracoes/microsoft/mapeamento/", admin_panel.save_mapping, name="mapping"),
    path("integracoes/microsoft/teste/", admin_panel.test_task, name="test-task"),
    path("integracoes/microsoft/conectar/", views.connect_microsoft, name="connect"),
    path("integracoes/microsoft/callback/", views.microsoft_callback, name="callback"),
    path("chamados/<uuid:ticket_id>/sincronizar/", views.synchronize, name="sync"),
]
