# Matriz de distancias entre comunas de Chile

Distancias viales entre las comunas de Chile, calculadas con ruteo real sobre
OpenStreetMap, **incluyendo las dos formas de distancia intracomunal** que no existen
en ninguna otra fuente publica.

Todo el pipeline es reproducible desde cero con `make all` y cuatro fuentes publicas.
No usa ninguna API comercial.

## Que tiene de distinto

**1. La diagonal no vale cero.** El centroide de una comuna contra si mismo mide 0 por
construccion, pero un viaje que nace y muere dentro de la misma comuna no. Este dataset
publica dos cantidades distintas para eso:

- **(A) viaje interno**: mediana de la distancia ruteada entre pares de puntos sorteados
  dentro de la comuna, con probabilidad proporcional a la poblacion.
- **(B) tramo de acceso**: del centroide a los puntos donde la red vial cruza el borde
  comunal. Es la primera y ultima milla de un viaje intercomunal.

Son cantidades diferentes: la razon B/A tiene mediana 2,87 y llega a 206 en Tortel.

**2. No usa formulas cerradas de area.** La formula clasica de impedancia intrazonal,
`(2/3)*sqrt(A/pi)`, asume actividad homogenea sobre la comuna. En Chile eso falla
espectacularmente: Tortel tiene 19.574 km2 con toda su poblacion en un pueblo, y la
formula predice 52,6 km donde lo medido es 0,36 km. **Error de 145x.** La columna
`radio_equivalente_km` esta incluida a proposito, para que el error sea visible.

**3. Distingue "lejos" de "inalcanzable".** El grafo vial de Chile tiene 9 componentes
conexas. A Magallanes no se llega por tierra sin pasar por Argentina. El dataset marca
eso con `solo_via_argentina`, calculado con dos grafos: uno de Chile completo y otro
recortado al poligono nacional.

**4. Publica cuatro definiciones de centroide, no una.** "El centroide de la comuna" es
al menos cuatro objetos distintos y en Chile difieren hasta **201 km** (Natales). El
centroide geometrico de Antofagasta cae en pleno desierto, a 124 km de la ciudad. El
canonico de este dataset es el **ponderado por poblacion**; los otros tres van como
columnas de contraste.

## Descargar

