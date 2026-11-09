from django.urls import path

from . import lifecycle_views, views

app_name = "tickets"
urlpatterns = [
    path('chamados/<uuid:pk>/excluir/', lifecycle_views.soft_delete, name='delete'),
    path('chamados/arquivados/', lifecycle_views.archived, name='archived'),
    path('chamados/<uuid:pk>/arquivar/', lifecycle_views.archive, name='archive'),
    path('chamados/<uuid:pk>/restaurar/', lifecycle_views.restore, name='restore'),
    path('chamados/<uuid:pk>/excluir-permanentemente/', lifecycle_views.permanent_delete, name='permanent-delete'),
    path("chamados/", views.ticket_list, name="list"),
    path("chamados/novo/", views.ticket_create, name="create"),
    path("chamados/novo/suporte/", views.ticket_create, {"standard": True}, name="standard-create"),
    path("chamados/<uuid:pk>/", views.ticket_detail, name="detail"),
    path("chamados/<uuid:pk>/anexos/<uuid:attachment_id>/", views.attachment_download,
         name="attachment"),
    path(
        "chamados/<uuid:pk>/anexos/<uuid:attachment_id>/visualizar/",
        views.attachment_preview,
        name="attachment-preview",
    ),
]
