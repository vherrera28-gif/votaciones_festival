"""Configuración del proyecto de votaciones del Festival de la Leyenda Vallenata.

Los datos sensibles se leen de variables de entorno (ver README.md).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "cambiar-esta-clave-en-produccion")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "festival",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "festival.context_processors.global_festival",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de datos: MySQL por defecto. DB_ENGINE=sqlite solo para pruebas rápidas ---
if os.environ.get("DB_ENGINE", "mysql") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "votaciones_db",
        "USER": "root",
        "PASSWORD": "Valen2025*+",
        "HOST": "localhost",
        "PORT": "3306",
        "OPTIONS": {
            "charset": "utf8mb4",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "festival:login"
LOGIN_REDIRECT_URL = "festival:categorias"
LOGOUT_REDIRECT_URL = "festival:inicio"

# --- Parámetros del festival (propuestas del equipo, pendientes de confirmación) ---
# Mientras la Fundación no confirme las reglas por escrito, se muestran como "por confirmar".
REGLAS_CONFIRMADAS_POR_FUNDACION = False
# Código de un solo uso para registro e inicio de sesión
CODIGO_VIGENCIA_MIN = 10
CODIGOS_MAX_POR_HORA = 3
CODIGO_MAX_INTENTOS = 5
# Mientras no exista proveedor de SMS, el código se muestra en pantalla (solo demostración).
MOSTRAR_CODIGO_EN_PANTALLA = DEBUG
# El checkbox "soy mayor de 18" es obligatorio al registrarse
REGISTRO_EXIGE_MAYORIA_EDAD = True
# Cuarentena automática: más de N votos desde la misma IP en 10 minutos (0 = desactivada)
CUARENTENA_VOTOS_POR_IP = 20
