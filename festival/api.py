"""API JSON de solo lectura para consumo de frontends externos."""
from django.db.models import Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Categoria, Edicion, Opcion


@require_GET
def categorias(request):
    """GET /api/categorias/

    Devuelve las categorías de la edición activa con sus votaciones y opciones
    activas: categoría -> votaciones -> opciones. No expone las reglas internas
    (peso del jurado, mayoría de edad, votos por votante).
    """
    edicion = Edicion.objects.filter(activa=True).first()
    datos = []
    if edicion:
        consulta = Categoria.objects.filter(edicion=edicion).prefetch_related(
            Prefetch(
                "votaciones__opciones",
                queryset=Opcion.objects.filter(activa=True),
            )
        )
        for categoria in consulta:
            datos.append({
                "id": categoria.pk,
                "nombre": categoria.nombre,
                "orden": categoria.orden,
                "activa": categoria.activa,
                "votaciones": [
                    {
                        "id": votacion.pk,
                        "titulo": votacion.titulo,
                        "apertura": votacion.apertura.isoformat(),
                        "cierre": votacion.cierre.isoformat(),
                        "opciones": [
                            {
                                "id": opcion.pk,
                                "nombre": opcion.nombre,
                                "biografia": opcion.biografia,
                                "media_url": opcion.media_url,
                            }
                            for opcion in votacion.opciones.all()
                        ],
                    }
                    for votacion in categoria.votaciones.all()
                ],
            })
    return JsonResponse(datos, safe=False, json_dumps_params={"ensure_ascii": False})
