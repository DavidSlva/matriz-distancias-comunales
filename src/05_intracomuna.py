"""Etapa 05: las dos distancias intracomunales.

(A) Viaje interno. Impedancia intrazonal: distancia ruteada entre pares de puntos
    sorteados dentro de la comuna con probabilidad proporcional a la poblacion.

    ORIGEN Y DESTINO SALEN DE LA MISMA DISTRIBUCION, la poblacion, asi que (A)
    modela un viaje entre dos residentes al azar. No es "la distancia intracomunal"
    en abstracto: la distribucion de origen define el caso. Un despacho a domicilio
    sale de un local, no de un hogar, y su ultimo kilometro es MENOR que este (A),
    porque el comercio se ubica donde esta la gente. Para modelar ese caso lo unico
    que hay que cambiar es de donde se sortea `o`.

    No se usa formula cerrada de area: `(2/3)*sqrt(A/pi)` se equivoca por 141x en
    Tortel, donde 19.574 km2 tienen toda su poblacion en un solo pueblo.

(B) Tramo de acceso. Del centroide canonico a los puntos donde la red vial cruza
    el borde comunal. Es la primera y ultima milla de un viaje intercomunal, no un
    promedio de viajes internos. Las dos cantidades difieren hasta 7x.
"""
from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Geod
from rasterio.mask import mask
from shapely.geometry import Point

GEOD = Geod(ellps="WGS84")
# Se usa el grafo NACIONAL: este es un dataset chileno, y una comuna fronteriza
# no debe enganchar ni rutear por un camino argentino.
OSRM = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
SALIDA = "datos/salida"
RNG = np.random.default_rng(20260831)

# Punto de partida del Monte Carlo. El muestreo es ADAPTATIVO: el ruido de (A) no lo
# predice el tamano de la comuna sino cuanto descarta el filtro de enganche, porque eso
# es lo que determina la muestra efectiva. Con 150 fijo, una comuna que descarta el 84%
# queda con 3.600 pares utiles en vez de 22.500, y el CV de la mediana entre replicas
# sube de 1% a 15%. Ver `src/analisis_parametros.py`.
N_MUESTRA = 150
N_MAX = 400       # tope; sobre esto la consulta se vuelve pesada sin ganar precision
PARES_OBJETIVO = 20000
N_BORDE = 240     # puntos muestreados sobre el borde comunal
SNAP_MAX = 2000   # m; sobre esto el punto no representa un origen vial creible
RADIO_M = 30000   # tope de enganche del centroide; ver 04_distancias.py

# Aca NO se usa el parametro `radiuses` de OSRM, a diferencia de la etapa 04. Los
# puntos de borde del altiplano (Ollague, San Pedro) no tienen camino a menos de
# 30 km, y OSRM responde 400 NoSegment y bota la peticion entera. En su lugar se
# filtra despues, con la distancia de enganche que la propia respuesta devuelve:
# el efecto es el mismo y ningun punto valido se pierde por culpa de otro.


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
        timeout=900,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "Ok":
        raise RuntimeError(j)
    m = np.array([[np.nan if v is None else v for v in f] for f in j["distances"]])
    return (
        m,
        np.array([w["distance"] for w in j["sources"]]),
        np.array([w["distance"] for w in j["destinations"]]),
    )


def sortear(geom, src, n):
    """n puntos dentro de la comuna, con probabilidad proporcional a la poblacion."""
    try:
        arr, tr = mask(src, [geom], crop=True, nodata=0, filled=True)
    except ValueError:
        return []
    b = arr[0].astype("float64")
    b[b < 0] = 0.0
    fs, cs = np.nonzero(b)
    if len(fs) == 0:
        return []
    p = b[fs, cs]
    p = p / p.sum()
    idx = RNG.choice(len(fs), size=n, replace=True, p=p)
    xs, ys = rasterio.transform.xy(tr, fs[idx], cs[idx])
    px = abs(tr.a)
    return [
        Point(x + RNG.uniform(-px / 2, px / 2), y + RNG.uniform(-px / 2, px / 2))
        for x, y in zip(np.asarray(xs), np.asarray(ys))
    ]


