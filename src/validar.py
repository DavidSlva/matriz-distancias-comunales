"""Invariantes del dataset. Falla con codigo distinto de 0 si alguno no se cumple."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

SALIDA = "datos/salida"
fallos: list[str] = []


def check(nombre, condicion, detalle=""):
    ok = bool(condicion)
    print(f"  [{'ok ' if ok else 'FALLA'}] {nombre}" + (f"  {detalle}" if detalle else ""))
    if not ok:
        fallos.append(nombre)


def main():
    com = pd.read_parquet(f"{SALIDA}/comunas.parquet")
    reales = com[com["es_comuna"]]

    print("comunas")
    check("345 comunas reales (BCN no incluye Antartica, 12202)", len(reales) == 345,
          f"hay {len(reales)}")
    check("sin cod_comuna duplicado", reales["cod_comuna"].is_unique)
    check("area total ~756.000 km2", 700_000 < reales["area_km2"].sum() < 820_000,
          f"{reales['area_km2'].sum():,.0f} km2")
    check("poblacion total entre 18 y 20 millones",
          18e6 < reales["poblacion_2020"].sum() < 20e6,
          f"{reales['poblacion_2020'].sum():,.0f}")
    check("todo centroide canonico tiene coordenada",
          reales[["canonico_lon", "canonico_lat"]].notna().all().all())
    check("longitudes dentro del rango de Chile",
          reales["canonico_lon"].between(-110, -66).all())
    check("latitudes dentro del rango de Chile",
          reales["canonico_lat"].between(-56, -17).all())

    p = f"{SALIDA}/distancias_comuna_comuna.parquet"
    if os.path.exists(p):
        d = pd.read_parquet(p)
        n = len(reales)
        print("\ndistancias_comuna_comuna")
        check(f"{n}x{n} filas", len(d) == n * n, f"hay {len(d):,}")
        check("sin nulos en las claves", d[["cod_origen", "cod_destino"]].notna().all().all())
        check("ninguna distancia negativa", (d["km_ruta"].fillna(0) >= 0).all())
        diag = d[d["cod_origen"] == d["cod_destino"]]
        check("diagonal en cero", (diag["km_ruta"].fillna(0) == 0).all())
        fuera = d[d["cod_origen"] != d["cod_destino"]]
        con_ruta = fuera[fuera["ruta_existe"] & (fuera["km_geodesica"] > 1)]
        # Invariante fisico, no estadistico: ninguna ruta por carretera puede ser mas
        # corta que la geodesica entre los mismos dos puntos. Cuando se viola, OSRM
        # engancho el punto lejos del que se pidio (ver notas/2026-08-31-osrm-engancha).
        check("factor de rodeo >= 1 en TODOS los pares con ruta",
              (con_ruta["factor_rodeo"] >= 1.0).all(),
              f"minimo {con_ruta['factor_rodeo'].min():.4f}")
        check("factor de rodeo mediano entre 1,1 y 1,8",
              1.1 < con_ruta["factor_rodeo"].median() < 1.8,
              f"{con_ruta['factor_rodeo'].median():.3f}")

        # testigo con distancia conocida: Santiago (13101) a Valparaiso (5101)
        t = d[(d["cod_origen"] == 13101) & (d["cod_destino"] == 5101)]
        if len(t):
            km = float(t["km_ruta"].iloc[0])
            check("Santiago a Valparaiso entre 100 y 145 km", 100 < km < 145, f"{km:.1f} km")

        # Magallanes contra la zona central: solo se llega saliendo del pais
        mag = reales.loc[reales["cod_region"] == 12, "cod_comuna"]
        cen = reales.loc[reales["cod_region"].isin([13, 5, 6]), "cod_comuna"]
        sub = d[d["cod_origen"].isin(cen) & d["cod_destino"].isin(mag)]
        if len(sub):
            check("Magallanes desde la zona central: solo_via_argentina",
                  sub["solo_via_argentina"].mean() > 0.95,
                  f"{sub['solo_via_argentina'].mean():.1%} de {len(sub)} pares")

    p = f"{SALIDA}/intracomuna.parquet"
    if os.path.exists(p):
        i = pd.read_parquet(p)
        print("\nintracomuna")
        check("una fila por comuna real", len(i) == len(reales), f"hay {len(i)}")
        check("(A) no negativa", (i["a_p50"].dropna() >= 0).all())
        check("(A) percentiles ordenados",
              (i[["a_p25", "a_p50", "a_p75", "a_p95"]].dropna().diff(axis=1).iloc[:, 1:] >= -1e-9)
              .all().all())
        check("toda comuna con salidas viales tiene b_min",
              i.loc[i["b_n_salidas"] > 0, "b_min"].notna().all())
        check("(A) medible en al menos el 95% de las comunas",
              i["a_p50"].notna().mean() > 0.95, f"{i['a_p50'].notna().mean():.1%}")

    print()
    if fallos:
        print(f"FALLARON {len(fallos)} invariantes: {', '.join(fallos)}")
        sys.exit(1)
    print("todos los invariantes se cumplen")


if __name__ == "__main__":
    main()
