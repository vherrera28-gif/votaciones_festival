from django.conf import settings

from .models import Edicion


def global_festival(request):
    return {
        "edicion_activa": Edicion.objects.filter(activa=True).first(),
        "reglas_confirmadas": settings.REGLAS_CONFIRMADAS_POR_FUNDACION,
    }