def main():
    com = pd.read_parquet(f"{SALIDA}/comunas.parquet")
    com = com[com["es_comuna"]].sort_values("cod_comuna").reset_index(drop=True)
    poly = gpd.read_file("datos/crudo/comunas/comunas.shp").to_crs(4326)
    poly["geometry"] = poly.geometry.make_valid()
    poly = poly.set_index("cod_comuna")

    filas = []
    with rasterio.open("datos/crudo/chl_pop_2020.tif") as src:
        for n, row in enumerate(com.itertuples(), 1):
            cod = row.cod_comuna
            g = poly.loc[cod].geometry
            if hasattr(g, "__len__"):
                g = g.union_all() if hasattr(g, "union_all") else g.iloc[0]
            reg = dict(cod_comuna=cod)

            # ---- (A) viaje interno, con muestreo adaptativo
            n_muestra = N_MUESTRA
            o = sortear(g, src, n_muestra)
            d = sortear(g, src, n_muestra)
            m_ok = np.empty((0, 0))
            if o and d:
                m, so, sd = tabla(o, d)
                m_ok = m[np.ix_(so <= SNAP_MAX, sd <= SNAP_MAX)]
                v = m_ok[np.isfinite(m_ok) & (m_ok > 0)]

                # Si el descarte dejo pocos pares utiles, se reintenta una vez con la
                # muestra que haria falta. Un solo reintento basta: el descarte
                # observado estima bien el que se vera con mas puntos.
                if 0 < v.size < PARES_OBJETIVO:
                    n_muestra = min(
                        N_MAX, int(np.ceil(N_MUESTRA * np.sqrt(PARES_OBJETIVO / v.size)))
                    )
                    if n_muestra > N_MUESTRA:
                        o = sortear(g, src, n_muestra)
                        d = sortear(g, src, n_muestra)
                        m, so, sd = tabla(o, d)
                        m_ok = m[np.ix_(so <= SNAP_MAX, sd <= SNAP_MAX)]
                        v = m_ok[np.isfinite(m_ok) & (m_ok > 0)]

                reg.update(
                    a_n_muestra=n_muestra,
                    a_n_pares=int(v.size),
                    a_pct_descartado=float(1 - m_ok.size / m.size) if m.size else np.nan,
                    **{
                        f"a_p{q}": float(np.percentile(v, q)) / 1000 if v.size else np.nan
                        for q in (25, 50, 75, 95)
                    },
                )
            else:
                reg.update(a_n_muestra=n_muestra, a_n_pares=0, a_pct_descartado=np.nan,
                           **{f"a_p{q}": np.nan for q in (25, 50, 75, 95)})

            # ---- (B) tramo de acceso
            borde = g.boundary
            pts = [borde.interpolate(t) for t in
                   np.linspace(0, borde.length, N_BORDE, endpoint=False)]
            centro = Point(row.canonico_lon, row.canonico_lat)
            mb, sc, sb = tabla([centro], pts)
            # Si el propio centroide engancho lejisimos, la fila entera es basura:
            # OSRM salto a otra componente conexa y (B) mediria un viaje que no existe.
            if sc[0] > RADIO_M:
                util = np.zeros(len(pts), dtype=bool)
            else:
                util = np.isfinite(mb[0]) & (sb <= SNAP_MAX)
            vb = mb[0][util]
            reg.update(
                b_n_salidas=int(util.sum()),
                b_min=float(vb.min()) / 1000 if vb.size else np.nan,
                b_p50=float(np.median(vb)) / 1000 if vb.size else np.nan,
                b_max=float(vb.max()) / 1000 if vb.size else np.nan,
            )

            # ---- contraste: la formula clasica, incluida a proposito
            area_m2, _ = GEOD.geometry_area_perimeter(g)
            reg["radio_equivalente_km"] = (2 / 3) * np.sqrt(abs(area_m2) / np.pi) / 1000

            filas.append(reg)
            if n % 25 == 0:
                print(f"  {n}/{len(com)}")

    df = pd.DataFrame(filas)
    for c in df.columns:
        if c != "cod_comuna" and df[c].dtype.kind == "f":
            df[c] = df[c].round(4)
    df.to_parquet(f"{SALIDA}/intracomuna.parquet", index=False)

    print(f"\ncomunas: {len(df)}")
    print(f"sin (A) medible: {df['a_p50'].isna().sum()}   sin (B) medible: {df['b_min'].isna().sum()}")
    print("\n(A) viaje interno, mediana en km:")
    print(df["a_p50"].describe(percentiles=[0.1, 0.5, 0.9]).round(2).to_string())
    print("\n(B) tramo de acceso, mediana en km:")
    print(df["b_p50"].describe(percentiles=[0.1, 0.5, 0.9]).round(2).to_string())
    r = (df["b_p50"] / df["a_p50"]).replace([np.inf, -np.inf], np.nan)
    print(f"\nrazon B/A: mediana {r.median():.2f}   p10 {r.quantile(.1):.2f}   "
          f"p90 {r.quantile(.9):.2f}")
    f = (df["radio_equivalente_km"] / df["a_p50"]).replace([np.inf, -np.inf], np.nan)
    print(f"error de la formula clasica contra (A): mediana {f.median():.2f}x   "
          f"p90 {f.quantile(.9):.2f}x   max {f.max():.1f}x")


if __name__ == "__main__":
    main()
