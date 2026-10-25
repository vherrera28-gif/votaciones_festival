from django.contrib import admin

from .models import (CalificacionJurado, Categoria, CodigoVerificacion, Edicion, Opcion,
                     Votacion, Votante, Voto)

admin.site.site_header = "Festival de la Leyenda Vallenata · Administración"
admin.site.site_title = "Votaciones"
admin.site.index_title = "Gestión de ediciones, categorías y votaciones"


@admin.register(Edicion)
class EdicionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "anio", "activa")


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "edicion", "orden", "activa")
    list_filter = ("edicion", "activa")


class OpcionInline(admin.TabularInline):
    model = Opcion
    extra = 2


@admin.register(Votacion)
class VotacionAdmin(admin.ModelAdmin):
    list_display = ("titulo", "categoria", "apertura", "cierre", "peso_jurado", "estado_actual", "pausada")
    list_filter = ("categoria__edicion", "categoria", "pausada")
    inlines = [OpcionInline]

    @admin.display(description="Estado")
    def estado_actual(self, obj):
        return obj.estado_texto


@admin.register(Opcion)
class OpcionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "votacion", "activa")
    list_filter = ("votacion__categoria__edicion", "activa")


@admin.register(Votante)
class VotanteAdmin(admin.ModelAdmin):
    list_display = ("cedula_oculta", "celular", "verificado", "mayor_edad_confirmada", "creado")
    list_filter = ("verificado", "mayor_edad_confirmada")
    search_fields = ("cedula", "celular")
    readonly_fields = ("usuario", "creado", "fecha_autorizacion")


@admin.register(Voto)
class VotoAdmin(admin.ModelAdmin):
    list_display = ("votante", "votacion", "opcion", "fecha", "ip", "en_cuarentena")
    list_filter = ("en_cuarentena", "votacion")
    readonly_fields = ("votante", "votacion", "opcion", "numero", "fecha", "ip")
    actions = ["enviar_a_cuarentena", "liberar_de_cuarentena"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # un voto emitido no se borra desde la aplicación

    @admin.action(description="Enviar los votos seleccionados a cuarentena")
    def enviar_a_cuarentena(self, request, queryset):
        queryset.update(en_cuarentena=True, motivo_cuarentena="Marcado manualmente por un administrador.")

    @admin.action(description="Liberar los votos seleccionados de la cuarentena")
    def liberar_de_cuarentena(self, request, queryset):
        queryset.update(en_cuarentena=False, motivo_cuarentena="")


@admin.register(CalificacionJurado)
class CalificacionJuradoAdmin(admin.ModelAdmin):
    list_display = ("opcion", "jurado", "puntaje")
    list_filter = ("opcion__votacion",)

    def get_exclude(self, request, obj=None):
        return None if request.user.is_superuser else ("jurado",)

    def get_queryset(self, request):
        consulta = super().get_queryset(request)
        return consulta if request.user.is_superuser else consulta.filter(jurado=request.user)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.jurado = request.user
            previa = CalificacionJurado.objects.filter(jurado=request.user, opcion=obj.opcion).first()
            if previa and previa.pk != obj.pk:  # calificar de nuevo actualiza la anterior
                previa.puntaje = obj.puntaje
                previa.save()
                return
        super().save_model(request, obj, form, change)


admin.site.register(CodigoVerificacion)
