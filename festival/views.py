import csv
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CodigoForm, LoginForm, RegistroForm, VotacionForm
from .models import Categoria, Edicion, Opcion, Voto, Votacion, Votante
from .services import (LimiteCodigosError, VotoError, calcular_resultados, emitir_voto,
                       enviar_codigo, verificar_codigo)


# ---------------------------------------------------------------- utilidades
def _edicion():
    return Edicion.objects.filter(activa=True).first()


def _votante(request):
    return getattr(request.user, "votante", None)


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _guardar_siguiente(request):
    destino = request.GET.get("next")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        request.session["siguiente"] = destino


def administrador_requerido(vista):
    """Solo personal con permiso para gestionar votaciones (los jurados quedan fuera)."""
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("admin:login"))
        if not (request.user.is_staff and request.user.has_perm("festival.change_votacion")):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return envoltura


# ---------------------------------------------------------------- registro e ingreso
def _enviar_y_redirigir(request, votante):
    try:
        codigo = enviar_codigo(votante)
    except LimiteCodigosError:
        messages.error(request, "Superaste el límite de códigos por hora. Intenta de nuevo más tarde.")
        return redirect("festival:login")
    request.session["votante_pendiente"] = votante.pk
    if settings.MOSTRAR_CODIGO_EN_PANTALLA:
        messages.info(request, f"Modo demostración: tu código es {codigo}.")
    else:
        messages.info(request, "Te enviamos un código de 6 dígitos a tu celular.")
    return redirect("festival:verificar")


def registro(request):
    if request.user.is_authenticated:
        return redirect("festival:categorias")
    _guardar_siguiente(request)
    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cedula = form.cleaned_data["cedula"]
        celular = form.cleaned_data["celular"]
        votante = Votante.objects.filter(cedula=cedula).first()
        celular_ocupado = (
            Votante.objects.filter(celular=celular, verificado=True)
            .exclude(pk=getattr(votante, "pk", None)).exists()
        )
        if (votante and votante.verificado) or celular_ocupado:
            form.add_error(None, "Ya existe una cuenta con estos datos. Inicia sesión.")
        else:
            with transaction.atomic():
                # Libera el celular si otra cuenta lo reservó sin llegar a verificarse.
                User.objects.filter(votante__celular=celular, votante__verificado=False) \
                    .exclude(votante__cedula=cedula).delete()
                if votante is None:
                    usuario = User(username=cedula)
                    usuario.set_unusable_password()
                    usuario.save()
                    votante = Votante(usuario=usuario, cedula=cedula)
                votante.celular = celular
                votante.mayor_edad_confirmada = form.cleaned_data["mayor_edad"]
                votante.datos_autorizados = True
                votante.fecha_autorizacion = timezone.now()
                votante.save()
            return _enviar_y_redirigir(request, votante)
    return render(request, "festival/registro.html", {"form": form, "seccion": "publica"})


def ingresar(request):
    if request.user.is_authenticated:
        return redirect("festival:categorias")
    _guardar_siguiente(request)
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        votante = Votante.objects.filter(
            cedula=form.cleaned_data["cedula"], celular=form.cleaned_data["celular"], verificado=True
        ).first()
        if votante is None:
            form.add_error(None, "No encontramos una cuenta con esos datos. Revisa la cédula y el celular o crea una cuenta.")
        else:
            return _enviar_y_redirigir(request, votante)
    return render(request, "festival/login.html", {"form": form, "seccion": "publica"})


def verificar(request):
    pk = request.session.get("votante_pendiente")
    votante = Votante.objects.filter(pk=pk).select_related("usuario").first() if pk else None
    if votante is None:
        return redirect("festival:login")
    form = CodigoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if verificar_codigo(votante, form.cleaned_data["codigo"]):
            destino = request.session.pop("siguiente", None)
            request.session.pop("votante_pendiente", None)
            if not votante.verificado:
                votante.verificado = True
                votante.save(update_fields=["verificado"])
            login(request, votante.usuario, backend="django.contrib.auth.backends.ModelBackend")
            if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
                return redirect(destino)
            return redirect("festival:categorias")
        form.add_error("codigo", "Código incorrecto o vencido. Puedes pedir uno nuevo.")
    return render(request, "festival/verificar.html", {"form": form, "votante": votante, "seccion": "publica"})


