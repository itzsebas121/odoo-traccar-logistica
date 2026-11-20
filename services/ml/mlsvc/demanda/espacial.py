"""Unidades espaciales para agregar la demanda a partir de la ubicacion del pedido (lat/lon aproximada).

Tipos (texto del parametro --unidades):
  - "h3:<res>"   celda hexagonal H3 (libreria h3). res 7 ~ 5 km2, 8 ~ 0,7 km2, 9 ~ 0,1 km2.
  - "kmeans[:k]" clusters de los puntos de venta; sin k se elige entre 4 y 15 por coeficiente de silueta.
  - "dbscan"     clusters por densidad (radio en km, metrica haversine); el ruido va al cluster mas cercano.
  - "zona"       la zona del DWH (centroide mas cercano de logistica.zona): referencia, no depende de lat/lon.

Un pedido sin coordenadas cae en la unidad "(sin ubicacion)" (salvo en "zona", que ya viene resuelta).
Las coordenadas llegan con la precision de Odoo (sin redondear): centros y cascos son los de los puntos reales.
Un Asignador entrenado se guarda con el modelo para ubicar coordenadas nuevas en /demanda/predict."""
import json
import math

import numpy as np

SIN_UBICACION = "(sin ubicacion)"
RADIO_TIERRA_KM = 6371.0


def _km_xy(lat, lon, lat0, lon0):
    """Proyeccion plana local (km) para clustering euclideo."""
    x = (np.asarray(lon) - lon0) * 111.32 * math.cos(math.radians(lat0))
    y = (np.asarray(lat) - lat0) * 110.57
    return np.column_stack([x, y])


def _casco(puntos):
    """Casco convexo (monotone chain) de [(lon, lat)] -> anillo cerrado. Con menos de 3 puntos, un cuadrado chico."""
    pts = sorted(set(puntos))
    if len(pts) < 3:
        lon, lat = (np.mean([p[0] for p in pts]), np.mean([p[1] for p in pts])) if pts else (0.0, 0.0)
        d = 0.002
        return [(lon - d, lat - d), (lon + d, lat - d), (lon + d, lat + d), (lon - d, lat + d), (lon - d, lat - d)]

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    inf, sup = [], []
    for p in pts:
        while len(inf) >= 2 and cruz(inf[-2], inf[-1], p) <= 0:
            inf.pop()
        inf.append(p)
    for p in reversed(pts):
        while len(sup) >= 2 and cruz(sup[-2], sup[-1], p) <= 0:
            sup.pop()
        sup.append(p)
    anillo = inf[:-1] + sup[:-1]
    return anillo + [anillo[0]]


