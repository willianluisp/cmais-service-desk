from django.urls import path

from . import admin_panel, views

app_name = "planner"
urlpatterns = [
    path('integracoes/microsoft/conferir-envios/', admin_panel.review_sends, name='review-sends'),
    path('integracoes/microsoft/vincular-envio/', admin_panel.resolve_send, name='resolve-send'),
    path('integracoes/microsoft/planos/', admin_panel.refresh_plans, name='plans'),
    path('integracoes/microsoft/plano/', admin_panel.select_plan, name='plan'),
    path('integracoes/microsoft/automacao/', admin_panel.toggle_automation, name='automation'),
    path('integracoes/microsoft/testar-conexao/', admin_panel.test_connection, name='test-connection'),
    path('integracoes/microsoft/sincronizar/', admin_panel.synchronize_now, name='sync-now'),
    path("integracoes/microsoft/configurar/", admin_panel.configure_oauth, name="configure"),
    path("integracoes/microsoft/desconectar/", admin_panel.disconnect_microsoft, name="disconnect"),
    path("integracoes/microsoft/buckets/", admin_panel.refresh_buckets, name="buckets"),
    path("integracoes/microsoft/mapeamento/", admin_panel.save_mapping, name="mapping"),
    path("integracoes/microsoft/teste/", admin_panel.test_task, name="test-task"),
    path("integracoes/microsoft/conectar/", views.connect_microsoft, name="connect"),
    path("integracoes/microsoft/callback/", views.microsoft_callback, name="callback"),
    path("chamados/<uuid:ticket_id>/sincronizar/", views.synchronize, name="sync"),
    path('chamados/<uuid:ticket_id>/checklist/aceitar-remoto/', views.accept_checklist_remote, name='accept-checklist-remote'),
]
