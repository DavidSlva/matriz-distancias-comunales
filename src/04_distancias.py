"""Etapa 04: matriz de distancias entre las comunas.

Rutea cada par contra dos grafos: Chile completo y Chile recortado al poligono
nacional. La diferencia entre ambos identifica los pares a los que solo se llega
por tierra saliendo del pais.

La diagonal sale 0 por construccion (el centroide contra si mismo). La distancia
intracomunal real vive en `intracomuna.parquet`, que es otra pregunta.
"""
from __future__ import annotations

import os
from collections import deque

import numpy as np
import pandas as pd
import requests
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
OSRM_CL = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
SALIDA = "datos/salida"

# Radio maximo de enganche a la red vial, en metros.
#
# Sin este limite OSRM engancha arbitrariamente lejos: al elegir el punto de
# enganche prefiere la componente conexa grande antes que devolver "sin ruta".
# Con eso, Juan Fernandez enganchaba a "Acceso a Caleta Loanco", en el Maule, a
# 670 km, y la isla aparecia conectada por tierra con el continente.
# Con radio, esa misma consulta responde NoRoute, que es la verdad.
#
# 30 km deja pasar las comunas realmente remotas (Cisnes engancha a 25 km) sin
# permitir el salto entre componentes. La calidad del enganche queda expuesta en
# la columna `snap_m` de `comunas`.
#
# El tope NO se aplica con el parametro `radiuses` de OSRM: basta que UNA
# coordenada no tenga camino dentro del radio para que el servidor responda
# 400 NoSegment y bote la consulta entera (pasa con Isla de Pascua y con los
# puntos del altiplano). Se aplica despues, sobre la distancia de enganche que la
# propia respuesta devuelve, con el mismo efecto y sin fragilidad.
RADIO_M = 30000


