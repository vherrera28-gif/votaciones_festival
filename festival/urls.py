from django.urls import path

from . import views

app_name = "festival"

urlpatterns = [
    # Interfaz pública
    path("", views.inicio, name="inicio"),
    path("registro/", views.registro, name="registro"),
    path("ingresar/", views.ingresar, name="login"),
    path("verificar/", views.verificar, name="verificar"),
    path("verificar/reenviar/", views.reenviar_codigo, name="reenviar"),
    path("salir/", views.salir, name="logout"),
    path("categorias/", views.categorias, name="categorias"),
    path("categorias/<int:pk>/", views.votaciones_categoria, name="votaciones"),
    path("votaciones/<int:pk>/", views.votacion_detalle, name="votacion"),
    path("votaciones/<int:pk>/opciones/", views.opciones, name="opciones"),
    path("votaciones/<int:pk>/confirmar/", views.confirmar_voto, name="confirmar"),
    path("votaciones/<int:pk>/mi-voto/", views.mi_voto, name="mi_voto"),
    # Administración
    path("panel/", views.panel_principal, name="panel"),
    path("panel/categorias/", views.panel_categorias, name="panel_categorias"),
    path("panel/votaciones/", views.panel_votaciones, name="panel_votaciones"),
    path("panel/votaciones/<int:pk>/", views.panel_votaciones, name="panel_votacion_editar"),
    path("panel/opciones/", views.panel_opciones, name="panel_opciones"),
    path("panel/resultados/", views.panel_resultados, name="panel_resultados"),
]
