"""Etapa 04b: distancias desde cada comuna a cada punto logistico.

Mismo metodo y mismas columnas que `distancias_comuna_comuna`, con `id_punto` en
lugar de `cod_destino`. Se separa de la etapa 04 porque depende de la capa de
puntos (etapa 03), que puede regenerarse sin rehacer la matriz comunal.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import requests
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
OSRM_CL = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
SALIDA = "datos/salida"

# Radio maximo de enganche a la red vial, en metros. Sin tope OSRM engancha
# arbitrariamente lejos, prefiriendo la componente conexa grande antes que devolver
# "sin ruta": Juan Fernandez enganchaba a un camino del Maule, a 670 km, y la isla
# aparecia conectada por tierra. Ver el comentario extendido en 04_distancias.py.
RADIO_M = 30000


def tabla(base, origenes, destinos, bloque=120):
    """Distancias y tiempos origen->destino, pedidos por bloques de origenes.

    El tope de enganche se aplica sobre la respuesta, no con `radiuses`: una sola
    coordenada sin camino cerca (Isla de Pascua, islas Desventuradas) haria que
    OSRM responda 400 NoSegment y bote la consulta completa.
    """
    coords = ";".join(f"{x:.6f},{y:.6f}" for x, y in origenes + destinos)
    no, nd = len(origenes), len(destinos)
    dist = np.full((no, nd), np.nan)
    dur = np.full((no, nd), np.nan)
    snap_o = np.full(no, np.nan)
    snap_d = np.full(nd, np.nan)
    destinos_idx = ";".join(map(str, range(no, no + nd)))
    for i0 in range(0, no, bloque):
        i1 = min(i0 + bloque, no)
        r = requests.get(
            f"{base}/table/v1/driving/{coords}",
            params={
                "sources": ";".join(map(str, range(i0, i1))),
                "destinations": destinos_idx,
                "annotations": "distance,duration",
            },
            timeout=1800,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("code") != "Ok":
            raise RuntimeError(j)
        dist[i0:i1] = [[np.nan if v is None else v for v in f] for f in j["distances"]]
        dur[i0:i1] = [[np.nan if v is None else v for v in f] for f in j["durations"]]
        snap_o[i0:i1] = [w["distance"] for w in j["sources"]]
        if np.isnan(snap_d).all():
            snap_d = np.array([w["distance"] for w in j["destinations"]])
        print(f"    origenes {i0}-{i1} de {no}")

    lo, ld = snap_o > RADIO_M, snap_d > RADIO_M
    if lo.any() or ld.any():
        print(f"    enganche fuera de tope: {lo.sum()} comunas, {ld.sum()} puntos; anulados")
        dist[lo, :] = np.nan
        dist[:, ld] = np.nan
        dur[lo, :] = np.nan
        dur[:, ld] = np.nan
    return dist, dur


def main():
    com = pd.read_parquet(f"{SALIDA}/comunas.parquet")
    com = com[com["es_comuna"]].sort_values("cod_comuna").reset_index(drop=True)
    pts = pd.read_parquet(f"{SALIDA}/puntos_logisticos.parquet").sort_values("id_punto")

    o = list(zip(com["canonico_lon"], com["canonico_lat"]))
    d = list(zip(pts["lon"], pts["lat"]))
    print(f"comunas: {len(o)}   puntos: {len(d)}   pares: {len(o)*len(d):,}")

    print("\n== grafo Chile completo ==")
    dist, dur = tabla(OSRM, o, d)
    print("\n== grafo recortado a Chile ==")
    dist_cl, _ = tabla(OSRM_CL, o, d)

    lon_o = np.array([p[0] for p in o])
    lat_o = np.array([p[1] for p in o])
    lon_d = np.array([p[0] for p in d])
    lat_d = np.array([p[1] for p in d])
    LO, LD = np.meshgrid(lon_o, lon_d, indexing="ij")
    AO, AD = np.meshgrid(lat_o, lat_d, indexing="ij")
    _, _, geo = GEOD.inv(LO, AO, LD, AD)

    O, P = np.meshgrid(com["cod_comuna"].to_numpy(), pts["id_punto"].to_numpy(), indexing="ij")
    km = dist / 1000
    km_geo = geo / 1000
    with np.errstate(divide="ignore", invalid="ignore"):
        rodeo = np.where(km_geo > 0, km / km_geo, np.nan)

    df = pd.DataFrame(
        {
            "cod_origen": O.ravel(),
            "id_punto": P.ravel(),
            "km_ruta": km.ravel().round(3),
            "minutos": (dur / 60).ravel().round(2),
            "km_geodesica": km_geo.ravel().round(3),
            "factor_rodeo": rodeo.ravel().round(4),
            "ruta_existe": np.isfinite(dist).ravel(),
            "solo_via_argentina": (np.isfinite(dist) & ~np.isfinite(dist_cl)).ravel(),
        }
    )
    df.to_parquet(f"{SALIDA}/distancias_comuna_punto.parquet", index=False)

    print(f"\nfilas: {len(df):,}")
    print(f"sin ruta:            {(~df['ruta_existe']).mean():.1%}")
    print(f"solo_via_argentina:  {df['solo_via_argentina'].mean():.1%}")
    nac = df[df["ruta_existe"] & ~df["solo_via_argentina"] & (df["km_geodesica"] > 1)]
    print(f"\nfactor de rodeo mediano: {nac['factor_rodeo'].median():.3f}")
    print(f"km_ruta mediano:         {nac['km_ruta'].median():.1f}")


if __name__ == "__main__":
    main()
