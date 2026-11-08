from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from festival.models import (CalificacionJurado, Categoria, Edicion, Opcion, Votacion, Votante)


class Command(BaseCommand):
    help = "Carga la edición 2027 con seis categorías, opciones y usuarios de prueba."

    def handle(self, *args, **opciones):
        ahora = timezone.now()
        edicion, _ = Edicion.objects.get_or_create(
            anio=2027, defaults={"nombre": "Festival de la Leyenda Vallenata", "activa": True}
        )
        nombres = ["Vallenato romántico", "Vallenato rumbero", "Acordeón",
                   "Grupo vallenato", "Solista", "Mujer del vallenato"]
        primera = None
        for orden, nombre in enumerate(nombres, start=1):
            categoria, _ = Categoria.objects.get_or_create(edicion=edicion, nombre=nombre, defaults={"orden": orden})
            apertura = ahora + timedelta(days=2) if nombre == "Grupo vallenato" else ahora - timedelta(days=1)
            votacion, creada = Votacion.objects.get_or_create(
                categoria=categoria, titulo=f"Votación {nombre} {edicion.anio}",
                defaults={"apertura": apertura, "cierre": ahora + timedelta(days=3, hours=14, minutes=22),
                          "peso_jurado": 50},  # 50/50 solo como dato de ejemplo del prototipo
            )
            if creada:
                for letra in "ABC":
                    Opcion.objects.create(votacion=votacion, nombre=f"Candidato {letra}",
                                          biografia="Biografía corta y muestra de audio o video.")
            primera = primera or votacion

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin12345")

        grupo, _ = Group.objects.get_or_create(name="Jurado")
        grupo.permissions.set(Permission.objects.filter(
            content_type__app_label="festival",
            codename__in=["add_calificacionjurado", "change_calificacionjurado", "view_calificacionjurado"],
        ))
        jurado = User.objects.filter(username="jurado1").first()
        if jurado is None:
            jurado = User.objects.create_user("jurado1", password="jurado12345", is_staff=True)
        jurado.groups.add(grupo)
        for letra, puntaje in zip("ABC", ("8.2", "7.5", "9.0")):
            opcion = primera.opciones.get(nombre=f"Candidato {letra}")
            CalificacionJurado.objects.get_or_create(jurado=jurado, opcion=opcion, defaults={"puntaje": Decimal(puntaje)})

        if not Votante.objects.filter(cedula="1234567890").exists():
            usuario = User(username="1234567890")
            usuario.set_unusable_password()
            usuario.save()
            Votante.objects.create(usuario=usuario, cedula="1234567890", celular="3001234567",
                                   mayor_edad_confirmada=True, datos_autorizados=True, verificado=True)

        self.stdout.write(self.style.SUCCESS("Datos de prueba cargados."))
        self.stdout.write("Admin:   admin / admin12345        (cámbiala fuera de pruebas)")
        self.stdout.write("Jurado:  jurado1 / jurado12345     (solo Django Admin)")
        self.stdout.write("Votante: cédula 1234567890, celular 3001234567 (el código aparece en pantalla)")