@require_POST
def reenviar_codigo(request):
    pk = request.session.get("votante_pendiente")
    votante = Votante.objects.filter(pk=pk).first() if pk else None
    if votante is None:
        return redirect("festival:login")
    return _enviar_y_redirigir(request, votante)


@require_POST
def salir(request):
    logout(request)
    return redirect("festival:inicio")


# ---------------------------------------------------------------- interfaz pública
def inicio(request):
    edicion = _edicion()
    votaciones = (
        Votacion.objects.filter(categoria__edicion=edicion).select_related("categoria") if edicion else []
    )
    abiertas = [v for v in votaciones if v.estado == "abierta"]
    restante = None
    if abiertas:
        segundos = max(int((min(v.cierre for v in abiertas) - timezone.now()).total_seconds()), 0)
        restante = {"d": segundos // 86400, "h": segundos % 86400 // 3600, "m": segundos % 3600 // 60}
    total_categorias = edicion.categorias.count() if edicion else 0
    return render(request, "festival/inicio.html", {
        "restante": restante, "total_categorias": total_categorias, "seccion": "publica",
    })


def categorias(request):
    edicion = _edicion()
    votante = _votante(request)
    ya_votadas = set()
    if votante and edicion:
        ya_votadas = set(
            Voto.objects.filter(votante=votante, votacion__categoria__edicion=edicion)
            .values_list("votacion__categoria_id", flat=True)
        )
    lista = []
    if edicion:
        for c in edicion.categorias.prefetch_related("votaciones"):
            lista.append({"obj": c, "votada": c.pk in ya_votadas})
    return render(request, "festival/categorias.html", {
        "categorias": lista, "votadas": len(ya_votadas), "total": len(lista),
        "autenticado_votante": votante is not None, "seccion": "publica",
    })


def votaciones_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk, edicion__activa=True)
    return render(request, "festival/votaciones.html", {
        "categoria": categoria, "votaciones": categoria.votaciones.select_related("categoria"),
        "seccion": "publica",
    })


def votacion_detalle(request, pk):
    votacion = get_object_or_404(Votacion.objects.select_related("categoria"), pk=pk)
    return render(request, "festival/votacion_detalle.html", {
        "votacion": votacion, "n_opciones": votacion.opciones.filter(activa=True).count(),
        "seccion": "publica",
    })


def opciones(request, pk):
    votacion = get_object_or_404(Votacion.objects.select_related("categoria"), pk=pk)
    ya_voto = False
    votante = _votante(request)
    if votante:
        ya_voto = Voto.objects.filter(votante=votante, votacion=votacion).count() >= votacion.votos_por_votante
    return render(request, "festival/opciones.html", {
        "votacion": votacion, "opciones": votacion.opciones.filter(activa=True),
        "ya_voto": ya_voto, "seccion": "publica",
    })


@login_required
def confirmar_voto(request, pk):
    votacion = get_object_or_404(Votacion.objects.select_related("categoria"), pk=pk)
    votante = _votante(request)
    if votante is None:
        messages.error(request, "Esta cuenta no es de votante. Ingresa con tu cédula y celular para votar.")
        return redirect("festival:inicio")

    valor = request.POST.get("opcion") if request.method == "POST" else request.GET.get("opcion")
    opcion = get_object_or_404(Opcion, pk=_entero(valor), votacion=votacion, activa=True)

    if request.method == "POST":
        try:
            emitir_voto(votante, votacion, opcion, ip=request.META.get("REMOTE_ADDR"))
        except VotoError as error:
            messages.error(request, str(error))
            return redirect("festival:mi_voto", pk=votacion.pk)
        messages.success(request, "¡Tu voto fue registrado!")
        return redirect("festival:mi_voto", pk=votacion.pk)

    if Voto.objects.filter(votante=votante, votacion=votacion).count() >= votacion.votos_por_votante:
        messages.error(request, "Ya votaste en esta votación. El voto no se puede cambiar.")
        return redirect("festival:mi_voto", pk=votacion.pk)
    return render(request, "festival/confirmar.html", {
        "votacion": votacion, "opcion": opcion, "seccion": "publica",
    })


