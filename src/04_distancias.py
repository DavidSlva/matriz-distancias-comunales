"""Etapa 04: matriz de distancias entre las comunas.

Rutea cada par contra dos grafos: uno que **incluye Argentina** y otro recortado al
territorio nacional. La diferencia entre ambos responde dos preguntas distintas: que
pares solo se alcanzan saliendo del pais, y cuanto cambia la distancia si se permite
cruzar.

**OSRM devuelve la ruta mas rapida, no la mas corta.** Eso importa aca: como el perfil
penaliza el transbordador a 5 km/h, en el grafo internacional el ruteador prefiere
rodear por camino argentino antes que navegar, aunque sean mas kilometros. Puerto Montt
a Punta Arenas da 2.100,8 km por Chile y 2.172,8 permitiendo Argentina: la internacional
es mas LARGA en distancia porque es mas rapida en tiempo. Por eso la columna se llama
`dif_km_via_argentina` y no "ahorro": puede ser negativa.

El tiempo de las travesias se corrige despues de rutear. Donde OSM trae `duration` se
respeta ese valor; donde no lo trae, OSRM cae a 5 km/h y se reemplaza por un modelo
ajustado sobre los cruces que si estan tagueados. La columna `minutos_fuente` dice cual
de los dos casos aplica a cada par.

Publica ademas `km_transbordo`: cuantos kilometros de la ruta nacional van en
transbordador. Para carga eso no es un detalle del trazado sino otra operacion, con
horario, cupo y tarifa.

La diagonal sale 0 por construccion (el centroide contra si mismo). La distancia
intracomunal real vive en `intracomuna.parquet`, que es otra pregunta.
"""
from __future__ import annotations

import os
from collections import deque

import numpy as np
import pandas as pd
import requests
import travesias
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
OSRM = os.environ.get("OSRM_URL", "http://osrm:5000")
OSRM_CL = os.environ.get("OSRM_CL_URL", "http://osrm_cl:5000")
SALIDA = "datos/salida"

# Radio maximo de enganche a la red vial, en metros.
#
# Sin este limite OSRM engancha arbitrariamente lejos: al elegir el punto de enganche
# prefiere la componente conexa grande antes que devolver "sin ruta". Con eso, Juan
# Fernandez enganchaba a "Acceso a Caleta Loanco", en el Maule, a 670 km, y la isla
# aparecia conectada por tierra con el continente.
#
# 30 km deja pasar las comunas realmente remotas (Cisnes engancha a 25 km) sin permitir
# el salto entre componentes. La calidad del enganche queda en `snap_m` de `comunas`.
#
# El tope NO se aplica con el parametro `radiuses` de OSRM: basta que UNA coordenada no
# tenga camino dentro del radio para que el servidor responda 400 NoSegment y bote la
# consulta entera. Se aplica despues, sobre la distancia de enganche que la propia
# respuesta devuelve, con el mismo efecto y sin fragilidad.
RADIO_M = 30000

# Solo puede haber navegacion si algun extremo esta en una region con transbordadores.
# Entre dos comunas del norte no hay barcaza posible, y pedir la geometria de esos
# pares seria gastar decenas de miles de consultas para obtener ceros.
#
# La lista NO es a ojo: sale de ubicar los 60 cruces de vehiculos del extracto de OSM.
# Ademas del arco austral hay balsas fluviales en el Maule (rio Maule), Nuble (rio
# Itata) y La Araucania (Pocoyan, Caracoles). Miden entre 70 y 340 metros.
#
# Incluirlas cuesta unos 15 minutos mas de ruteo y corrige en la direccion CONTRARIA al
# resto: en un cruce de 70 m los 5 km/h de OSRM dan 50 segundos, cuando cargar y
# descargar una balsa toma varios minutos. Ahi el ruteador no sobreestima, subestima.
REGIONES_CON_BARCAZA = {7, 8, 9, 10, 11, 12, 14, 16}


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
        if np.isnan(snap).all():
            snap = np.array([w["distance"] for w in j["destinations"]])
        print(f"    origenes {i0}-{i1} de {n}")

    lejos = snap > RADIO_M
    if lejos.any():
        print(f"    {lejos.sum()} coordenadas enganchadas a mas de "
              f"{RADIO_M / 1000:.0f} km, anuladas")
        dist[lejos, :] = np.nan
        dist[:, lejos] = np.nan
        dur[lejos, :] = np.nan
        dur[:, lejos] = np.nan
    return dist, dur


