from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CalificacionJurado, Categoria, Edicion, Opcion, Votacion, Votante, Voto
from .services import (LimiteCodigosError, VotoError, calcular_resultados, emitir_voto,
                       enviar_codigo, puntaje_final)


def crear_votante(cedula="1234567890", celular="3001234567", mayor=True, verificado=True):
    usuario = User(username=cedula)
    usuario.set_unusable_password()
    usuario.save()
    return Votante.objects.create(
        usuario=usuario, cedula=cedula, celular=celular, mayor_edad_confirmada=mayor,
        datos_autorizados=True, verificado=verificado,
    )


class BaseTest(TestCase):
    def setUp(self):
        ahora = timezone.now()
        self.edicion = Edicion.objects.create(nombre="Festival", anio=2027, activa=True)
        self.categoria = Categoria.objects.create(edicion=self.edicion, nombre="Acordeón", orden=1)
        self.votacion = Votacion.objects.create(
            categoria=self.categoria, titulo="Votación Acordeón",
            apertura=ahora - timedelta(hours=1), cierre=ahora + timedelta(days=1),
        )
        self.a = Opcion.objects.create(votacion=self.votacion, nombre="Candidato A")
        self.b = Opcion.objects.create(votacion=self.votacion, nombre="Candidato B")
        self.votante = crear_votante()


class VotoTests(BaseTest):
    def test_un_voto_por_votante_y_votacion(self):
        emitir_voto(self.votante, self.votacion, self.a)
        with self.assertRaises(VotoError):
            emitir_voto(self.votante, self.votacion, self.b)
        self.assertEqual(Voto.objects.count(), 1)

    def test_la_base_de_datos_rechaza_duplicados(self):
        Voto.objects.create(votante=self.votante, votacion=self.votacion, opcion=self.a, numero=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Voto.objects.create(votante=self.votante, votacion=self.votacion, opcion=self.b, numero=1)

    def test_limite_de_votos_configurable(self):
        self.votacion.votos_por_votante = 2
        self.votacion.save()
        emitir_voto(self.votante, self.votacion, self.a)
        emitir_voto(self.votante, self.votacion, self.b)
        with self.assertRaises(VotoError):
            emitir_voto(self.votante, self.votacion, self.a)

    def test_votacion_cerrada_proxima_o_pausada_rechaza(self):
        ahora = timezone.now()
        self.votacion.apertura, self.votacion.cierre = ahora - timedelta(days=2), ahora - timedelta(days=1)
        self.votacion.save()
        with self.assertRaises(VotoError):
            emitir_voto(self.votante, self.votacion, self.a)
        self.votacion.apertura, self.votacion.cierre = ahora + timedelta(days=1), ahora + timedelta(days=2)
        self.votacion.save()
        with self.assertRaises(VotoError):
            emitir_voto(self.votante, self.votacion, self.a)
        self.votacion.apertura, self.votacion.cierre = ahora - timedelta(hours=1), ahora + timedelta(days=1)
        self.votacion.pausada = True
        self.votacion.save()
        with self.assertRaises(VotoError):
            emitir_voto(self.votante, self.votacion, self.a)

    def test_mayoria_de_edad_es_configurable(self):
        menor = crear_votante("9876543210", "3109876543", mayor=False)
        with self.assertRaises(VotoError):
            emitir_voto(menor, self.votacion, self.a)
        self.votacion.exigir_mayoria_edad = False
        self.votacion.save()
        emitir_voto(menor, self.votacion, self.a)
        self.assertEqual(Voto.objects.count(), 1)

    def test_votante_sin_verificar_no_vota(self):
        sin_verificar = crear_votante("1112223334", "3201112233", verificado=False)
        with self.assertRaises(VotoError):
            emitir_voto(sin_verificar, self.votacion, self.a)

    def test_opcion_de_otra_votacion_se_rechaza(self):
        otra = Votacion.objects.create(
            categoria=self.categoria, titulo="Otra", apertura=timezone.now() - timedelta(hours=1),
            cierre=timezone.now() + timedelta(days=1),
        )
        ajena = Opcion.objects.create(votacion=otra, nombre="Ajena")
        with self.assertRaises(VotoError):
            emitir_voto(self.votante, self.votacion, ajena)


class ResultadosTests(BaseTest):
    def test_puntaje_final_del_prototipo(self):
        self.assertEqual(puntaje_final(41, 8.2, 50), 61.5)
        self.assertEqual(puntaje_final(33, 7.5, 50), 54.0)
        self.assertEqual(puntaje_final(26, 9.0, 50), 58.0)
        self.assertEqual(puntaje_final(40, 9.0, 0), 40.0)  # sin jurado solo cuenta el público

    def test_votos_en_cuarentena_no_cuentan(self):
        otro = crear_votante("5556667778", "3155556667")
        emitir_voto(self.votante, self.votacion, self.a)
        emitir_voto(otro, self.votacion, self.b)
        Voto.objects.filter(votante=otro).update(en_cuarentena=True)
        filas, total = calcular_resultados(self.votacion)
        self.assertEqual(total, 1)
        por_nombre = {f["opcion"].nombre: f for f in filas}
        self.assertEqual(por_nombre["Candidato A"]["pct"], 100.0)
        self.assertEqual(por_nombre["Candidato B"]["votos"], 0)

    def test_promedio_del_jurado(self):
        self.votacion.peso_jurado = 50
        self.votacion.save()
        jurado = User.objects.create_user("j1", password="x", is_staff=True)
        CalificacionJurado.objects.create(jurado=jurado, opcion=self.a, puntaje=Decimal("8.2"))
        filas, _ = calcular_resultados(self.votacion)
        fila_a = next(f for f in filas if f["opcion"] == self.a)
        self.assertEqual(fila_a["jurado"], 8.2)
        self.assertEqual(fila_a["final"], 41.0)  # 50% de 82 + 50% de 0 % de público


class AccesoTests(BaseTest):
    def test_panel_exige_permisos_de_administrador(self):
        url = reverse("festival:panel")
        self.assertEqual(self.client.get(url).status_code, 302)  # anónimo -> login de admin
        self.client.force_login(self.votante.usuario)
        self.assertEqual(self.client.get(url).status_code, 403)  # votante no es administrador
        self.client.logout()
        admin = User.objects.create_superuser("admin", "a@a.co", "admin12345")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_confirmar_voto_por_la_web_y_no_repetir(self):
        self.client.force_login(self.votante.usuario)
        url = reverse("festival:confirmar", args=[self.votacion.pk])
        self.assertEqual(self.client.get(url, {"opcion": self.a.pk}).status_code, 200)
        self.client.post(url, {"opcion": self.a.pk})
        self.client.post(url, {"opcion": self.b.pk})
        self.assertEqual(Voto.objects.count(), 1)
        self.assertEqual(Voto.objects.get().opcion, self.a)

    def test_votar_exige_sesion(self):
        url = reverse("festival:confirmar", args=[self.votacion.pk])
        respuesta = self.client.post(url, {"opcion": self.a.pk})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Voto.objects.count(), 0)