def _geojson(anillo):
    return json.dumps({"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in anillo]]})


class Asignador:
    def __init__(self, tipo):
        self.tipo = tipo
        base, _, arg = tipo.partition(":")
        if base not in ("h3", "kmeans", "dbscan", "zona"):
            raise ValueError("Unidad espacial desconocida: %s" % tipo)
        self.base, self.arg = base, arg
        self.centros = {}          # unidad_id -> (lat, lon)
        self._modelo = None
        self._ref = None           # (lat0, lon0) de la proyeccion
        self._zonas = {}           # zona -> (lat, lon) media de sus ventas (para ubicar lat/lon nuevas en "zona")

    # ---------------------------------------------------------------- ajuste
    def ajustar(self, lat, lon, zona):
        lat, lon, zona = np.asarray(lat, float), np.asarray(lon, float), np.asarray(zona, object)
        ok = ~(np.isnan(lat) | np.isnan(lon))
        for z in set(zona[ok]):
            m = ok & (zona == z)
            self._zonas[z] = (float(lat[m].mean()), float(lon[m].mean()))
        if self.base in ("kmeans", "dbscan") and ok.sum() > 0:
            self._ref = (float(lat[ok].mean()), float(lon[ok].mean()))
            xy = _km_xy(lat[ok], lon[ok], *self._ref)
            unicos = np.unique(np.round(xy, 3), axis=0)
            if self.base == "kmeans":
                self._modelo = self._kmeans(unicos)
            else:
                self._modelo = self._dbscan(unicos)
        return self

    def _kmeans(self, xy):
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
        n = len(xy)
        if self.arg:
            ks = [min(int(self.arg), max(1, n))]
        else:
            ks = [k for k in range(4, 16) if k < n]
            ks = ks or [max(1, min(2, n))]
        mejor, mejor_s = None, -2.0
        for k in ks:
            km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(xy)
            s = silhouette_score(xy, km.labels_) if 1 < k < n else -1.0
            if s > mejor_s:
                mejor, mejor_s = km, s
        self.k_elegido, self.silueta = int(mejor.n_clusters), float(mejor_s)
        return mejor

    def _dbscan(self, xy):
        from sklearn.cluster import DBSCAN
        from sklearn.neighbors import NearestNeighbors
        eps_km = float(self.arg) if self.arg else 0.6
        etiquetas = DBSCAN(eps=eps_km, min_samples=3).fit_predict(xy)
        if (etiquetas >= 0).sum() == 0:              # todo ruido: un solo cluster
            etiquetas = np.zeros(len(xy), dtype=int)
        nucleo = xy[etiquetas >= 0]
        nn = NearestNeighbors(n_neighbors=1).fit(nucleo)
        etiquetas = etiquetas[etiquetas >= 0][nn.kneighbors(xy, return_distance=False)[:, 0]]
        return {"nn": NearestNeighbors(n_neighbors=1).fit(xy), "etiquetas": etiquetas}

    # ---------------------------------------------------------------- asignacion
    def asignar(self, lat, lon, zona=None):
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        n = len(lat)
        zona = np.asarray(zona if zona is not None else [None] * n, object)
        ok = ~(np.isnan(lat) | np.isnan(lon))
        out = np.full(n, SIN_UBICACION, dtype=object)
        if self.base == "zona":
            out = np.where(pd_notnull(zona), zona, out)
            faltan = ~pd_notnull(zona) & ok
            if faltan.any() and self._zonas:
                nombres = list(self._zonas)
                c = np.array([self._zonas[z] for z in nombres])
                for i in np.where(faltan)[0]:
                    d = (c[:, 0] - lat[i]) ** 2 + (c[:, 1] - lon[i]) ** 2
                    out[i] = nombres[int(d.argmin())]
            return out
        if not ok.any():
            return out
        if self.base == "h3":
            import h3
            res = int(self.arg or 8)
            out[ok] = [h3.latlng_to_cell(a, b, res) for a, b in zip(lat[ok], lon[ok])]
        elif self.base == "kmeans":
            xy = _km_xy(lat[ok], lon[ok], *self._ref)
            out[ok] = ["k%02d" % e for e in self._modelo.predict(xy)]
        else:
            xy = _km_xy(lat[ok], lon[ok], *self._ref)
            idx = self._modelo["nn"].kneighbors(xy, return_distance=False)[:, 0]
            out[ok] = ["d%02d" % e for e in self._modelo["etiquetas"][idx]]
        return out

    def asignar_con_limite(self, lat, lon, zona=None, lejos_km=None):
        """Como `asignar`, pero en el servidor: un punto a mas de `lejos_km` de lo que el modelo conocio (punto de
        entrenamiento mas cercano en dbscan, centro del cluster en kmeans) no se fuerza a una unidad lejana. Esos
        puntos forman unidades nuevas (DBSCAN haversine sobre ellos mismos) con id estable 's<lat>_<lon>' del centro.
        h3 y zona no lo necesitan: la celda o la zona ya es la del punto exacto."""
        out = self.asignar(lat, lon, zona)
        if self.base not in ("kmeans", "dbscan") or self._modelo is None or self._ref is None:
            return out
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        ok = ~(np.isnan(lat) | np.isnan(lon))
        if not ok.any():
            return out
        idx = np.where(ok)[0]
        xy = _km_xy(lat[ok], lon[ok], *self._ref)
        if self.base == "dbscan":
            lejos_km = lejos_km or max(3 * (float(self.arg) if self.arg else 0.6), 1.5)
            dist = self._modelo["nn"].kneighbors(xy, return_distance=True)[0][:, 0]
        else:
            lejos_km = lejos_km or 5.0
            dist = np.min(np.linalg.norm(xy[:, None, :] - self._modelo.cluster_centers_[None, :, :], axis=2), axis=1)
        lejos = idx[dist > lejos_km]
        if len(lejos) == 0:
            return out
        from sklearn.cluster import DBSCAN
        eps_km = float(self.arg) if (self.base == "dbscan" and self.arg) else 0.6
        rad = np.radians(np.column_stack([lat[lejos], lon[lejos]]))
        etiquetas = DBSCAN(eps=eps_km / RADIO_TIERRA_KM, min_samples=1, metric="haversine",
                           algorithm="ball_tree").fit_predict(rad)
        for e in np.unique(etiquetas):
            m = lejos[etiquetas == e]
            out[m] = "s%.3f_%.3f" % (float(lat[m].mean()), float(lon[m].mean()))
        return out

    # ---------------------------------------------------------------- geometria
    def unidades(self, lat, lon, unidad):
        """[{unidad_id, centro_lat, centro_lon, geojson, lineas}] de las unidades con ventas."""
        lat, lon, unidad = np.asarray(lat, float), np.asarray(lon, float), np.asarray(unidad, object)
        filas = []
        for u in sorted(set(unidad)):
            m = unidad == u
            ok = m & ~(np.isnan(lat) | np.isnan(lon))
            centro = (float(lat[ok].mean()), float(lon[ok].mean())) if ok.any() else (None, None)
            geo = None
            if self.base == "h3" and u != SIN_UBICACION:
                import h3
                anillo = [(b, a) for a, b in h3.cell_to_boundary(u)]
                geo = _geojson(anillo + [anillo[0]])
                centro = tuple(float(x) for x in h3.cell_to_latlng(u))
            elif ok.any():
                geo = _geojson(_casco(list(zip(lon[ok].round(4), lat[ok].round(4)))))
            filas.append({"unidad_id": str(u), "centro_lat": centro[0], "centro_lon": centro[1], "geojson": geo,
                          "lineas": int(m.sum())})
        return filas

    def describir(self):
        d = {"tipo": self.tipo}
        if self.base == "kmeans" and self._modelo is not None:
            d.update(k=self.k_elegido, silueta=round(self.silueta, 3))
        return d


def pd_notnull(a):
    return np.array([x is not None and x == x and x != "" for x in a], dtype=bool)


def disponible(tipo):
    """False si la unidad necesita una libreria que no esta instalada (h3)."""
    if tipo.startswith("h3"):
        try:
            import h3  # noqa: F401
        except ImportError:
            return False
    return True
