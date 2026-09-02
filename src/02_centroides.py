"""Etapa 02: atributos y centroides de las 346 comunas.

Produce `datos/salida/comunas.parquet` con las cuatro definiciones de centroide,
area geodesica, poblacion y calidad de enganche a la red vial.

El poligono de recorte lo construye `src/02b_poligono_recorte.py`, no esta etapa.
"""
from __future__ import annotations

import itertools
import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import CRS, Geod, Transformer
from rasterio.mask import mask
from shapely.geometry import Point, mapping
from shapely.ops import transform as shp_transform

GEOD = Geod(ellps="WGS84")
# Se usa el grafo NACIONAL: este es un dataset chileno, y una comuna fronteriza
# no debe enganchar ni rutear por un camino argentino.
OSRM = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
RUTA_POB = "datos/crudo/chl_pop_2020.tif"
SALIDA = "datos/salida"


def proyeccion_local(geom):
    """Azimutal equidistante centrada en la comuna: metros honestos a escala local.

    Calcular un centroide en grados sobre EPSG:4326 pondera mal en latitudes altas.
    Chile llega a -56, donde un grado de longitud mide la mitad que uno de latitud.
    """
    c = geom.centroid
    local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +datum=WGS84 +units=m +no_defs"
    )
    ida = Transformer.from_crs(4326, local, always_xy=True).transform
    vuelta = Transformer.from_crs(local, 4326, always_xy=True).transform
    return ida, vuelta


def centroide_poblacional(geom, src):
    """Centro de masa poblacional sobre la grilla WorldPop constrained (~100 m)."""
    try:
        arr, tr = mask(src, [geom], crop=True, nodata=0, filled=True)
    except ValueError:
        return None, 0.0
    banda = arr[0].astype("float64")
    banda[banda < 0] = 0.0
    filas, cols = np.nonzero(banda)
    if len(filas) == 0:
        return None, 0.0
    pesos = banda[filas, cols]
    xs, ys = rasterio.transform.xy(tr, filas, cols)
    return (
        Point(np.average(np.asarray(xs), weights=pesos), np.average(np.asarray(ys), weights=pesos)),
        float(pesos.sum()),
    )


def enganche_m(punto):
    """Distancia del punto al camino mas cercano, segun OSRM. Indicador de calidad."""
    r = requests.get(f"{OSRM}/nearest/v1/driving/{punto.x:.6f},{punto.y:.6f}", timeout=60)
    j = r.json()
    if j.get("code") != "Ok" or not j.get("waypoints"):
        return np.nan
    return float(j["waypoints"][0]["distance"])


