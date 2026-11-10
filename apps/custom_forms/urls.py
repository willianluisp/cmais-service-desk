from django.urls import path

from . import views

app_name = "custom_forms"
urlpatterns = [
    path("administracao/formularios/", views.manage, name="manage"),
    path("administracao/formularios/lixeira/", views.trash, name="trash"),
    path("administracao/formularios/ordenar/", views.ordering, name="ordering"),
    path("administracao/formularios/<uuid:pk>/excluir-definitivamente/", views.permanent_delete, name="permanent-delete"),
    path("administracao/formularios/novo/", views.editor, name="new"),
    path("administracao/formularios/suporte/", views.configure_support, name="configure-support"),
    path("administracao/formularios/previa/", views.preview, name="preview"),
    path("administracao/formularios/<uuid:pk>/", views.editor, name="edit"),
    path("administracao/formularios/<uuid:pk>/acao/", views.action, name="action"),
    path("chamados/novo/formulario/<uuid:pk>/", views.request_form, name="request"),
]
