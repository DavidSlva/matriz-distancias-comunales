"""Sonda 1: cuanto difieren las definiciones de centroide en comunas testigo.

Calcula cuatro centroides por comuna y las distancias geodesicas entre ellos.
Si las cuatro coinciden, la eleccion no importa; si divergen, es la decision
mas importante del proyecto.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS, Geod, Transformer
from rasterio.mask import mask
from shapely.geometry import Point

GEOD = Geod(ellps="WGS84")
TESTIGO = {2101: "Antofagasta", 8101: "Concepcion", 12401: "Natales", 13123: "Providencia"}


def crs_local(geom):
    """Azimutal equidistante centrada en la comuna: metros honestos a escala local."""
    c = geom.centroid
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )


def centroide_poblacional(geom, ruta_raster):
    """Centro de masa poblacional usando WorldPop (grilla ~100 m, constrained)."""
    with rasterio.open(ruta_raster) as src:
        arr, transform = mask(src, [geom], crop=True, nodata=0, filled=True)
        banda = arr[0].astype("float64")
        banda[banda < 0] = 0.0
        if banda.sum() <= 0:
            return None, 0.0
        filas, cols = np.nonzero(banda)
        pesos = banda[filas, cols]
        # centros de celda
        xs, ys = rasterio.transform.xy(transform, filas, cols)
        lon = np.average(np.asarray(xs), weights=pesos)
        lat = np.average(np.asarray(ys), weights=pesos)
        return Point(lon, lat), float(pesos.sum())


def main():
    com = gpd.read_file("datos/crudo/comunas/comunas.shp").to_crs(4326)
    pob = gpd.read_file("datos/crudo/areas_pobladas/Areas_Pobladas.shp").to_crs(4326)

    filas = []
    for cod, nombre in TESTIGO.items():
        g = com.loc[com["cod_comuna"] == cod].geometry.union_all()

        area_m2, _ = GEOD.geometry_area_perimeter(g)
        area_km2 = abs(area_m2) / 1e6
        area_merc = com.loc[com["cod_comuna"] == cod, "st_area_sh"].sum() / 1e6

        local = crs_local(g)
        a_local = Transformer.from_crs(4326, local, always_xy=True).transform
        de_local = Transformer.from_crs(local, 4326, always_xy=True).transform
        from shapely.ops import transform as shp_transform

        g_local = shp_transform(a_local, g)

        cents = {}
        cents["geometrico"] = shp_transform(de_local, g_local.centroid)
        cents["sobre_superficie"] = shp_transform(de_local, g_local.representative_point())

        p_pop, hab = centroide_poblacional(g, "datos/crudo/chl_pop_2020.tif")
        cents["poblacional"] = p_pop

        dentro = pob[pob.intersects(g)].copy()
        if not dentro.empty:
            dentro["geometry"] = dentro.geometry.intersection(g)
            dentro = dentro[~dentro.geometry.is_empty]
        if not dentro.empty:
            dentro["a"] = [abs(GEOD.geometry_area_perimeter(x)[0]) for x in dentro.geometry]
            mayor = dentro.loc[dentro["a"].idxmax()]
            cents["nucleo_urbano"] = mayor.geometry.centroid
            nucleo = f"{mayor.get('Localidad') or mayor.get('Entidad')}"
        else:
            cents["nucleo_urbano"] = None
            nucleo = "(sin area poblada)"

        dentro_poly = {k: (g.contains(v) if v else None) for k, v in cents.items()}

        print(f"\n{'='*78}\n{nombre} ({cod})")
        print(f"  area geodesica      {area_km2:12,.1f} km2")
        print(f"  area segun st_area_sh (Web Mercator) {area_merc:12,.1f} km2  "
              f"-> inflada {area_merc/area_km2:.2f}x")
        print(f"  poblacion WorldPop  {hab:12,.0f} hab")
        print(f"  nucleo urbano mayor {nucleo}")
        print("  centroides:")
        for k, v in cents.items():
            if v is None:
                print(f"    {k:18s} (no disponible)")
                continue
            print(f"    {k:18s} lon={v.x:10.5f} lat={v.y:10.5f}  dentro={dentro_poly[k]}")

        print("  separacion entre definiciones (km):")
        claves = [k for k, v in cents.items() if v is not None]
        for i, a in enumerate(claves):
            for b in claves[i + 1:]:
                _, _, d = GEOD.inv(cents[a].x, cents[a].y, cents[b].x, cents[b].y)
                print(f"    {a:18s} <-> {b:18s} {d/1000:8.2f}")
                filas.append((nombre, a, b, d / 1000))

    print(f"\n{'='*78}\nRESUMEN: separacion maxima por comuna")
    import pandas as pd
    df = pd.DataFrame(filas, columns=["comuna", "a", "b", "km"])
    print(df.groupby("comuna")["km"].agg(["max", "mean"]).round(2).to_string())


if __name__ == "__main__":
    main()
