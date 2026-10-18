from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    render_template_string,
    session,
    redirect,
    url_for
)

import os
import secrets
import bcrypt
import pymysql

from pathlib import Path
from pymysql.cursors import DictCursor


# ======================================
# CONFIGURACION DE FLASK
# ======================================

app = Flask(__name__)

CARPETA_PROYECTO = Path(__file__).resolve().parent
ARCHIVO_SECRETO = CARPETA_PROYECTO / ".flask_secret"

# Mantener la misma clave entre reinicios
if not ARCHIVO_SECRETO.exists():
    try:
        with ARCHIVO_SECRETO.open("x") as archivo:
            archivo.write(secrets.token_hex(32))
    except FileExistsError:
        pass

os.chmod(ARCHIVO_SECRETO, 0o600)

app.secret_key = ARCHIVO_SECRETO.read_text().strip()

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ======================================
# CONEXION A MARIADB
# ======================================

def conectar_db():

    password_db = os.environ.get("PORTAL_DB_PASSWORD")

    if not password_db:
        raise RuntimeError(
            "No se configuro PORTAL_DB_PASSWORD"
        )

    conexion = pymysql.connect(
        unix_socket="/var/lib/mysql/mysql.sock",
        user="portal_app",
        password=password_db,
        database="portal_estudiantil",
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False
    )

    return conexion


# ======================================
# PAGINA PRINCIPAL
# ======================================

@app.route("/")
def inicio():
    return render_template("index.html")


# ======================================
# REGISTRO DE USUARIOS
# ======================================

@app.route("/registro", methods=["POST"])
def registro():

    datos = request.get_json(silent=True)

    if not isinstance(datos, dict):
        return jsonify({
            "mensaje": "Datos invalidos"
        }), 400

    usuario = datos.get("usuario")
    password = datos.get("password")

    if not isinstance(usuario, str) or not isinstance(password, str):
        return jsonify({
            "mensaje": "Ingresa usuario y contrasena"
        }), 400

    usuario = usuario.strip()
    password_bytes = password.encode("utf-8")

    if not 3 <= len(usuario) <= 40:
        return jsonify({
            "mensaje": "El usuario debe tener entre 3 y 40 caracteres"
        }), 400

    if len(password) < 8 or len(password_bytes) > 72:
        return jsonify({
            "mensaje": "La contrasena debe tener al menos 8 caracteres y no superar 72 bytes"
        }), 400

    # CIFRAR LA CONTRASENA CON BCRYPT
    hash_password = bcrypt.hashpw(
        password_bytes,
        bcrypt.gensalt(rounds=12)
    ).decode("utf-8")

    conexion = None

    try:
        conexion = conectar_db()

        with conexion.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO usuarios (usuario, password_hash)
                VALUES (%s, %s)
                """,
                (usuario, hash_password)
            )

        conexion.commit()

        return jsonify({
            "mensaje": "Usuario registrado exitosamente"
        }), 201

    except pymysql.err.IntegrityError as error:

        if conexion:
            conexion.rollback()

        if error.args[0] == 1062:
            return jsonify({
                "mensaje": "Este usuario ya esta registrado"
            }), 409

        app.logger.exception("Error de integridad")

        return jsonify({
            "mensaje": "No se pudo registrar el usuario"
        }), 500

    except (pymysql.MySQLError, RuntimeError):

        if conexion:
            conexion.rollback()

        app.logger.exception("Error de MariaDB")

        return jsonify({
            "mensaje": "Error de conexion con la base de datos"
        }), 503

    finally:
        if conexion:
            conexion.close()


# ======================================
# PAGINA DE INICIO DE SESION
# ======================================

@app.route("/iniciar-sesion")
def pagina_login():
    return render_template("login.html")


# ======================================
# VALIDAR USUARIO Y CONTRASENA
# ======================================

@app.route("/login", methods=["POST"])
def login():

    session.clear()

    datos = request.get_json(silent=True)

    if not isinstance(datos, dict):
        return jsonify({
            "mensaje": "Datos invalidos"
        }), 400

    usuario = datos.get("usuario")
    password = datos.get("password")

    if not isinstance(usuario, str) or not isinstance(password, str):
        return jsonify({
            "mensaje": "Ingresa tus credenciales"
        }), 400

    usuario = usuario.strip()
    password_bytes = password.encode("utf-8")

    if len(password_bytes) > 72:
        return jsonify({
            "mensaje": "Usuario o contrasena incorrectos"
        }), 401

    conexion = None

    try:
        conexion = conectar_db()

        with conexion.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, usuario, password_hash
                FROM usuarios
                WHERE usuario = %s
                """,
                (usuario,)
            )

            resultado = cursor.fetchone()

    except (pymysql.MySQLError, RuntimeError):

        app.logger.exception("Error al consultar MariaDB")

        return jsonify({
            "mensaje": "Error de conexion con la base de datos"
        }), 503

    finally:
        if conexion:
            conexion.close()

    if resultado is None:
        return jsonify({
            "mensaje": "Usuario o contrasena incorrectos"
        }), 401

    # VERIFICAR CONTRASENA CON BCRYPT
    hash_guardado = resultado["password_hash"]

    try:
        contrasena_valida = bcrypt.checkpw(
            password_bytes,
            hash_guardado.encode("utf-8")
        )
    except ValueError:
        app.logger.error("Hash bcrypt invalido")
        return jsonify({
            "mensaje": "Usuario o contrasena incorrectos"
        }), 401

    if not contrasena_valida:
        return jsonify({
            "mensaje": "Usuario o contrasena incorrectos"
        }), 401

    # CREAR SESION
    session["usuario_id"] = resultado["id"]
    session["usuario"] = resultado["usuario"]

    return jsonify({
        "mensaje": "Inicio de sesion exitoso",
        "usuario": resultado["usuario"]
    }), 200