@login_required
def mi_voto(request, pk):
    votacion = get_object_or_404(Votacion.objects.select_related("categoria"), pk=pk)
    votante = _votante(request)
    votos = []
    if votante:
        votos = list(Voto.objects.filter(votante=votante, votacion=votacion).select_related("opcion"))
    return render(request, "festival/mi_voto.html", {
        "votacion": votacion, "votos": votos, "seccion": "publica",
    })


# ---------------------------------------------------------------- administración
@administrador_requerido
def panel_principal(request):
    edicion = _edicion()
    votos = Voto.objects.filter(votacion__categoria__edicion=edicion)
    votaciones = Votacion.objects.filter(categoria__edicion=edicion).select_related("categoria")
    return render(request, "festival/panel/principal.html", {
        "votos_totales": votos.count(),
        "abiertas": sum(1 for v in votaciones if v.estado == "abierta"),
        "cuarentena": votos.filter(en_cuarentena=True).count(),
        "seccion": "panel", "subseccion": "principal",
    })


@administrador_requerido
def panel_categorias(request):
    edicion = _edicion()
    if request.method == "POST":
        if edicion is None:
            messages.error(request, "No hay una edición activa. Crea o activa una en Django Admin.")
            return redirect("festival:panel_categorias")
        accion = request.POST.get("accion")
        if accion == "crear":
            nombre = request.POST.get("nombre", "").strip()
            if not nombre:
                messages.error(request, "Escribe el nombre de la categoría.")
            elif Categoria.objects.filter(edicion=edicion, nombre__iexact=nombre).exists():
                messages.error(request, "Ya existe una categoría con ese nombre en esta edición.")
            else:
                Categoria.objects.create(edicion=edicion, nombre=nombre, orden=edicion.categorias.count() + 1)
                messages.success(request, f"Categoría «{nombre}» creada.")
        elif accion == "alternar":
            categoria = get_object_or_404(Categoria, pk=_entero(request.POST.get("id")), edicion=edicion)
            categoria.activa = not categoria.activa
            categoria.save(update_fields=["activa"])
            messages.success(request, f"Categoría «{categoria.nombre}» {'reanudada' if categoria.activa else 'pausada'}.")
        return redirect("festival:panel_categorias")
    lista = []
    if edicion:
        for c in edicion.categorias.prefetch_related("votaciones__opciones"):
            n = sum(v.opciones.filter(activa=True).count() for v in c.votaciones.all())
            lista.append({"obj": c, "n_opciones": n})
    return render(request, "festival/panel/categorias.html", {
        "categorias": lista, "seccion": "panel", "subseccion": "categorias",
    })


@administrador_requerido
def panel_votaciones(request, pk=None):
    edicion = _edicion()
    instancia = get_object_or_404(Votacion, pk=pk, categoria__edicion=edicion) if pk else None
    form = VotacionForm(request.POST or None, instance=instancia, edicion=edicion)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votación guardada.")
        return redirect("festival:panel_votaciones")
    votaciones = Votacion.objects.filter(categoria__edicion=edicion).select_related("categoria")
    return render(request, "festival/panel/votaciones.html", {
        "votaciones": votaciones, "form": form, "editando": instancia,
        "seccion": "panel", "subseccion": "votaciones",
    })


