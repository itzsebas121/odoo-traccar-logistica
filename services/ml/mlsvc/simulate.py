"""Viajes simulados con patron conocido (procedencia = SIMULADO)."""
import argparse
import pathlib
import numpy as np
import pandas as pd
from . import ZONAS
from .features import TZ_OFFSET_H

VEHICULOS = ["VEH-01", "VEH-02", "VEH-03"]
# Destino preferido por franja horaria local; con ruido.
FRANJAS = [(6, 10, "centro"), (10, 13, "ficoa"), (13, 16, "huachi"), (16, 19, "izamba")]
PREF_VEH = {"VEH-01": "atocha", "VEH-02": "ingahurco", "VEH-03": "otra"}


def generar(dias=120, seed=42, inicio="2026-01-05", viajes_por_dia=6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    filas = []
    for d in pd.date_range(inicio, periods=dias, freq="D", tz="UTC"):
        for veh in VEHICULOS:
            origen = "centro"
            for _ in range(viajes_por_dia):
                hora = int(rng.integers(6, 19))
                base = next(z for a, b, z in FRANJAS if a <= hora < b)
                if rng.random() < 0.8:
                    dest = base
                elif rng.random() < 0.5:
                    dest = PREF_VEH[veh]
                else:
                    dest = str(rng.choice(ZONAS))
                local = d + pd.Timedelta(hours=hora, minutes=int(rng.integers(0, 60)))
                filas.append({
                    "vehiculo_codigo": veh,
                    "fecha_hora": (local - pd.Timedelta(hours=TZ_OFFSET_H)).isoformat(),
                    "zona_origen": origen,
                    "zona_destino": dest,
                    "procedencia": "SIMULADO",
                })
                origen = dest
    return pd.DataFrame(filas)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/viajes_simulados.csv")
    p.add_argument("--dias", type=int, default=120)
    a = p.parse_args(argv)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    generar(a.dias).to_csv(out, index=False)
    print(out)


if __name__ == "__main__":
    main()
