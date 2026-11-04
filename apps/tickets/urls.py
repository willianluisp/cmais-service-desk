from django.urls import path

from . import views

app_name = "tickets"
urlpatterns = [
    path("chamados/", views.ticket_list, name="list"),
    path("chamados/novo/", views.ticket_create, name="create"),
    path("chamados/<uuid:pk>/", views.ticket_detail, name="detail"),
    path("chamados/<uuid:pk>/anexos/<uuid:attachment_id>/", views.attachment_download,
         name="attachment"),
    path(
        "chamados/<uuid:pk>/anexos/<uuid:attachment_id>/visualizar/",
        views.attachment_preview,
        name="attachment-preview",
    ),
]
