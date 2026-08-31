"""Sonda 2: (A) viaje interno promedio vs (B) tramo de acceso, con ruteo real.

(A) impedancia intrazonal: mediana de la distancia ruteada entre pares de puntos
    sorteados dentro de la comuna, ponderados por poblacion.
(B) tramo de acceso: del centroide a los puntos donde la red vial cruza el borde.
"""
from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import rasterio
import requests
from pyproj import Geod
from rasterio.mask import mask
from shapely.geometry import Point

GEOD = Geod(ellps="WGS84")
OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
TESTIGO = {2101: "Antofagasta", 8101: "Concepcion", 12401: "Natales", 13123: "Providencia"}
RNG = np.random.default_rng(20260831)
N = 120          # puntos por lado del muestreo Monte Carlo
N_BORDE = 200    # puntos muestreados sobre el borde comunal
SNAP_MAX = 2000  # m: si el punto queda a mas de esto de un camino, se descarta


def tabla(origenes, destinos):
    """OSRM /table: matriz de distancias ruteadas en metros."""
    coords = ";".join(f"{p.x:.6f},{p.y:.6f}" for p in origenes + destinos)
    ns, nd = len(origenes), len(destinos)
    r = requests.get(
        f"{OSRM}/table/v1/driving/{coords}",
        params={
            "sources": ";".join(map(str, range(ns))),
            "destinations": ";".join(map(str, range(ns, ns + nd))),
            "annotations": "distance",
        },
        timeout=600,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("code") != "Ok":
        raise RuntimeError(d)
    m = np.array(d["distances"], dtype="float64")
    snap_o = np.array([w["distance"] for w in d["sources"]])
    snap_d = np.array([w["distance"] for w in d["destinations"]])
    return m, snap_o, snap_d


def muestrear_poblacion(geom, ruta, n):
    """Sortea n puntos dentro de la comuna con probabilidad proporcional a poblacion."""
    with rasterio.open(ruta) as src:
        arr, transform = mask(src, [geom], crop=True, nodata=0, filled=True)
    banda = arr[0].astype("float64")
    banda[banda < 0] = 0.0
    filas, cols = np.nonzero(banda)
    if len(filas) == 0:
        return []
    p = banda[filas, cols]
    p = p / p.sum()
    idx = RNG.choice(len(filas), size=n, replace=True, p=p)
    xs, ys = rasterio.transform.xy(transform, filas[idx], cols[idx])
    px = abs(transform.a)
    return [
        Point(x + RNG.uniform(-px / 2, px / 2), y + RNG.uniform(-px / 2, px / 2))
        for x, y in zip(np.asarray(xs), np.asarray(ys))
    ]


def muestrear_borde(geom, n):
    b = geom.boundary
    largo = b.length
    return [b.interpolate(t, normalized=False) for t in np.linspace(0, largo, n, endpoint=False)]


def pct(v, q):
    return float(np.nanpercentile(v, q)) / 1000


def main():
    com = gpd.read_file("datos/crudo/comunas/comunas.shp").to_crs(4326)
    resumen = []

    for cod, nombre in TESTIGO.items():
        g = com.loc[com["cod_comuna"] == cod].geometry.union_all()
        print(f"\n{'='*78}\n{nombre} ({cod})")

        # --- centroide poblacional, el que usaremos como origen de (B)
        with rasterio.open("datos/crudo/chl_pop_2020.tif") as src:
            arr, tr = mask(src, [g], crop=True, nodata=0, filled=True)
        banda = arr[0].astype("float64")
        banda[banda < 0] = 0
        fs, cs = np.nonzero(banda)
        w = banda[fs, cs]
        xs, ys = rasterio.transform.xy(tr, fs, cs)
        centro = Point(np.average(np.asarray(xs), weights=w), np.average(np.asarray(ys), weights=w))

        # --- (A) Monte Carlo ponderado por poblacion
        o = muestrear_poblacion(g, "datos/crudo/chl_pop_2020.tif", N)
        d = muestrear_poblacion(g, "datos/crudo/chl_pop_2020.tif", N)
        m, so, sd = tabla(o, d)
        ok_o, ok_d = so <= SNAP_MAX, sd <= SNAP_MAX
        m_ok = m[np.ix_(ok_o, ok_d)]
        vals = m_ok[np.isfinite(m_ok) & (m_ok > 0)]
        desc = 1 - (m_ok.size / m.size) if m.size else 0
        sin_ruta = float(np.mean(~np.isfinite(m_ok))) if m_ok.size else float("nan")

        print(f"  (A) viaje interno, ruteado, ponderado por poblacion  [n={vals.size:,} pares]")
        print(f"      p25 {pct(vals,25):7.2f} km   mediana {pct(vals,50):7.2f} km   "
              f"p75 {pct(vals,75):7.2f} km   p95 {pct(vals,95):7.2f} km")
        print(f"      puntos descartados por snap >{SNAP_MAX} m: {desc:.1%}   "
              f"pares sin ruta: {sin_ruta:.1%}")

        # --- (B) tramo de acceso: centroide -> salidas viales del borde
        borde = muestrear_borde(g, N_BORDE)
        mb, sb_o, sb_d = tabla([centro], borde)
        util = np.isfinite(mb[0]) & (sb_d <= SNAP_MAX)
        vb = mb[0][util]
        print(f"  (B) tramo de acceso, centroide -> borde vial  "
              f"[{util.sum()} de {N_BORDE} puntos de borde sobre la red]")
        if vb.size:
            print(f"      minimo {vb.min()/1000:7.2f} km   mediana {np.median(vb)/1000:7.2f} km   "
                  f"maximo {vb.max()/1000:7.2f} km")
        else:
            print("      sin salidas viales alcanzables")

        area_m2, _ = GEOD.geometry_area_perimeter(g)
        radio = np.sqrt(abs(area_m2) / np.pi) / 1000
        print(f"  referencia: radio equivalente (2/3)*sqrt(A/pi) = {2/3*radio:7.2f} km")

        resumen.append(
            dict(
                comuna=nombre,
                area_km2=abs(area_m2) / 1e6,
                A_mediana_km=pct(vals, 50),
                B_min_km=vb.min() / 1000 if vb.size else np.nan,
                B_mediana_km=float(np.median(vb)) / 1000 if vb.size else np.nan,
                radio_23_km=2 / 3 * radio,
            )
        )

    import pandas as pd
    df = pd.DataFrame(resumen)
    df["B_med_sobre_A"] = df["B_mediana_km"] / df["A_mediana_km"]
    df["formula_sobre_A"] = df["radio_23_km"] / df["A_mediana_km"]
    print(f"\n{'='*78}\nRESUMEN")
    print(df.round(2).to_string(index=False))
    df.to_csv("datos/sonda_intracomuna.csv", index=False)


if __name__ == "__main__":
    main()
