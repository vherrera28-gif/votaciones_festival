"""Modelos del sistema de votaciones.

Jerarquía escalable:  Edición -> Categoría -> Votación -> Opción.
Las reglas aún no confirmadas por la Fundación (jurado, mayoría de edad,
límite de votos) son campos configurables, no código.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

ETIQUETAS_ESTADO = {
    "abierta": "Abierta",
    "proxima": "Próximamente",
    "cerrada": "Cerrada",
    "pausada": "Pausada",
    "sin_votacion": "Sin votación",
}

solo_digitos = RegexValidator(r"^\d+$", "Solo se permiten números.")
celular_colombiano = RegexValidator(
    r"^3\d{9}$", "Celular colombiano de 10 dígitos que empiece por 3."
)


class Edicion(models.Model):
    nombre = models.CharField(max_length=120)
    anio = models.PositiveSmallIntegerField("año", unique=True)
    activa = models.BooleanField(default=False, help_text="Solo una edición puede estar activa.")

    class Meta:
        verbose_name = "edición"
        verbose_name_plural = "ediciones"
        ordering = ["-anio"]

    def __str__(self):
        return f"{self.nombre} {self.anio}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.activa:
            Edicion.objects.exclude(pk=self.pk).update(activa=False)


class Categoria(models.Model):
    edicion = models.ForeignKey(Edicion, on_delete=models.CASCADE, related_name="categorias")
    nombre = models.CharField(max_length=100)
    orden = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True, help_text="Desmarcar equivale a pausar la categoría.")

    class Meta:
        verbose_name = "categoría"
        ordering = ["orden", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["edicion", "nombre"], name="categoria_unica_por_edicion")
        ]

    def __str__(self):
        return f"{self.nombre} ({self.edicion.anio})"

    @property
    def estado(self):
        if not self.activa:
            return "pausada"
        estados = [v.estado for v in self.votaciones.all()]
        for prioridad in ("abierta", "proxima", "pausada", "cerrada"):
            if prioridad in estados:
                return prioridad
        return "sin_votacion"

    @property
    def estado_texto(self):
        return ETIQUETAS_ESTADO[self.estado]

    @property
    def votaciones_abiertas(self):
        return sum(1 for v in self.votaciones.all() if v.estado == "abierta")


class Votacion(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name="votaciones")
    titulo = models.CharField(max_length=150)
    apertura = models.DateTimeField()
    cierre = models.DateTimeField()
    # --- Reglas configurables (propuestas pendientes de confirmación) ---
    peso_jurado = models.PositiveSmallIntegerField(
        "peso del jurado (%)", default=0, validators=[MaxValueValidator(100)],
        help_text="0 = solo cuenta el voto del público.",
    )
    exigir_mayoria_edad = models.BooleanField("exigir mayoría de edad", default=True)
    votos_por_votante = models.PositiveSmallIntegerField(
        "votos por votante", default=1, validators=[MinValueValidator(1)]
    )
    pausada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "votación"
        verbose_name_plural = "votaciones"
        ordering = ["categoria__orden", "apertura"]

    def __str__(self):
        return self.titulo

    def clean(self):
        if self.apertura and self.cierre and self.cierre <= self.apertura:
            raise ValidationError("El cierre debe ser posterior a la apertura.")

    @property
    def peso_publico(self):
        return 100 - self.peso_jurado

    @property
    def estado(self):
        if self.pausada or not self.categoria.activa:
            return "pausada"
        ahora = timezone.now()
        if ahora < self.apertura:
            return "proxima"
        if ahora >= self.cierre:
            return "cerrada"
        return "abierta"

    @property
    def estado_texto(self):
        return ETIQUETAS_ESTADO[self.estado]

    @property
    def abierta(self):
        return self.estado == "abierta"


class Opcion(models.Model):
    votacion = models.ForeignKey(Votacion, on_delete=models.CASCADE, related_name="opciones")
    nombre = models.CharField(max_length=150)
    biografia = models.TextField(blank=True)
    media_url = models.URLField("enlace de audio o video", blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "opción"
        verbose_name_plural = "opciones"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["votacion", "nombre"], name="opcion_unica_por_votacion")
        ]

    def __str__(self):
        return f"{self.nombre} · {self.votacion.titulo}"


class Votante(models.Model):
    """Identidad del votante: la CÉDULA identifica a la persona; el CELULAR es el
    canal de verificación (código de un solo uso). Ambos son únicos."""

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name="votante")
    cedula = models.CharField("cédula", max_length=10, unique=True, validators=[solo_digitos])
    celular = models.CharField(max_length=10, unique=True, validators=[celular_colombiano])
    mayor_edad_confirmada = models.BooleanField(default=False)
    datos_autorizados = models.BooleanField("autoriza tratamiento de datos", default=False)
    fecha_autorizacion = models.DateTimeField(null=True, blank=True)
    verificado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"C.C. {self.cedula_oculta}"

    @property
    def cedula_oculta(self):
        return "*" * max(len(self.cedula) - 3, 0) + self.cedula[-3:]


class CodigoVerificacion(models.Model):
    votante = models.ForeignKey(Votante, on_delete=models.CASCADE, related_name="codigos")
    codigo_hash = models.CharField(max_length=128)
    creado = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)
    intentos = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "código de verificación"
        verbose_name_plural = "códigos de verificación"

    @property
    def vigente(self):
        limite = self.creado + timedelta(minutes=settings.CODIGO_VIGENCIA_MIN)
        return (not self.usado) and timezone.now() < limite and self.intentos < settings.CODIGO_MAX_INTENTOS


class Voto(models.Model):
    votante = models.ForeignKey(Votante, on_delete=models.PROTECT, related_name="votos")
    votacion = models.ForeignKey(Votacion, on_delete=models.PROTECT, related_name="votos")
    opcion = models.ForeignKey(Opcion, on_delete=models.PROTECT, related_name="votos")
    numero = models.PositiveSmallIntegerField(default=1, help_text="Consecutivo del voto del votante en esta votación.")
    fecha = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    en_cuarentena = models.BooleanField(default=False)
    motivo_cuarentena = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            # Con el límite por defecto (1 voto) esto equivale a: un voto por votante y votación.
            models.UniqueConstraint(fields=["votante", "votacion", "numero"], name="voto_unico_por_numero")
        ]

    def __str__(self):
        return f"{self.votante} → {self.opcion.nombre}"


class CalificacionJurado(models.Model):
    jurado = models.ForeignKey(User, on_delete=models.CASCADE, related_name="calificaciones")
    opcion = models.ForeignKey(Opcion, on_delete=models.CASCADE, related_name="calificaciones")
    puntaje = models.DecimalField(
        max_digits=3, decimal_places=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )

    class Meta:
        verbose_name = "calificación de jurado"
        verbose_name_plural = "calificaciones de jurado"
        constraints = [
            models.UniqueConstraint(fields=["jurado", "opcion"], name="calificacion_unica_por_jurado")
        ]

    def clean(self):
        if self.opcion_id and self.opcion.votacion.peso_jurado == 0:
            raise ValidationError("Esta votación no usa jurado (peso del jurado = 0).")

    def __str__(self):
        return f"{self.opcion.nombre}: {self.puntaje}"
