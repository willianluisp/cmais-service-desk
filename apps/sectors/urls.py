from django.urls import path

from . import views

app_name = "sectors"
urlpatterns = [
    path("", views.manage, name="manage"),
    path("novo/", views.create, name="create"),
    path("<int:pk>/editar/", views.edit, name="edit"),
    path("<int:pk>/excluir/", views.delete, name="delete"),
]