def transbordo_km(base, puntos, pares):
    """Kilometros navegados y correccion de tiempo de cada ruta.

    Exige la geometria por par, que el servicio `table` no entrega, asi que se
    consulta ruta por ruta. Por eso la lista de pares llega ya filtrada.

    Devuelve {(i, j): (km, segundos_de_correccion, se_modelo)}.
    """
    out = {}
    for k, (i, j) in enumerate(pares, 1):
        a, b = puntos[i], puntos[j]
        try:
            r = requests.get(
                f"{base}/route/v1/driving/"
                f"{a[0]:.6f},{a[1]:.6f};{b[0]:.6f},{b[1]:.6f}",
                params={"overview": "false", "steps": "true"},
                timeout=120,
            ).json()
            if r.get("code") == "Ok":
                out[(i, j)] = travesias.corrige(
                    r["routes"][0]["legs"][0]["steps"]
                )
        except requests.RequestException:
            pass
        if k % 5000 == 0:
            print(f"    transbordo {k:,}/{len(pares):,}")
    return out


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
    print(f"comunas: {n}   pares: {n * n:,}")

    print("\n== grafo con Argentina ==")
    d_int, _ = tabla(OSRM, puntos)
    print("\n== grafo recortado al territorio nacional ==")
    d_nac, t_nac = tabla(OSRM_CL, puntos)

    lon = np.array([p[0] for p in puntos])
    lat = np.array([p[1] for p in puntos])
    LON1, LON2 = np.meshgrid(lon, lon, indexing="ij")
    LAT1, LAT2 = np.meshgrid(lat, lat, indexing="ij")
    _, _, geo = GEOD.inv(LON1, LAT1, LON2, LAT2)

    existe_int = np.isfinite(d_int)
    existe_nac = np.isfinite(d_nac)

    # La conectividad se mide sobre el grafo NACIONAL, que es la pregunta que importa:
    # que partes de Chile se alcanzan entre si sin salir del pais.
    comp = componentes(existe_nac)
    print(f"\ncomponentes conexas dentro de Chile: {comp.max() + 1}")
    for c in range(comp.max() + 1):
        m = comp == c
        if m.sum() > 2:
            print(f"  componente {c}: {m.sum()} comunas "
                  f"(regiones {sorted(set(com.loc[m, 'cod_region']))})")

    reg = com["cod_region"].to_numpy()
    candidatos = [
        (i, j)
        for i in range(n)
        for j in range(n)
        if i != j and existe_nac[i, j]
        and (reg[i] in REGIONES_CON_BARCAZA or reg[j] in REGIONES_CON_BARCAZA)
    ]
    print(f"\npares que podrian usar transbordador: {len(candidatos):,}")
    ferry = transbordo_km(OSRM_CL, puntos, candidatos)
    km_ferry = np.zeros((n, n))
    corr_s = np.zeros((n, n))
    modelado = np.zeros((n, n), dtype=bool)
    for (i, j), (km, seg, mod) in ferry.items():
        km_ferry[i, j] = km
        corr_s[i, j] = seg
        modelado[i, j] = mod
    km_ferry[~existe_nac] = np.nan

    # El tiempo del transbordo se corrige DESPUES de rutear, no dentro del grafo. Meter
    # la duracion en el .pbf obligaria a reconstruir 7,4 GB de grafo por un cambio en 22
    # vias, y ademas dejaria el supuesto escondido dentro del ruteador. Asi queda a la
    # vista y cada par declara de donde salio su minuto.
    t_nac = t_nac + corr_s
    print(f"pares con tiempo de travesia modelado: {modelado.sum():,}")

    O, D = np.meshgrid(cods, cods, indexing="ij")
    km_int = d_int / 1000
    km_nac = d_nac / 1000
    km_geo = geo / 1000
    with np.errstate(divide="ignore", invalid="ignore"):
        rodeo = np.where(km_geo > 0, km_nac / km_geo, np.nan)
    dif_int = km_nac - km_int

    df = pd.DataFrame(
        {
            "cod_origen": O.ravel(),
            "cod_destino": D.ravel(),
            "km_ruta": km_nac.ravel().round(3),
            "minutos": (t_nac / 60).ravel().round(2),
            "minutos_fuente": np.where(modelado, "modelo", "osm").ravel(),
            "km_transbordo": km_ferry.ravel().round(3),
            "km_geodesica": km_geo.ravel().round(3),
            "factor_rodeo": rodeo.ravel().round(4),
            "ruta_existe": existe_nac.ravel(),
            "km_via_argentina": km_int.ravel().round(3),
            "solo_via_argentina": (existe_int & ~existe_nac).ravel(),
            "dif_km_via_argentina": dif_int.ravel().round(3),
        }
    )
    df.to_parquet(f"{SALIDA}/distancias_comuna_comuna.parquet", index=False)

    # se escribe aparte: la etapa 06 ensambla las columnas derivadas sobre `comunas`,
    # para que 04 y 05 puedan correr en paralelo sin pisarse el mismo archivo
    pd.DataFrame({"cod_comuna": cods, "componente_vial": comp}).to_parquet(
        f"{SALIDA}/_componente_vial.parquet", index=False
    )

    fuera = df[df["cod_origen"] != df["cod_destino"]]
    con = fuera[fuera["ruta_existe"]]
    print(f"\nfilas: {len(df):,}")
    print(f"sin ruta nacional:      {(~fuera['ruta_existe']).sum():,} "
          f"({(~fuera['ruta_existe']).mean():.1%})")
    print(f"solo_via_argentina:     {fuera['solo_via_argentina'].sum():,} "
          f"({fuera['solo_via_argentina'].mean():.1%})")
    print(f"con transbordo (>0 km): {(con['km_transbordo'] > 0).sum():,} "
          f"({(con['km_transbordo'] > 0).mean():.1%} de los que tienen ruta)")

    t = con.loc[con["km_transbordo"] > 0, "km_transbordo"]
    if len(t):
        print("\nkm_transbordo en los pares que navegan:")
        print(t.describe(percentiles=[0.5, 0.9]).round(1).to_string())

    mod = con["minutos_fuente"] == "modelo"
    print(f"\nminutos_fuente = 'modelo': {mod.sum():,} pares "
          f"({mod.mean():.1%} de los que tienen ruta)")
    if mod.any():
        nav = con["km_transbordo"] > 0
        print(f"  de los {nav.sum():,} pares que navegan, "
              f"{(mod & nav).sum():,} llevan al menos una travesia sin dato en OSM")

    a = con["dif_km_via_argentina"]
    print(f"\npares donde ir por Argentina acorta mas de 1 km: {(a > 1).sum():,}")
    if (a > 1).any():
        print(a[a > 1].describe(percentiles=[0.5, 0.9]).round(1).to_string())

    print("\nfactor de rodeo (ruta nacional):")
    print(con["factor_rodeo"].describe(percentiles=[0.1, 0.5, 0.9]).round(3).to_string())
    print("\nkm_ruta (nacional):")
    print(con["km_ruta"].describe(percentiles=[0.5, 0.95]).round(1).to_string())


if __name__ == "__main__":
    main()
