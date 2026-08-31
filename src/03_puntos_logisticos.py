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

OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
SALIDA = "datos/salida"
CRUDO = "datos/crudo/puntos_osm.geojson"


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

    j["lon"] = j.geometry.x
    j["lat"] = j.geometry.y
    j["fuente_geo"] = "openstreetmap"
    j["verificado"] = False
    j["snap_m"] = [enganche_m(x, y) for x, y in zip(j["lon"], j["lat"])]

    out = (
        j[["nombre", "tipo", "cod_comuna", "nombre_comuna", "lon", "lat",
           "fuente_geo", "verificado", "snap_m"]]
        .drop_duplicates(subset=["nombre", "tipo", "cod_comuna"])
        .sort_values(["tipo", "cod_comuna", "nombre"])
        .reset_index(drop=True)
    )
    out.insert(0, "id_punto", range(1, len(out) + 1))
    out.to_parquet(f"{SALIDA}/puntos_logisticos.parquet", index=False)

    print(f"puntos: {len(out)}")
    print(out.groupby("tipo").size().to_string())
    print(f"\ncomunas con al menos un punto: {out['cod_comuna'].nunique()}")
    print(f"puntos a mas de 2 km de un camino: {(out['snap_m'] > 2000).sum()}")


if __name__ == "__main__":
    main()