Los datos se publican como
[GitHub Release](https://github.com/DavidSlva/matriz-distancias-comunales/releases/latest),
no en el arbol del repositorio. Cada tabla viene en CSV y en Parquet.

```bash
# una tabla suelta
curl -LO https://github.com/DavidSlva/matriz-distancias-comunales/releases/latest/download/intracomuna.csv

# todas
gh release download --repo DavidSlva/matriz-distancias-comunales
```

Leerlas desde Python, sin descargar nada a mano:

```python
import pandas as pd

base = "https://github.com/DavidSlva/matriz-distancias-comunales/releases/latest/download"
intra    = pd.read_parquet(f"{base}/intracomuna.parquet")
comunas  = pd.read_parquet(f"{base}/comunas.parquet")
distancias = pd.read_parquet(f"{base}/distancias_comuna_comuna.parquet")
```

## Tablas

| tabla | filas | que es |
|---|---:|---|
| `comunas` | 346 | atributos, las 4 definiciones de centroide y calidad |
| `intracomuna` | 345 | (A) y (B) por comuna, con percentiles |
| `distancias_comuna_comuna` | 119.025 | matriz dirigida 345 x 345 |
| `puntos_logisticos` | 451 | puertos, aeropuertos y pasos fronterizos desde OSM |
| `distancias_comuna_punto` | 155.595 | matriz 345 x 451 |

Cada una en Parquet y CSV, en `datos/salida/`.

### `comunas`

| columna | descripcion |
|---|---|
| `cod_comuna` | codigo oficial |
| `es_comuna` | falso solo para el poligono `0` "Zona sin demarcar" de BCN, que no es una comuna. Se publica marcado en vez de filtrarse |
| `nombre_comuna`, `nombre_provincia`, `cod_region`, `nombre_region` | identidad |
| `area_km2` | area **geodesica** sobre el elipsoide WGS84 |
| `poblacion_2020` | suma de WorldPop constrained dentro del poligono |
| `centroide_pob_lon/lat` | centro de masa poblacional. **Canonico** |
| `centroide_geom_lon/lat` | centroide geometrico, en azimutal equidistante local |
| `centroide_sup_lon/lat` | punto garantizado dentro del poligono |
| `centroide_urb_lon/lat` | centroide del mayor poligono de area poblada |
| `canonico_lon/lat` | el punto efectivamente usado para rutear |
| `origen_canonico` | de cual definicion salio el canonico |
| `canonico_dentro` | si el canonico cae dentro del poligono. Falso en 11 comunas costeras y de archipielago |
| `snap_m` | distancia del canonico al camino mas cercano. **Indicador de calidad** |
| `componente_vial` | componente conexa del grafo vial nacional |
| `n_salidas_viales` | puntos del borde comunal que estan sobre la red |

### `intracomuna`

| columna | descripcion |
|---|---|
| `a_p25`, `a_p50`, `a_p75`, `a_p95` | **(A)** viaje interno, en km |
| `a_n_pares` | pares efectivamente ruteados |
| `a_pct_descartado` | fraccion de la muestra descartada por enganche excesivo |
| `b_min`, `b_p50`, `b_max` | **(B)** tramo de acceso, en km |
| `b_n_salidas` | salidas viales alcanzables encontradas |
| `radio_equivalente_km` | la formula clasica, como contraste |

### `distancias_comuna_comuna` y `distancias_comuna_punto`

| columna | descripcion |
|---|---|
| `cod_origen` | comuna de origen |
| `cod_destino` / `id_punto` | destino |
| `km_ruta` | distancia por carretera |
| `minutos` | tiempo de viaje a **flujo libre**. No modela trafico |
| `km_geodesica` | linea recta sobre el elipsoide entre los mismos dos puntos |
| `factor_rodeo` | `km_ruta / km_geodesica`. Mediana nacional 1,248 |
| `ruta_existe` | falso cuando no hay camino ni pasando por Argentina |
| `solo_via_argentina` | verdadero cuando hay ruta en el grafo completo y no en el recortado |

## Como reproducirlo

Requiere Docker. Ocupa unos 5 GB entre insumos y grafos.

```bash
make descargar     # baja las 4 fuentes y verifica md5
make centroides    # produce comunas + el poligono para recortar
make grafos        # construye los dos grafos OSRM (lento: decenas de minutos)
make intracomuna
make distancias
make ensamblar
make validar
```

O `make all`.

## Limitaciones declaradas

- **Cubre 345 de las 346 comunas oficiales.** El shapefile de BCN no incluye la comuna
  Antartica (12202).
- **Solo red vial.** No modela transporte maritimo ni ferroviario. El perfil de ruteo si
  incluye transbordos, que en Chile son parte real del transporte carretero de carga
  (Chiloe, Carretera Austral).
- **Los minutos son de flujo libre.** Sin trafico, sin estacionalidad, sin restricciones
  vehiculares.
- **Un centroide es un punto, y una comuna no lo es.** La columna `snap_m` expone cuanto
  se aleja el punto de la red vial: 21 comunas superan los 2 km y conviene filtrarlas
  segun el uso.
- BCN advierte que su cartografia "solo posee caracter referencial, y bajo ninguna
  circunstancia deberia ser utilizado para realizar trabajos que requieran precision
  geodesica".

## Fuentes

| fuente | que aporta | licencia |
|---|---|---|
| [Biblioteca del Congreso Nacional de Chile](https://www.bcn.cl/siit/mapas_vectoriales) | poligonos comunales y areas pobladas | uso libre con atribucion |
| [Geofabrik / OpenStreetMap](https://download.geofabrik.de/south-america/chile.html) | red vial | ODbL 1.0 |
| [WorldPop](https://www.worldpop.org/) | grilla de poblacion 2020 constrained | CC-BY 4.0 |

Atribucion requerida al reutilizar:

> Contiene informacion de la Biblioteca del Congreso Nacional de Chile.
> Datos viales (c) colaboradores de OpenStreetMap, ODbL.
> Poblacion: WorldPop (www.worldpop.org), CC-BY 4.0.

## Licencia

| que | licencia |
|---|---|
| Codigo (`src/`, `Makefile`, `Dockerfile`, `docker-compose.yml`) | MIT, ver `LICENSE` |
| **Datos** (`datos/salida/`) | **ODbL 1.0**, ver `LICENSE-DATA.txt` |
| Documentacion (`docs/`, `notas/`, este README) | CC-BY 4.0, ver `LICENSE-DOCS.txt` |

Los datos van bajo ODbL porque derivan de OpenStreetMap y su clausula de reparto por
igual lo exige.

**Que significa en la practica.** Si usas este dataset para producir algo (un calculo de
costos, un mapa, un informe, un modelo), eso es una *Produced Work* bajo ODbL: solo
requiere atribucion, **no** te obliga a abrir tu producto. La clausula de reparto por
igual se activa unicamente si publicas una version modificada de **la base de datos
misma**. El uso interno no impone ninguna obligacion mas alla de citar.