@override_settings(MOSTRAR_CODIGO_EN_PANTALLA=True)
class RegistroTests(TestCase):
    datos = {"cedula": "1.234.567.891", "celular": "300 123 4568", "mayor_edad": "on", "datos": "on"}

    def test_registro_verificacion_e_ingreso(self):
        r = self.client.post(reverse("festival:registro"), self.datos)
        self.assertRedirects(r, reverse("festival:verificar"))
        votante = Votante.objects.get(cedula="1234567891")
        self.assertFalse(votante.verificado)
        codigo = votante.codigos.latest("creado")
        codigo.codigo_hash = make_password("123456")
        codigo.save()
        r = self.client.post(reverse("festival:verificar"), {"codigo": "123456"})
        self.assertRedirects(r, reverse("festival:categorias"), fetch_redirect_response=False)
        votante.refresh_from_db()
        self.assertTrue(votante.verificado)
        self.assertEqual(int(self.client.session["_auth_user_id"]), votante.usuario.pk)

    def test_codigo_incorrecto_no_inicia_sesion(self):
        self.client.post(reverse("festival:registro"), self.datos)
        r = self.client.post(reverse("festival:verificar"), {"codigo": "000000"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_registro_exige_mayoria_de_edad_y_datos(self):
        sin_edad = {k: v for k, v in self.datos.items() if k != "mayor_edad"}
        self.assertEqual(self.client.post(reverse("festival:registro"), sin_edad).status_code, 200)
        sin_datos = {k: v for k, v in self.datos.items() if k != "datos"}
        self.assertEqual(self.client.post(reverse("festival:registro"), sin_datos).status_code, 200)
        self.assertEqual(Votante.objects.count(), 0)

    def test_cedula_duplicada_es_rechazada(self):
        crear_votante("1234567891", "3009999999")
        r = self.client.post(reverse("festival:registro"), self.datos)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Votante.objects.count(), 1)

    def test_celular_duplicado_es_rechazado(self):
        crear_votante("7778889990", "3001234568")
        r = self.client.post(reverse("festival:registro"), self.datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Votante.objects.filter(cedula="1234567891").exists())

    def test_ingreso_con_celular_que_no_corresponde(self):
        crear_votante("1234567891", "3001234568")
        r = self.client.post(reverse("festival:login"), {"cedula": "1234567891", "celular": "3110000000"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "No encontramos una cuenta")

    def test_limite_de_codigos_por_hora(self):
        votante = crear_votante()
        for _ in range(3):
            enviar_codigo(votante)
        with self.assertRaises(LimiteCodigosError):
            enviar_codigo(votante)

    def test_campo_trampa_bloquea_bots(self):
        r = self.client.post(reverse("festival:registro"), {**self.datos, "website": "http://spam"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Votante.objects.count(), 0)