def main():
    os.makedirs(SALIDA, exist_ok=True)
    com = gpd.read_file("datos/crudo/comunas/comunas.shp").to_crs(4326)
    com["geometry"] = com.geometry.make_valid()
    areas = gpd.read_file("datos/crudo/areas_pobladas/Areas_Pobladas.shp").to_crs(4326)
    areas["geometry"] = areas.geometry.make_valid()

    filas = []
    with rasterio.open(RUTA_POB) as src:
        for n, (_, row) in enumerate(com.iterrows(), 1):
            g = row.geometry
            ida, vuelta = proyeccion_local(g)
            g_local = shp_transform(ida, g)

            c_geom = shp_transform(vuelta, g_local.centroid)
            c_sup = shp_transform(vuelta, g_local.representative_point())
            c_pob, poblacion = centroide_poblacional(g, src)

            # nucleo urbano: centroide del mayor poligono de area poblada de la comuna
            sub = areas[areas.intersects(g)]
            c_urb = None
            if len(sub):
                recorte = sub.geometry.intersection(g)
                recorte = recorte[~recorte.is_empty]
                if len(recorte):
                    sup = [abs(GEOD.geometry_area_perimeter(x)[0]) for x in recorte]
                    c_urb = recorte.iloc[int(np.argmax(sup))].centroid

            # cascada de respaldo, explicita: nunca inventamos un punto en silencio
            if c_pob is None:
                origen_canonico = "nucleo_urbano" if c_urb is not None else "sobre_superficie"
                canonico = c_urb if c_urb is not None else c_sup
            else:
                origen_canonico = "poblacional"
                canonico = c_pob

            area_m2, _ = GEOD.geometry_area_perimeter(g)

            # Cuanto se separan entre si las cuatro definiciones. Es la medida de cuan
            # mal representa un punto unico a esta comuna: 0,05 km en las urbanas,
            # 200,78 km en Natales. Se publica como columna porque es un indicador de
            # calidad por fila, no un dato de contexto.
            candidatos = {"pob": c_pob, "geom": c_geom, "sup": c_sup, "urb": c_urb}
            candidatos = {k: v for k, v in candidatos.items() if v is not None}
            pares = [
                GEOD.inv(a.x, a.y, b.x, b.y)[2] / 1000
                for a, b in itertools.combinations(candidatos.values(), 2)
            ]
            dispersion = max(pares) if pares else np.nan

            filas.append(
                dict(
                    cod_comuna=int(row["cod_comuna"]),
                    # BCN trae un poligono `cod_comuna = 0` ("Zona sin demarcar", limites
                    # en disputa, poblacion 0) que no es una comuna. Se marca en vez de
                    # filtrarse, para que nada se pierda en silencio aguas abajo.
                    es_comuna=int(row["cod_comuna"]) > 0,
                    nombre_comuna=row["Comuna"],
                    nombre_provincia=row["Provincia"],
                    cod_region=int(row["codregion"]),
                    nombre_region=row["Region"],
                    area_km2=abs(area_m2) / 1e6,
                    poblacion_2020=poblacion,
                    centroide_pob_lon=c_pob.x if c_pob else np.nan,
                    centroide_pob_lat=c_pob.y if c_pob else np.nan,
                    centroide_geom_lon=c_geom.x,
                    centroide_geom_lat=c_geom.y,
                    centroide_sup_lon=c_sup.x,
                    centroide_sup_lat=c_sup.y,
                    centroide_urb_lon=c_urb.x if c_urb is not None else np.nan,
                    centroide_urb_lat=c_urb.y if c_urb is not None else np.nan,
                    canonico_lon=canonico.x,
                    canonico_lat=canonico.y,
                    origen_canonico=origen_canonico,
                    canonico_dentro=bool(g.contains(canonico)),
                    dispersion_centroides_km=dispersion,
                    snap_m=enganche_m(canonico),
                )
            )
            if n % 50 == 0:
                print(f"  {n}/{len(com)}")

    df = pd.DataFrame(filas).sort_values("cod_comuna").reset_index(drop=True)
    df.to_parquet(f"{SALIDA}/comunas.parquet", index=False)

    print(f"\ncomunas: {len(df)}")
    print(f"origen del centroide canonico:\n{df['origen_canonico'].value_counts().to_string()}")
    print(f"centroide canonico fuera del poligono: {(~df['canonico_dentro']).sum()}")
    print(f"poblacion total: {df['poblacion_2020'].sum():,.0f}")
    print(f"area total: {df['area_km2'].sum():,.0f} km2")
    print("\nseparacion maxima entre las cuatro definiciones (dispersion_centroides_km):")
    print(df["dispersion_centroides_km"].describe(percentiles=[0.5, 0.9]).round(2).to_string())
    print("\nenganche a la red vial (snap_m):")
    print(df["snap_m"].describe(percentiles=[0.5, 0.9, 0.99]).round(1).to_string())
    print(f"\ncomunas con snap_m > 2000 m: {(df['snap_m'] > 2000).sum()}")
    peor = df.nlargest(8, "snap_m")[["cod_comuna", "nombre_comuna", "area_km2", "snap_m"]]
    print(peor.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
