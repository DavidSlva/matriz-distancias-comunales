"""Etapa 04b: distancias desde cada comuna a cada punto logistico.

Mismo metodo y mismas columnas que `distancias_comuna_comuna`, con `id_punto` en
lugar de `cod_destino`. Se separa de la etapa 04 porque depende de la capa de
puntos (etapa 03), que puede regenerarse sin rehacer la matriz comunal.

`km_ruta` es la ruta NACIONAL, igual que en la matriz comunal: para un modelo de
costos chileno, cruzar a Argentina es otra operacion y va en su propia columna.

El tiempo de las travesias se corrige con el mismo criterio que la etapa 04, en
`travesias.py`. Sin eso los dos archivos publicarian `minutos` con semantica distinta,
que es peor que publicarlos mal en los dos.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import requests
import travesias
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
OSRM_CL = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
SALIDA = "datos/salida"

# Mismas regiones que la etapa 04, y por la misma razon: son las unicas donde hay
# transbordadores, asi que pedir la geometria del resto seria gastar consultas para
# obtener ceros. Ver el comentario extendido en 04_distancias.py.
REGIONES_CON_BARCAZA = {7, 8, 9, 10, 11, 12, 14, 16}

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


def transbordo(base, origenes, destinos, pares):
    """Kilometros navegados y correccion de tiempo de cada par comuna-punto.

    El servicio `table` no entrega geometria, asi que hay que pedir ruta por ruta.
    Devuelve {(i, j): (km, segundos_de_correccion, se_modelo)}.
    """
    out = {}
    for k, (i, j) in enumerate(pares, 1):
        a, b = origenes[i], destinos[j]
        try:
            r = requests.get(
                f"{base}/route/v1/driving/"
                f"{a[0]:.6f},{a[1]:.6f};{b[0]:.6f},{b[1]:.6f}",
                params={"overview": "false", "steps": "true"},
                timeout=120,
            ).json()
            if r.get("code") == "Ok":
                out[(i, j)] = travesias.corrige(r["routes"][0]["legs"][0]["steps"])
        except requests.RequestException:
            pass
        if k % 5000 == 0:
            print(f"    transbordo {k:,}/{len(pares):,}")
    return out


def main():
    com = pd.read_parquet(f"{SALIDA}/comunas.parquet")
    com = com[com["es_comuna"]].sort_values("cod_comuna").reset_index(drop=True)
    pts = pd.read_parquet(f"{SALIDA}/puntos_logisticos.parquet").sort_values("id_punto")

    o = list(zip(com["canonico_lon"], com["canonico_lat"]))
    d = list(zip(pts["lon"], pts["lat"]))
    print(f"comunas: {len(o)}   puntos: {len(d)}   pares: {len(o)*len(d):,}")

    print("\n== grafo con Argentina ==")
    dist_int, _ = tabla(OSRM, o, d)
    print("\n== grafo recortado al territorio nacional ==")
    dist, dur = tabla(OSRM_CL, o, d)

    # Igual que en la etapa 04: el tiempo de las travesias se corrige despues de
    # rutear, y cada par declara si su minuto salio de OSM o del modelo.
    reg_o = (com["cod_comuna"].to_numpy() // 1000)
    reg_d = (pts["cod_comuna"].to_numpy() // 1000)
    existe = np.isfinite(dist)
    pares = [
        (i, j)
        for i in range(len(o))
        for j in range(len(d))
        if existe[i, j]
        and (reg_o[i] in REGIONES_CON_BARCAZA or reg_d[j] in REGIONES_CON_BARCAZA)
    ]
    print(f"\npares que podrian usar transbordador: {len(pares):,}")
    ferry = transbordo(OSRM_CL, o, d, pares)
    km_ferry = np.zeros_like(dist)
    corr_s = np.zeros_like(dist)
    modelado = np.zeros(dist.shape, dtype=bool)
    for (i, j), (km_t, seg, mod) in ferry.items():
        km_ferry[i, j] = km_t
        corr_s[i, j] = seg
        modelado[i, j] = mod
    km_ferry[~existe] = np.nan
    dur = dur + corr_s
    print(f"pares con tiempo de travesia modelado: {modelado.sum():,}")

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
            "minutos_fuente": np.where(modelado, "modelo", "osm").ravel(),
            "km_transbordo": km_ferry.ravel().round(3),
            "km_geodesica": km_geo.ravel().round(3),
            "factor_rodeo": rodeo.ravel().round(4),
            "ruta_existe": np.isfinite(dist).ravel(),
            "km_via_argentina": (dist_int / 1000).ravel().round(3),
            "solo_via_argentina": (np.isfinite(dist_int) & ~np.isfinite(dist)).ravel(),
            "dif_km_via_argentina": ((dist - dist_int) / 1000).ravel().round(3),
        }
    )
    df.to_parquet(f"{SALIDA}/distancias_comuna_punto.parquet", index=False)

    print(f"\nfilas: {len(df):,}")
    print(f"sin ruta nacional:   {(~df['ruta_existe']).mean():.1%}")
    print(f"solo_via_argentina:  {df['solo_via_argentina'].mean():.1%}")
    con = df[df["ruta_existe"]]
    print(f"con transbordo (>0 km): {(con['km_transbordo'] > 0).sum():,} "
          f"({(con['km_transbordo'] > 0).mean():.1%} de los que tienen ruta)")
    mod = con["minutos_fuente"] == "modelo"
    print(f"minutos_fuente = 'modelo': {mod.sum():,} ({mod.mean():.1%})")
    nac = df[df["ruta_existe"] & (df["km_geodesica"] > 1)]
    print(f"\nfactor de rodeo mediano: {nac['factor_rodeo'].median():.3f}")
    print(f"km_ruta mediano:         {nac['km_ruta'].median():.1f}")
    a = nac["dif_km_via_argentina"]
    print(f"pares donde cruzar acorta mas de 1 km: {(a > 1).sum():,}")


if __name__ == "__main__":
    main()
