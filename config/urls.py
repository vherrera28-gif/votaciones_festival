from django.contrib import admin
from django.urls import include, path

from festival import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/categorias/", api.categorias, name="api_categorias"),
    path("", include("festival.urls")),
]
