# Sonda: distancias intracomunales con ruteo vial real

**Fecha:** 2026-08-31
**Estado:** sonda exploratoria. Todo el codigo de `sonda/` es desechable.

## Que se probo

Cuatro comunas testigo (Providencia, Concepcion, Antofagasta, Natales) con ruteo vial
real (OSRM sobre OpenStreetMap Chile, extracto del 2026-08-31, md5
`6ba274aae78ea1d279a06a9a194e7649`), poligonos comunales de BCN y poblacion WorldPop
2020 constrained.

## Hallazgo 1: la definicion de centroide decide el resultado

Separacion maxima entre las cuatro definiciones de centroide:

| comuna | area km2 | separacion max |
|---|---:|---:|
| Providencia | 14,4 | 0,42 km |
| Concepcion | 219,1 | 8,49 km |
| Antofagasta | 30.703,2 | **128,24 km** |
| Natales | 51.382,2 | **200,78 km** |

El centroide geometrico de Antofagasta cae en el desierto, a 124 km de la ciudad.
Los dos centroides basados en actividad (poblacional y nucleo urbano) convergen entre
si en todas las comunas (0,02 a 25,8 km), mientras los dos geometricos se alejan de
ellos sin control. En Natales el centroide poblacional cae **fuera** del poligono.

**Implicancia:** el dataset debe entregar el centroide poblacional, y publicar los otros
solo como columnas de contraste.

## Hallazgo 2: la formula clasica de impedancia intrazonal falla en Chile

`d = (2/3)*sqrt(A/pi)` contra la mediana medida por Monte Carlo ruteado:

| comuna | (A) medido | formula | error |
|---|---:|---:|---:|
| Providencia | 2,88 km | 1,43 km | 0,50x |
| Concepcion | 4,94 km | 5,57 km | 1,13x |
| Antofagasta | 12,90 km | 65,91 km | 5,1x |
| Natales | 1,57 km | 85,26 km | **54,5x** |

La formula asume actividad homogenea sobre el area. En Natales la comuna tiene
51.382 km2 pero la poblacion esta toda en Puerto Natales, asi que el viaje interno real
mide 1,57 km y la formula predice 85. **No usar formulas cerradas de area.**

## Hallazgo 3: (A) y (B) son numeros distintos, y cuanto difieren depende de la comuna

| comuna | (A) viaje interno | (B) acceso, mediana | razon B/A |
|---|---:|---:|---:|
| Providencia | 2,88 km | 3,34 km | 1,16 |
| Concepcion | 4,94 km | 18,25 km | 3,70 |
| Natales | 1,57 km | 6,40 km | 4,09 |
| Antofagasta | 12,90 km | 92,44 km | **7,17** |

Confirma que (A) y (B) tienen que ser columnas separadas.

Dato lateral: en Natales solo **1 de 200 puntos del borde comunal** esta sobre la red
vial. El resto es fiordo y hielo.

## Hallazgo 4: gotchas tecnicos

- Los shapefiles de BCN vienen en **EPSG:3857 (Web Mercator)** y traen `st_area_sh`
  calculado en esa proyeccion. El area sale inflada 1,44x en Providencia, 1,56x en
  Concepcion y **2,49x en Natales**: el error crece hacia el sur. Usar area geodesica.
- OSRM **rutea por Argentina sin avisar**. Cualquier matriz nacional necesita una
  restriccion de frontera explicita, o al menos una columna con el % de ruta fuera de
  Chile.
- El grafo de Chile tiene **4 componentes conexas grandes** (3.405 en total).
- `Areas_Pobladas.shp` de BCN no trae `cod_comuna` ni poblacion: solo join espacial.
- BCN y Geofabrik exigen `User-Agent`; sin el, 401 y conexion cortada.

## Insumos verificados

| fuente | archivo | tamano | licencia |
|---|---|---:|---|
| BCN | `comunas_final.zip` (346 comunas, trae `cod_comuna`) | 42 MB | uso publico |
| BCN | `Areas_Pobladas.zip` (652 poligonos) | 2,5 MB | uso publico |
| Geofabrik | `chile-latest.osm.pbf` | 347 MB | ODbL |
| WorldPop | `chl_ppp_2020_UNadj_constrained.tif` | 14 MB | CC-BY 4.0 |

Todas redistribuibles. Ninguna API comercial involucrada.

Costo en disco del stack completo: **2,2 GB** (1,8 GB del grafo OSRM).
