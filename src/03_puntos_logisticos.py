"""Etapa 03: capa de puntos logisticos (puertos, aeropuertos, pasos fronterizos).

Se construye desde OpenStreetMap, no desde ningun catalogo privado. El insumo es
`datos/crudo/puntos_osm.geojson`, que produce `src/osm_puntos.sh` con
`osmium tags-filter` sobre el extracto de Chile.

Cada punto se asigna a una comuna por join espacial, no por nombre.
"""
from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
# Se usa el grafo NACIONAL: este es un dataset chileno, y una comuna fronteriza
# no debe enganchar ni rutear por un camino argentino.
OSRM = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
SALIDA = "datos/salida"
CRUDO = "datos/crudo/puntos_osm.geojson"


def subtipo(row):
    """Distingue lo que sirve para carga de lo que no.

    Sin esto el layer mete en la misma bolsa el Puerto de Valparaiso y el Club de
    Yates de Antofagasta. Se deriva de etiquetas de OSM, no de criterio propio.
    """
    t = row["tipo"]
    if t == "aeropuerto":
        if pd.notna(row.get("iata")):
            return "con_codigo_iata"          # aeropuerto comercial
        if pd.notna(row.get("icao")):
            return "aerodromo_registrado"     # tiene codigo OACI
        return "pista"
    if t == "puerto":
        ind = row.get("industrial")
        if ind == "port":
            return "portuario_industrial"
        if ind == "shipyard":
            return "astillero"
        if row.get("seamark:type") == "harbour":
            return "fondeadero"
        return "instalacion_menor"            # clubes de yates, caletas
    return t


def clasificar(row):
    """Tipo del punto, en el orden en que las etiquetas de OSM son mas especificas."""
    if row.get("aeroway") == "aerodrome":
        return "aeropuerto"
    if row.get("barrier") == "border_control" or row.get("amenity") == "customs":
        return "paso_fronterizo"
    if row.get("seamark:type") == "harbour" or row.get("harbour") == "yes" \
            or row.get("landuse") == "port" or row.get("industrial") == "port":
        return "puerto"
    if row.get("railway") in ("station", "halt"):
        return "estacion_ferroviaria"
    return "otro"


def enganche_m(lon, lat):
    try:
        j = requests.get(f"{OSRM}/nearest/v1/driving/{lon:.6f},{lat:.6f}", timeout=60).json()
        if j.get("code") == "Ok" and j.get("waypoints"):
            return float(j["waypoints"][0]["distance"])
    except Exception:
        pass
    return np.nan


def main():
    if not os.path.exists(CRUDO):
        raise SystemExit(
            f"falta {CRUDO}. Generalo con: bash src/osm_puntos.sh \"$(pwd)\""
        )

    pts = gpd.read_file(CRUDO).to_crs(4326)
    # los poligonos (un puerto suele mapearse como area) se reducen a su centroide
    pts["geometry"] = pts.geometry.representative_point()
    pts = pts[pts.geometry.notna()]

    com = gpd.read_file("datos/crudo/comunas/comunas.shp").to_crs(4326)
    com["geometry"] = com.geometry.make_valid()
    com = com[["cod_comuna", "Comuna", "geometry"]].rename(columns={"Comuna": "nombre_comuna"})

    j = gpd.sjoin(pts, com, how="inner", predicate="within")
    j["tipo"] = j.apply(clasificar, axis=1)
    j = j[j["tipo"] != "otro"].copy()

    nombre = j.get("name")
    j["nombre"] = nombre if nombre is not None else None
    j = j[j["nombre"].notna()]

    for col in ("iata", "icao", "industrial", "seamark:type", "operator"):
        if col not in j.columns:
            j[col] = None
    j["subtipo"] = j.apply(subtipo, axis=1)

    j["lon"] = j.geometry.x
    j["lat"] = j.geometry.y
    j["fuente_geo"] = "openstreetmap"
    j["snap_m"] = [enganche_m(x, y) for x, y in zip(j["lon"], j["lat"])]

    out = (
        j[["nombre", "tipo", "subtipo", "cod_comuna", "nombre_comuna", "lon", "lat",
           "iata", "icao", "operator", "fuente_geo", "snap_m"]]
        .rename(columns={"operator": "operador"})
        .drop_duplicates(subset=["nombre", "tipo", "cod_comuna"])
        .sort_values(["tipo", "cod_comuna", "nombre"])
        .reset_index(drop=True)
    )
    out.insert(0, "id_punto", range(1, len(out) + 1))

    # Un mismo terminal suele estar mapeado mas de una vez, como nodo y como area, con
    # nombres apenas distintos. Se marca en vez de borrarse: cual de los dos sobra es
    # criterio, y el criterio se deja a quien use el dato.
    out["posible_duplicado"] = False
    for _, g in out.groupby("tipo"):
        idx = list(g.index)
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, k = idx[a], idx[b]
                d = GEOD.inv(out.at[i, "lon"], out.at[i, "lat"],
                             out.at[k, "lon"], out.at[k, "lat"])[2]
                if d < 500:
                    out.loc[[i, k], "posible_duplicado"] = True
    out.to_parquet(f"{SALIDA}/puntos_logisticos.parquet", index=False)

    print(f"puntos: {len(out)}")
    print(out.groupby(["tipo", "subtipo"]).size().to_string())
    print(f"\ncomunas con al menos un punto: {out['cod_comuna'].nunique()}")
    print(f"puntos a mas de 2 km de un camino: {(out['snap_m'] > 2000).sum()}")
    print(f"posibles duplicados (a menos de 500 m de otro del mismo tipo): "
          f"{out['posible_duplicado'].sum()}")


if __name__ == "__main__":
    main()
