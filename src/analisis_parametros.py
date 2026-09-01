"""Justifica los dos parametros del muestreo de (A): `N_MUESTRA` y `SNAP_MAX`.

No forma parte de `make all`: se corre cuando hay que revisar la eleccion, y su
salida es lo que la respalda en la documentacion.

**Convergencia.** Para cada comuna testigo se sortea una vez la muestra maxima y se
rutea la matriz completa; los tamanos menores se evaluan sobre la submatriz superior
izquierda. Tomar los primeros k de una muestra aleatoria es una muestra aleatoria de
tamano k, asi que el resultado es exacto y cuesta una sola consulta por replica.

**Umbral de enganche.** `SNAP_MAX` es un filtro posterior: se aplica sobre la
distancia de enganche que la propia respuesta devuelve. Basta una consulta por comuna
y despues se evalua a distintos umbrales.
"""
from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.mask import mask
from shapely.geometry import Point

OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
SALIDA = "datos/salida"
RASTER = "datos/crudo/chl_pop_2020.tif"

N_MAX = 250
REPLICAS = 6
TAMANOS = [25, 50, 100, 150, 200, 250]
UMBRALES = [500, 1000, 2000, 5000, 30000]

# Una comuna por regimen: urbana densa, media, grande con poblacion concentrada,
# grande con poblacion dispersa, y las dos de mayor descarte del pais.
TESTIGO = {
    13123: "Providencia",
    8101: "Concepcion",
    2101: "Antofagasta",
    11202: "Cisnes",
    3102: "Taltal",
    11303: "Tortel",
}


def tabla(origenes, destinos):
    coords = ";".join(f"{p.x:.6f},{p.y:.6f}" for p in origenes + destinos)
    ns, nd = len(origenes), len(destinos)
    r = requests.get(
        f"{OSRM}/table/v1/driving/{coords}",
        params={
            "sources": ";".join(map(str, range(ns))),
            "destinations": ";".join(map(str, range(ns, ns + nd))),
            "annotations": "distance",
        },
        timeout=1800,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "Ok":
        raise RuntimeError(j)
    m = np.array([[np.nan if v is None else v for v in f] for f in j["distances"]])
    return (m,
            np.array([w["distance"] for w in j["sources"]]),
            np.array([w["distance"] for w in j["destinations"]]))


def sortear(geom, src, n, rng):
    arr, tr = mask(src, [geom], crop=True, nodata=0, filled=True)
    b = arr[0].astype("float64")
    b[b < 0] = 0.0
    fs, cs = np.nonzero(b)
    if len(fs) == 0:
        return []
    p = b[fs, cs] / b[fs, cs].sum()
    idx = rng.choice(len(fs), size=n, replace=True, p=p)
    xs, ys = rasterio.transform.xy(tr, fs[idx], cs[idx])
    px = abs(tr.a)
    return [Point(x + rng.uniform(-px / 2, px / 2), y + rng.uniform(-px / 2, px / 2))
            for x, y in zip(np.asarray(xs), np.asarray(ys))]


def percentil(m, so, sd, k, umbral):
    """p50 y p95 de la submatriz k x k, filtrando por distancia de enganche."""
    sub = m[:k, :k][np.ix_(so[:k] <= umbral, sd[:k] <= umbral)]
    v = sub[np.isfinite(sub) & (sub > 0)]
    if v.size < 10:
        return np.nan, np.nan, v.size
    return float(np.percentile(v, 50)) / 1000, float(np.percentile(v, 95)) / 1000, v.size


def main():
    poly = gpd.read_file("datos/crudo/comunas/comunas.shp").to_crs(4326)
    poly["geometry"] = poly.geometry.make_valid()
    poly = poly.set_index("cod_comuna")

    conv, sens = [], []
    with rasterio.open(RASTER) as src:
        for cod, nombre in TESTIGO.items():
            g = poly.loc[cod].geometry
            print(f"  {nombre}...")
            for rep in range(REPLICAS):
                rng = np.random.default_rng(20260901 + rep)
                o = sortear(g, src, N_MAX, rng)
                d = sortear(g, src, N_MAX, rng)
                m, so, sd = tabla(o, d)
                for k in TAMANOS:
                    p50, p95, n = percentil(m, so, sd, k, 2000)
                    conv.append(dict(comuna=nombre, replica=rep, k=k,
                                     p50=p50, p95=p95, pares=n))
                if rep == 0:
                    for u in UMBRALES:
                        p50, p95, n = percentil(m, so, sd, 150, u)
                        desc = 1 - (so[:150] <= u).mean() * (sd[:150] <= u).mean()
                        sens.append(dict(comuna=nombre, umbral=u, p50=p50, p95=p95,
                                         pares=n, descartado=desc))

    cv = pd.DataFrame(conv)
    se = pd.DataFrame(sens)
    cv.to_csv(f"{SALIDA}/_analisis_convergencia.csv", index=False)
    se.to_csv(f"{SALIDA}/_analisis_umbral.csv", index=False)

    print("\n" + "=" * 78)
    print("B1  CONVERGENCIA: dispersion de p50 entre replicas, en % de la mediana")
    print("=" * 78)
    r = (cv.groupby(["comuna", "k"])["p50"]
           .agg(media="mean", desv="std")
           .assign(cv_pct=lambda d: 100 * d.desv / d.media)
           .reset_index()
           .pivot(index="comuna", columns="k", values="cv_pct"))
    print(r.round(2).to_string())
    print("\n  p50 medio por tamano (km):")
    print(cv.groupby(["comuna", "k"])["p50"].mean().unstack().round(2).to_string())
    print("\n  lo mismo para p95 (km):")
    print(cv.groupby(["comuna", "k"])["p95"].mean().unstack().round(2).to_string())

    print("\n" + "=" * 78)
    print("B2  UMBRAL DE ENGANCHE: p50 (km) segun SNAP_MAX")
    print("=" * 78)
    print(se.pivot(index="comuna", columns="umbral", values="p50").round(2).to_string())
    print("\n  fraccion de la muestra descartada:")
    print(se.pivot(index="comuna", columns="umbral", values="descartado").round(3).to_string())


if __name__ == "__main__":
    main()
