"""Reglas de negocio: verificación por código, emisión de voto y resultados."""
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.db.models import Avg
from django.utils import timezone

from .models import CodigoVerificacion, Voto, Votante, Votacion

logger = logging.getLogger(__name__)


class VotoError(Exception):
    """El voto no se puede registrar (mensaje apto para mostrar al votante)."""


class LimiteCodigosError(Exception):
    """Se superó el máximo de códigos por hora."""


# ---------- Normalización de datos de identificación ----------
def solo_digitos(texto):
    return "".join(c for c in (texto or "") if c.isdigit())


def normalizar_cedula(texto):
    return solo_digitos(texto)


def normalizar_celular(texto):
    digitos = solo_digitos(texto)
    if digitos.startswith("57") and len(digitos) == 12:
        digitos = digitos[2:]
    return digitos


# ---------- Código de un solo uso ----------
def enviar_codigo(votante):
    """Genera un código de 6 dígitos (se guarda solo su hash) y lo 'envía'."""
    desde = timezone.now() - timedelta(hours=1)
    if votante.codigos.filter(creado__gte=desde).count() >= settings.CODIGOS_MAX_POR_HORA:
        raise LimiteCodigosError()
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    CodigoVerificacion.objects.create(votante=votante, codigo_hash=make_password(codigo))
    # Punto de integración: aquí se conecta el proveedor de SMS acordado con la Fundación.
    logger.info("Código generado para el votante %s", votante.pk)
    return codigo


def verificar_codigo(votante, codigo):
    registro = votante.codigos.filter(usado=False).order_by("-creado").first()
    if registro is None or not registro.vigente:
        return False
    registro.intentos += 1
    if check_password(codigo, registro.codigo_hash):
        registro.usado = True
        registro.save(update_fields=["usado", "intentos"])
        return True
    registro.save(update_fields=["intentos"])
    return False


# ---------- Emisión del voto ----------
def emitir_voto(votante, votacion, opcion, ip=None):
    """Registra un voto de forma atómica. Lanza VotoError si no es válido.

    Defensa en profundidad contra duplicados:
      1) bloqueo de la fila del votante dentro de la transacción,
      2) conteo de votos previos contra el límite de la votación,
      3) restricción UNIQUE (votante, votación, número) en la base de datos.
    """
    with transaction.atomic():
        votante = Votante.objects.select_for_update().get(pk=votante.pk)
        votacion = Votacion.objects.select_related("categoria").get(pk=votacion.pk)

        if not votante.verificado:
            raise VotoError("Debes verificar tu cuenta para votar.")
        if not votacion.abierta:
            raise VotoError("Esta votación no está abierta.")
        if opcion.votacion_id != votacion.pk or not opcion.activa:
            raise VotoError("La opción elegida no está disponible en esta votación.")
        if votacion.exigir_mayoria_edad and not votante.mayor_edad_confirmada:
            raise VotoError("Esta votación exige confirmar que eres mayor de edad.")

        previos = Voto.objects.filter(votante=votante, votacion=votacion).count()
        if previos >= votacion.votos_por_votante:
            raise VotoError("Ya votaste en esta votación. El voto no se puede cambiar.")

        try:
            with transaction.atomic():
                voto = Voto.objects.create(
                    votante=votante, votacion=votacion, opcion=opcion,
                    numero=previos + 1, ip=ip,
                )
        except IntegrityError:
            raise VotoError("Ya votaste en esta votación. El voto no se puede cambiar.")

        _revisar_cuarentena(voto)
    return voto


def _revisar_cuarentena(voto):
    """Envía a cuarentena (para revisión del administrador) ráfagas desde una misma IP."""
    limite = settings.CUARENTENA_VOTOS_POR_IP
    if not limite or not voto.ip:
        return
    desde = timezone.now() - timedelta(minutes=10)
    recientes = Voto.objects.filter(votacion=voto.votacion, ip=voto.ip, fecha__gte=desde).count()
    if recientes > limite:
        voto.en_cuarentena = True
        voto.motivo_cuarentena = f"Más de {limite} votos desde la misma IP en 10 minutos."
        voto.save(update_fields=["en_cuarentena", "motivo_cuarentena"])


# ---------- Resultados ----------
def puntaje_final(pct_publico, promedio_jurado, peso_jurado):
    """Puntaje = peso_jurado% de (promedio jurado x 10) + peso_público% del % del público."""
    peso_publico = 100 - peso_jurado
    return round(peso_jurado / 100 * (promedio_jurado * 10) + peso_publico / 100 * pct_publico, 1)


def calcular_resultados(votacion):
    """Devuelve (filas, total_votos_validos). No cuenta los votos en cuarentena."""
    total = Voto.objects.filter(votacion=votacion, en_cuarentena=False).count()
    filas = []
    for opcion in votacion.opciones.all():
        votos = opcion.votos.filter(en_cuarentena=False).count()
        pct = votos / total * 100 if total else 0.0
        promedio = opcion.calificaciones.aggregate(p=Avg("puntaje"))["p"]
        promedio = float(promedio) if promedio is not None else None
        final = puntaje_final(pct, promedio or 0.0, votacion.peso_jurado)
        filas.append({
            "opcion": opcion, "votos": votos, "pct": round(pct, 1),
            "jurado": promedio, "final": final,
        })
    filas.sort(key=lambda f: f["final"], reverse=True)
    return filas, total
