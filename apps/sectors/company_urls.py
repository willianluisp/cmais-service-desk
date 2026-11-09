from django.urls import path

from . import company_views as views

app_name = "companies"
urlpatterns = [
    path("", views.manage, name="manage"),
    path("novo/", views.create, name="create"),
    path("<int:pk>/editar/", views.edit, name="edit"),
    path("<int:pk>/excluir/", views.delete, name="delete"),
]
