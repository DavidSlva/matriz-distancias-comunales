# El enganche a la red vial, y por que necesita un tope

Nota tecnica sobre una conducta de OSRM que afecta a cualquier matriz de distancias
construida sobre datos con islas o con red vial fragmentada. Chile tiene las dos cosas.

## La conducta

Para rutear entre dos coordenadas, OSRM primero las **engancha** a la red vial: busca el
segmento de camino que las representa (*phantom node*). Esa busqueda no se limita al
segmento mas cercano. OSRM evalua varios candidatos y **prefiere los que pertenecen a la
componente conexa grande**, para no devolver "sin ruta".

Sin un tope, esa preferencia no tiene limite de distancia.

## El sintoma

El centroide de Juan Fernandez esta en `-78,833 , -33,638`, en el archipielago, a 670 km
de la costa. Consultado sin tope, OSRM devolvia una ruta por carretera al continente.

Pidiendo la misma ruta con `steps=true`, el primer tramo delata el punto de partida:

```
   1.0 km  modo=driving  (sin nombre)
   1.4 km  modo=driving  Acceso a Caleta Loanco     <- Region del Maule, continente
  35.6 km  modo=driving  Ruta M-50-K
  79.4 km  modo=driving  Ruta L-30-K
  56.9 km  modo=driving  Ruta 5 Sur
```

La ruta nunca estuvo en la isla. Y el servicio `/nearest` sobre la misma coordenada
reportaba un enganche de **23,9 m**: si hay camino en la isla, pero el ruteo lo ignoraba
y se iba a la componente continental.

## Como se detecta en los datos

La huella es `factor_rodeo` por debajo de 1. Una ruta por carretera no puede ser mas
corta que la geodesica entre los mismos dos puntos, asi que un cociente menor a 1 no
significa "ruta eficiente": significa que el punto de partida no es el que se pidio.

Por eso el dataset publica `km_geodesica` junto a `km_ruta`, y por eso
`factor_rodeo >= 1` es un invariante **exacto** en `src/validar.py`, no una tolerancia
estadistica.

## El tope, y por que no se usa `radiuses`

`RADIO_M = 30000` metros. El valor deja pasar las comunas realmente remotas (Cisnes
engancha a 25 km) sin permitir el salto entre componentes conexas.

OSRM ofrece el parametro `radiuses` para esto, pero **es fragil para una matriz**: basta
que UNA coordenada no tenga camino dentro del radio para que el servidor responda
`400 NoSegment` y bote la consulta entera. Con Isla de Pascua en la lista, o con puntos
de borde del altiplano, la matriz completa falla.

El tope se aplica entonces **sobre la respuesta**, usando la distancia de enganche que la
propia consulta devuelve para cada coordenada. La fila y la columna de un punto
enganchado fuera de tope se anulan. Se verifico que ambos caminos producen resultados
identicos cuando `radiuses` no falla.

## Efecto medido

| caso | sin tope | con tope de 30 km |
|---|---|---|
| Juan Fernandez a Valparaiso | 503,1 km | **sin ruta** |
| Santiago a Valparaiso | 119,5 km | 119,5 km |
| Quinchao (Chiloe) a Puerto Montt | 180,2 km | 180,2 km |

Chiloe sigue ruteando, y eso es correcto: el perfil `car.lua` incluye transbordos, y en
Chile el transbordo es parte real del transporte carretero de carga.

Sobre los 119.025 pares de la matriz comunal, el minimo de `factor_rodeo` pasa de
**0,039 a 1,000**.

## Donde vive en el codigo

`RADIO_M` esta definido en `src/04_distancias.py`, con el comentario extendido, y se
replica en `src/04b_distancias_puntos.py` y `src/05_intracomuna.py`. La columna `snap_m`
de la tabla `comunas` expone la distancia de enganche real de cada centroide, para poder
filtrar segun el uso.
