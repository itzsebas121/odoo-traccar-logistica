"""Fuentes de datos del pronostico de demanda. El ML solo lee el DWH (nunca Odoo, Traccar ni staging).

Conexion por partes (host, puerto, base, usuario, clave) con psycopg2.connect(**kwargs): la clave puede tener
cualquier caracter (pendiente M4 de docs/guia_analisis_ml.md, antes iba dentro de una URL).
  - lectura:   DWH_USER (dwh_ro) + DWH_DB_PASSWORD
  - escritura: DWH_ML_USER (dwh_ml) + DWH_ML_PASSWORD, solo tablas ml_* (comparativa, unidades y pronosticos)
"""
import os
from contextlib import closing

import numpy as np
import pandas as pd

COLUMNAS = ["fecha_local", "producto_sk", "producto_id_odoo", "producto", "categoria", "lat_aprox", "lon_aprox", "zona",
            "cantidad", "procedencia"]
SQL_VENTAS = ("SELECT fecha_local, producto_sk, producto_id_odoo, producto, categoria, lat_aprox, lon_aprox, zona, "
              "cantidad, procedencia FROM v_ml_ventas_geo WHERE fecha_local IS NOT NULL AND producto_sk IS NOT NULL")


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def _params(usuario_var, usuario_def, clave_var):
    clave = os.environ.get(clave_var)
    if not clave:
        raise ConfigError("Falta la variable de entorno %s (vea .env.example)." % clave_var)
    e = os.environ.get
    return dict(host=e("DWH_HOST", "db"), port=e("DWH_PORT", "5432"), dbname=e("DWH_NAME", "logistica_dwh"),
                user=e(usuario_var) or usuario_def, password=clave)


def params_lectura():
    return _params("DWH_USER", "dwh_ro", "DWH_DB_PASSWORD")


def params_escritura():
    return _params("DWH_ML_USER", "dwh_ml", "DWH_ML_PASSWORD")


def puede_escribir():
    return bool(os.environ.get("DWH_ML_PASSWORD"))


def conectar(escritura=False):
    import psycopg2
    return psycopg2.connect(**(params_escritura() if escritura else params_lectura()))


def normalizar(df):
    if "producto_id_odoo" not in df.columns and "producto_sk" in df.columns:
        df = df.assign(producto_id_odoo=df["producto_sk"])
    falta = set(COLUMNAS) - set(df.columns)
    if falta:
        raise ValueError("Faltan columnas: %s" % sorted(falta))
    df = df[COLUMNAS].copy()
    df["fecha_local"] = pd.to_datetime(df["fecha_local"]).dt.normalize()
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0.0).astype(float)
    for c in ("lat_aprox", "lon_aprox"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["producto_sk"] = df["producto_sk"].astype(int)
    df["producto_id_odoo"] = pd.to_numeric(df["producto_id_odoo"], errors="coerce").fillna(-1).astype(int)
    df["zona"] = df["zona"].fillna("(sin zona)").astype(str)
    df["categoria"] = df["categoria"].fillna("(sin categoria)").astype(str)
    return df.sort_values("fecha_local", kind="stable").reset_index(drop=True)


def leer_dwh():
    with closing(conectar()) as con:
        with con.cursor() as cur:
            cur.execute(SQL_VENTAS)
            filas = cur.fetchall()
            cols = [d[0] for d in cur.description]
    df = pd.DataFrame(filas, columns=cols)
    for c in ("cantidad", "lat_aprox", "lon_aprox"):
        df[c] = df[c].astype(float)
    return df


def sintetico(dias=150, semilla=7, productos=6, inicio="2026-03-01"):
    """Ventas sinteticas con patron conocido (semana, quincena, preferencia por ubicacion) para pruebas.
    Cuatro focos de clientes alrededor de un centro; procedencia SIMULADO."""
    rng = np.random.default_rng(semilla)
    focos = [(-1.240, -78.620, "centro"), (-1.226, -78.633, "ficoa"), (-1.264, -78.630, "huachi"),
             (-1.201, -78.587, "izamba")]
    afin = rng.uniform(0.3, 2.0, size=(productos, len(focos)))
    semana = np.array([0.8, 0.85, 0.9, 1.0, 1.25, 1.4, 1.1])
    filas = []
    for d in pd.date_range(inicio, periods=dias, freq="D"):
        f_dia = semana[d.dayofweek] * (1.3 if d.day in (1, 15, 16, 30, 31) else 1.0)
        for p in range(productos):
            for k, (la, lo, zona) in enumerate(focos):
                n = rng.poisson(0.9 * afin[p, k] * f_dia)
                for _ in range(n):
                    filas.append({
                        "fecha_local": d, "producto_sk": p + 1, "producto": "Producto %d" % (p + 1),
                        "categoria": "Categoria %d" % (p % 3), "lat_aprox": round(la + rng.normal(0, 0.003), 3),
                        "lon_aprox": round(lo + rng.normal(0, 0.003), 3), "zona": zona,
                        "cantidad": float(1 + rng.poisson(0.5)), "procedencia": "SIMULADO"})
    return pd.DataFrame(filas)


def cargar(fuente):
    """fuente: 'dwh', 'sintetico' o 'csv:<ruta>'. Devuelve las ventas normalizadas (una fila por linea)."""
    if fuente == "dwh":
        return normalizar(leer_dwh())
    if fuente == "sintetico":
        return normalizar(sintetico())
    if fuente.startswith("csv:"):
        return normalizar(pd.read_csv(fuente[4:]))
    raise SystemExit("Fuente desconocida: %s (use dwh, sintetico o csv:<ruta>)" % fuente)
