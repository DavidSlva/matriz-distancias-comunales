"""Etapa 06: ensambla las columnas derivadas y publica CSV junto al Parquet.

Las etapas 04 y 05 producen atributos de comuna (`componente_vial`,
`n_salidas_viales`) que no pueden escribirse desde ambas sin pisarse. Aca se unen.
"""
from __future__ import annotations

import os

import pandas as pd

SALIDA = "datos/salida"


def main():
    com = pd.read_parquet(f"{SALIDA}/comunas.parquet")

    ruta_comp = f"{SALIDA}/_componente_vial.parquet"
    if os.path.exists(ruta_comp):
        com = com.drop(columns=["componente_vial"], errors="ignore").merge(
            pd.read_parquet(ruta_comp), on="cod_comuna", how="left"
        )

    ruta_intra = f"{SALIDA}/intracomuna.parquet"
    if os.path.exists(ruta_intra):
        intra = pd.read_parquet(ruta_intra)[["cod_comuna", "b_n_salidas"]]
        com = com.drop(columns=["n_salidas_viales"], errors="ignore").merge(
            intra.rename(columns={"b_n_salidas": "n_salidas_viales"}),
            on="cod_comuna",
            how="left",
        )

    com.to_parquet(f"{SALIDA}/comunas.parquet", index=False)

    for nombre in ["comunas", "intracomuna", "distancias_comuna_comuna",
                   "puntos_logisticos", "distancias_comuna_punto"]:
        p = f"{SALIDA}/{nombre}.parquet"
        if not os.path.exists(p):
            print(f"  (falta {nombre}, se omite)")
            continue
        d = pd.read_parquet(p)
        d.to_csv(f"{SALIDA}/{nombre}.csv", index=False, encoding="utf-8")
        mb_p = os.path.getsize(p) / 1e6
        mb_c = os.path.getsize(f"{SALIDA}/{nombre}.csv") / 1e6
        print(f"  {nombre:28s} {len(d):>9,} filas  {len(d.columns):>2} cols  "
              f"parquet {mb_p:6.1f} MB  csv {mb_c:7.1f} MB")


if __name__ == "__main__":
    main()
