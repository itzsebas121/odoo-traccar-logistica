"""Consultas OLAP del BI. Lee SOLO el esquema dwh de PostgreSQL (rol de solo lectura); no usa Odoo."""
import os
import re

import pandas as pd
import psycopg2

SQL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql", "olap_queries.sql")
PROCEDENCIAS = ("REAL", "SIMULADO")


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def dsn():
    """Cadena de conexion al DWH con el rol de solo lectura. La contrasena es obligatoria y no tiene valor por defecto."""
    password = os.environ.get("DWH_DB_PASSWORD")
    if not password:
        raise ConfigError(
            "Falta la variable de entorno obligatoria DWH_DB_PASSWORD (contrasena del rol dwh_ro). "
            "Definala en .env (vea .env.example) y vuelva a levantar el servicio bi.")
    e = os.environ.get
    return "host=%s port=%s dbname=%s user=%s password=%s" % (
        e("DWH_HOST", "db"), e("DWH_PORT", "5432"), e("DWH_NAME", "logistica_dwh"), e("DWH_USER", "dwh_ro"), password)


def conectar():
    return psycopg2.connect(dsn())


def cargar_consultas(ruta=SQL_FILE):
    """Devuelve {nombre: (sql, usa_rollup)} a partir de los bloques '-- name: x' del archivo SQL."""
    with open(ruta, encoding="utf-8") as f:
        texto = f.read()
    consultas = {}
    for bloque in re.split(r"^-- name:\s*", texto, flags=re.M)[1:]:
        nombre, _, cuerpo = bloque.partition("\n")
        consultas[nombre.strip()] = (cuerpo.strip(), "GROUP BY ROLLUP" in cuerpo)
    return consultas


QUERIES = cargar_consultas()


def hay_simulados(procedencia):
    """True si el filtro de procedencia incluye datos simulados (o no filtra)."""
    return procedencia is None or "SIMULADO" in procedencia


def consulta(conn, nombre, desde=None, hasta=None, procedencia=None):
    """Ejecuta una consulta nombrada y devuelve un DataFrame. procedencia: lista de 'REAL'/'SIMULADO' o None (todas)."""
    sql, _ = QUERIES[nombre]
    proc = list(procedencia) if procedencia is not None else None
    with conn.cursor() as cur:
        cur.execute(sql, {"desde": desde, "hasta": hasta, "proc": proc})
        cols = [d[0] for d in cur.description]
        filas = cur.fetchall()
    conn.rollback()
    return pd.DataFrame(filas, columns=cols)


def indicadores(conn, desde=None, hasta=None, procedencia=None):
    return {n: consulta(conn, n, desde, hasta, procedencia) for n in QUERIES}
