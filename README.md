# Votaciones · Festival de la Leyenda Vallenata

Aplicación web con **Python, Django (patrón MVT) y MySQL**. Paleta: rojo, vinotinto, negro y blanco.

## Estructura (MVT)

| Capa | Archivos |
|---|---|
| Modelo | `festival/models.py` (Edición → Categoría → Votación → Opción; Votante, Voto, CalificacionJurado) |
| Vista | `festival/views.py`, `festival/services.py` (reglas de negocio) |
| Plantilla | `festival/templates/festival/` y `festival/static/festival/css/estilo.css` |
| Rutas | `config/urls.py`, `festival/urls.py` |

## Pasos

1. **Entorno**
   ```bash
   python -m venv venv
   # Windows: venv\Scripts\activate    Linux/Mac: source venv/bin/activate
   pip install -r requirements.txt
   ```
   Si `mysqlclient` falla en Windows: `pip install pymysql` y en `config/__init__.py` agrega
   `import pymysql; pymysql.install_as_MySQLdb()`.

2. **Base de datos MySQL**
   ```sql
   CREATE DATABASE votaciones_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
   Define las credenciales por variables de entorno (o edita `config/settings.py`):
   `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`.
   Para probar sin MySQL: `DB_ENGINE=sqlite`.

3. **Migraciones** (el proyecto no trae migraciones generadas; se crean aquí)
   ```bash
   python manage.py makemigrations festival
   python manage.py migrate
   ```

4. **Django Admin y datos de prueba**
   ```bash
   python manage.py cargar_datos_prueba
   python manage.py runserver
   ```
   - Admin: `admin / admin12345` · Jurado: `jurado1 / jurado12345` (cámbialas fuera de pruebas)
   - Votante: cédula `1234567890`, celular `3001234567` (el código aparece en pantalla en modo demostración)
   - Django Admin: `http://127.0.0.1:8000/admin/` · Panel propio: `http://127.0.0.1:8000/panel/`

5. **Pruebas**
   ```bash
   python manage.py test festival
   ```

## Regla de identificación (propuesta, por confirmar con la Fundación)

La **cédula identifica** a la persona; el **celular** solo verifica con un código de un solo uso.
Cédula única, celular único y restricción única `(votante, votación, número de voto)` en la base de datos.
Con el límite por defecto (1 voto) equivale a un voto por votante y votación.

## Parámetros sin tocar código

- Por votación (Django Admin o `/panel/votaciones/`): apertura, cierre, `peso_jurado`, `exigir_mayoria_edad`, `votos_por_votante`, `pausada`.
- Globales (`config/settings.py`): `REGLAS_CONFIRMADAS_POR_FUNDACION` (mientras sea `False`, la interfaz marca las reglas como «por confirmar»), `CODIGOS_MAX_POR_HORA`, `CODIGO_VIGENCIA_MIN`, `CUARENTENA_VOTOS_POR_IP`, `MOSTRAR_CODIGO_EN_PANTALLA`.
- Nueva edición: crearla en Django Admin y marcarla como activa; sus categorías y votaciones se cargan igual, sin cambiar código.

## Pendientes antes de producción

- Conectar un proveedor de SMS en `services.enviar_codigo` y poner `MOSTRAR_CODIGO_EN_PANTALLA = False`.
- `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` propia y HTTPS. Detrás de un proxy, `REMOTE_ADDR` no es la IP real del votante.
- La cédula se declara, no se valida contra una fuente oficial.
