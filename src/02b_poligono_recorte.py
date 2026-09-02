"""Etapa 02b: el poligono con el que se recorta el extracto de OpenStreetMap.

El recorte define que significa "ruta nacional", asi que equivocarlo corrompe dos
columnas publicadas.

**Por que no sirve la union de comunas.** Es tierra, y las rutas de transbordador van
sobre agua: recortar con ella las elimina. Con ese poligono, Puerto Montt a Chaiten
(239,7 km enteramente chilenos por la Carretera Austral) salia "sin ruta", y quedaba
marcado como que solo se llega por Argentina. Medido sobre las rutas a Punta Arenas, el
tramo que caia "fuera de Chile" eran 832 km de **navegacion chilena**, no de Argentina.

**Que se construye aca.** La tierra de Chile dilatada hacia el mar, menos la tierra de
los paises vecinos. Asi los corredores de barcaza quedan dentro y los caminos argentinos,
bolivianos y peruanos quedan fuera, que es exactamente la distincion que la columna
`solo_via_argentina` pretende medir.
"""
from __future__ import annotations

import json
import os

import geopandas as gpd
from shapely.geometry import mapping

SALIDA = "datos/salida"
PAIS = "Chile"
VECINOS = ["Argentina", "Bolivia", "Peru"]

# Dilatacion en grados. Los canales patagonicos por donde navegan las barcazas corren
# pegados a la costa; un grado (unos 67 km a latitud -53) los cubre con holgura sin
# necesitar una envolvente maritima enorme.
DILATACION = 1.0

# La simplificacion mantiene el recorte tratable para `osmium extract`, que se arrastra
# con poligonos de miles de anillos. A esta escala es inocua: separa paises, no predios.
TOLERANCIA = 0.01


def main():
    os.makedirs(SALIDA, exist_ok=True)

    # Se usa el poligono pais de Natural Earth, no la union de las 346 comunas. La
    # union comunal tiene decenas de miles de anillos y dilatarla agota la memoria del
    # contenedor (el kernel la mata con SIGKILL). Y no aporta: lo que se decide aca es
    # de que lado de la frontera esta un camino, no donde termina un predio.
    mundo = gpd.read_file("datos/crudo/ne_paises/ne_10m_admin_0_countries.shp").to_crs(4326)
    col = "ADMIN" if "ADMIN" in mundo.columns else "NAME"

    chile_tierra = mundo.loc[mundo[col] == PAIS, "geometry"].make_valid().union_all()
    vecinos = mundo[mundo[col].isin(VECINOS)]
    if len(vecinos) != len(VECINOS):
        raise SystemExit(f"faltan vecinos: se esperaban {VECINOS}, hay {list(vecinos[col])}")
    tierra_vecina = vecinos.geometry.make_valid().union_all()

    envolvente = chile_tierra.buffer(DILATACION)
    recorte = envolvente.difference(tierra_vecina).buffer(0)

    with open(f"{SALIDA}/chile_recorte.geojson", "w", encoding="utf-8") as fh:
        json.dump({"type": "Feature", "properties": {}, "geometry": mapping(recorte)}, fh)

    def area_km2(g):
        return gpd.GeoSeries([g], crs=4326).to_crs(6933).area.iloc[0] / 1e6

    print(f"chile tierra       {area_km2(chile_tierra):12,.0f} km2")
    print(f"dilatado {DILATACION}g      {area_km2(envolvente):12,.0f} km2")
    print(f"menos vecinos      {area_km2(recorte):12,.0f} km2   <- poligono de recorte")
    print(f"geometria: {recorte.geom_type}, {len(getattr(recorte, 'geoms', [recorte]))} partes")
    print(f"escrito en {SALIDA}/chile_recorte.geojson "
          f"({os.path.getsize(f'{SALIDA}/chile_recorte.geojson')/1e6:.1f} MB)")

    # control: el recorte no puede tragarse territorio vecino
    solapa = recorte.intersection(tierra_vecina)
    print(f"\nsolapamiento con tierra vecina: {area_km2(solapa):,.0f} km2 "
          f"({'ok' if area_km2(solapa) < 1000 else 'REVISAR'})")


if __name__ == "__main__":
    main()