# ======================================
# PANEL ESTUDIANTIL PRIVADO
# ======================================

@app.route("/panel")
def panel():

    if "usuario_id" not in session:
        return redirect(url_for("pagina_login"))

    return render_template_string("""
    <!DOCTYPE html>
    <html lang="es">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Panel Estudiantil - ESPE</title>

        <style>
            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: #edf3fa;
            }

            header {
                background: #133c70;
                color: white;
                text-align: center;
                padding: 28px;
            }

            header h1 {
                margin: 0 0 10px;
            }

            .contenedor {
                max-width: 650px;
                margin: 70px auto;
                padding: 35px;
                background: white;
                border-radius: 14px;
                box-shadow: 0 5px 20px #00000018;
                text-align: center;
            }

            h2 {
                color: #133c70;
            }

            p {
                color: #475569;
                line-height: 1.6;
            }

            button {
                padding: 12px 25px;
                margin-top: 20px;
                border: none;
                border-radius: 7px;
                background: #133c70;
                color: white;
                font-size: 15px;
                cursor: pointer;
            }

            button:hover {
                background: #20599c;
            }
        </style>
    </head>

    <body>

        <header>
            <h1>Portal Estudiantil</h1>
            <p style="color:white;">
                Universidad de las Fuerzas Armadas ESPE
            </p>
        </header>

        <div class="contenedor">

            <h2>Bienvenido, {{ usuario }}</h2>

            <p>Has iniciado sesion correctamente.</p>

            <p>
                Tu cuenta se encuentra registrada en MariaDB
                y tu contrasena esta protegida mediante bcrypt.
            </p>

            <form action="/salir" method="POST">
                <button type="submit">
                    Cerrar sesion
                </button>
            </form>

        </div>

    </body>
    </html>
    """, usuario=session["usuario"])


# ======================================
# CERRAR SESION
# ======================================

@app.route("/salir", methods=["POST"])
def salir():

    session.clear()

    return redirect(url_for("pagina_login"))


# ======================================
# EJECUTAR FLASK
# ======================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