@administrador_requerido
def panel_opciones(request):
    edicion = _edicion()
    votaciones = list(Votacion.objects.filter(categoria__edicion=edicion).select_related("categoria"))
    pedida = _entero(request.GET.get("votacion") or request.POST.get("votacion"))
    seleccionada = next((v for v in votaciones if v.pk == pedida), votaciones[0] if votaciones else None)

    if request.method == "POST" and seleccionada:
        accion = request.POST.get("accion")
        if accion == "agregar":
            nombre = request.POST.get("nombre", "").strip()
            if not nombre:
                messages.error(request, "Escribe el nombre de la nueva opción.")
            elif seleccionada.opciones.filter(nombre__iexact=nombre).exists():
                messages.error(request, "Esa opción ya existe en esta votación.")
            else:
                Opcion.objects.create(votacion=seleccionada, nombre=nombre)
                messages.success(request, f"Opción «{nombre}» agregada.")
        elif accion in ("quitar", "reactivar"):
            opcion = get_object_or_404(Opcion, pk=_entero(request.POST.get("id")), votacion=seleccionada)
            if accion == "reactivar":
                opcion.activa = True
                opcion.save(update_fields=["activa"])
                messages.success(request, f"Opción «{opcion.nombre}» reactivada.")
            elif opcion.votos.exists() or opcion.calificaciones.exists():
                opcion.activa = False
                opcion.save(update_fields=["activa"])
                messages.warning(request, "La opción ya tiene votos o calificaciones: se desactivó para conservar el historial.")
            else:
                opcion.delete()
                messages.success(request, "Opción eliminada.")
        return redirect(f"{reverse('festival:panel_opciones')}?votacion={seleccionada.pk}")

    return render(request, "festival/panel/opciones.html", {
        "votaciones": votaciones, "seleccionada": seleccionada,
        "opciones": seleccionada.opciones.all() if seleccionada else [],
        "seccion": "panel", "subseccion": "opciones",
    })


@administrador_requerido
def panel_resultados(request):
    edicion = _edicion()
    votaciones = list(Votacion.objects.filter(categoria__edicion=edicion).select_related("categoria"))
    pedida = _entero(request.GET.get("votacion"))
    seleccionada = next((v for v in votaciones if v.pk == pedida), votaciones[0] if votaciones else None)
    filas, total, cuarentena = [], 0, 0
    if seleccionada:
        filas, total = calcular_resultados(seleccionada)
        cuarentena = Voto.objects.filter(votacion=seleccionada, en_cuarentena=True).count()

    if seleccionada and "exportar" in request.GET:
        respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
        respuesta["Content-Disposition"] = f'attachment; filename="acta_votacion_{seleccionada.pk}.csv"'
        respuesta.write("\ufeff")  # BOM para que Excel lea bien los acentos
        w = csv.writer(respuesta)
        w.writerow(["Acta de resultados", seleccionada.titulo])
        w.writerow(["Generada", timezone.localtime().strftime("%Y-%m-%d %H:%M")])
        w.writerow(["Estado", "Resultado parcial" if seleccionada.estado != "cerrada" else "Resultado final"])
        w.writerow(["Peso jurado %", seleccionada.peso_jurado, "Peso público %", seleccionada.peso_publico])
        w.writerow([])
        w.writerow(["Opción", "Votos válidos", "Público %", "Jurado (1-10)", "Puntaje final"])
        for f in filas:
            w.writerow([f["opcion"].nombre, f["votos"], f["pct"],
                        "" if f["jurado"] is None else round(f["jurado"], 1), f["final"]])
        w.writerow([])
        w.writerow(["Total votos válidos", total, "Votos en cuarentena (no cuentan)", cuarentena])
        return respuesta

    return render(request, "festival/panel/resultados.html", {
        "votaciones": votaciones, "seleccionada": seleccionada, "filas": filas,
        "total": total, "cuarentena": cuarentena,
        "seccion": "panel", "subseccion": "resultados",
    })