def tabla(base, puntos, bloque=170):
    """Matriz completa de distancias y tiempos, en bloques para no reventar la URL.

    OSRM acepta hasta `--max-table-size` coordenadas por peticion, y la URL tiene
    limite practico de largo, asi que se pide por bloques de origenes.

    Devuelve tambien la distancia de enganche de cada coordenada a la red vial.
    """
    n = len(puntos)
    coords = ";".join(f"{x:.6f},{y:.6f}" for x, y in puntos)
    dist = np.full((n, n), np.nan)
    dur = np.full((n, n), np.nan)
    snap = np.full(n, np.nan)
    for i0 in range(0, n, bloque):
        i1 = min(i0 + bloque, n)
        r = requests.get(
            f"{base}/table/v1/driving/{coords}",
            params={
                "sources": ";".join(map(str, range(i0, i1))),
                "annotations": "distance,duration",
            },
            timeout=1800,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("code") != "Ok":
            raise RuntimeError(j)
        dist[i0:i1] = np.array(
            [[np.nan if v is None else v for v in fila] for fila in j["distances"]]
        )
        dur[i0:i1] = np.array(
            [[np.nan if v is None else v for v in fila] for fila in j["durations"]]
        )
        # `destinations` cubre las n coordenadas en cada bloque: basta el primero
        if np.isnan(snap).all():
            snap = np.array([w["distance"] for w in j["destinations"]])
        print(f"    origenes {i0}-{i1} de {n}")

    # una coordenada enganchada mas alla del tope no representa el punto pedido:
    # su fila y su columna se anulan en lugar de publicar un viaje inventado
    lejos = snap > RADIO_M
    if lejos.any():
        print(f"    {lejos.sum()} coordenadas enganchadas a mas de {RADIO_M/1000:.0f} km, anuladas")
        dist[lejos, :] = np.nan
        dist[:, lejos] = np.nan
        dur[lejos, :] = np.nan
        dur[:, lejos] = np.nan
    return dist, dur


def componentes(alcanzable):
    """Componentes conexas de la matriz de alcanzabilidad, por BFS."""
    n = len(alcanzable)
    comp = np.full(n, -1)
    actual = 0
    for s in range(n):
        if comp[s] != -1:
            continue
        cola = deque([s])
        comp[s] = actual
        while cola:
            u = cola.popleft()
            for v in np.nonzero(alcanzable[u] | alcanzable[:, u])[0]:
                if comp[v] == -1:
                    comp[v] = actual
                    cola.append(v)
        actual += 1
    return comp


def main():
    com = pd.read_parquet(f"{SALIDA}/comunas.parquet")
    com = com[com["es_comuna"]].sort_values("cod_comuna").reset_index(drop=True)
    cods = com["cod_comuna"].to_numpy()
    puntos = list(zip(com["canonico_lon"], com["canonico_lat"]))
    n = len(com)
    print(f"comunas: {n}   pares: {n*n:,}")

    print("\n== grafo Chile completo ==")
    d_full, t_full = tabla(OSRM, puntos)
    print("\n== grafo recortado a Chile ==")
    d_cl, _ = tabla(OSRM_CL, puntos)

    # geodesica entre los mismos dos puntos
    lon = np.array([p[0] for p in puntos])
    lat = np.array([p[1] for p in puntos])
    LON1, LON2 = np.meshgrid(lon, lon, indexing="ij")
    LAT1, LAT2 = np.meshgrid(lat, lat, indexing="ij")
    _, _, geo = GEOD.inv(LON1, LAT1, LON2, LAT2)

    existe_full = np.isfinite(d_full)
    existe_cl = np.isfinite(d_cl)
    comp = componentes(existe_cl)
    print(f"\ncomponentes conexas dentro de Chile: {comp.max()+1}")
    for c in range(comp.max() + 1):
        m = comp == c
        if m.sum() > 3:
            print(f"  componente {c}: {m.sum()} comunas "
                  f"(regiones {sorted(set(com.loc[m, 'cod_region']))})")

    O, D = np.meshgrid(cods, cods, indexing="ij")
    km_ruta = d_full / 1000
    km_geo = geo / 1000
    with np.errstate(divide="ignore", invalid="ignore"):
        rodeo = np.where(km_geo > 0, km_ruta / km_geo, np.nan)

    df = pd.DataFrame(
        {
            "cod_origen": O.ravel(),
            "cod_destino": D.ravel(),
            "km_ruta": km_ruta.ravel().round(3),
            "minutos": (t_full / 60).ravel().round(2),
            "km_geodesica": km_geo.ravel().round(3),
            "factor_rodeo": rodeo.ravel().round(4),
            "ruta_existe": existe_full.ravel(),
            "solo_via_argentina": (existe_full & ~existe_cl).ravel(),
        }
    )
    df.to_parquet(f"{SALIDA}/distancias_comuna_comuna.parquet", index=False)

    # se escribe aparte: la etapa 06 ensambla las columnas derivadas sobre `comunas`,
    # para que 04 y 05 puedan correr en paralelo sin pisarse el mismo archivo
    pd.DataFrame({"cod_comuna": cods, "componente_vial": comp}).to_parquet(
        f"{SALIDA}/_componente_vial.parquet", index=False
    )

    fuera = df[df["cod_origen"] != df["cod_destino"]]
    print(f"\nfilas: {len(df):,}")
    print(f"pares sin ruta ni por Argentina: {(~fuera['ruta_existe']).sum():,} "
          f"({(~fuera['ruta_existe']).mean():.1%})")
    print(f"pares solo_via_argentina:        {fuera['solo_via_argentina'].sum():,} "
          f"({fuera['solo_via_argentina'].mean():.1%})")
    print("\nfactor de rodeo (pares con ruta nacional):")
    nac = fuera[fuera["ruta_existe"] & ~fuera["solo_via_argentina"]]
    print(nac["factor_rodeo"].describe(percentiles=[0.1, 0.5, 0.9]).round(3).to_string())
    print("\nkm_ruta:")
    print(nac["km_ruta"].describe(percentiles=[0.5, 0.95]).round(1).to_string())


if __name__ == "__main__":
    main()
