# Bug: OSRM engancha a 670 km y conecta una isla con el continente

**Fecha:** 2026-08-31

## Resumen

La primera corrida de la matriz daba **Juan Fernandez a Iquique = 2.141 km por
carretera**. Juan Fernandez es un archipielago a 670 km de la costa: no hay ruta
terrestre posible. El error venia del enganche del punto a la red vial, no del ruteo.

## Hallazgos detallados

### Causa raiz

OSRM, al elegir el punto de enganche (*phantom node*) de una coordenada, no se limita
al segmento mas cercano: busca varios candidatos y **prefiere los que pertenecen a la
componente conexa grande**, para evitar devolver "sin ruta". Sin un radio maximo esa
busqueda no tiene tope, asi que el centroide de Juan Fernandez (-78,833, -33,638)
enganchaba a un camino del continente.

### Confirmacion

Pidiendo la ruta con `steps=true`, el primer tramo delata el punto de partida:

```
   1.0 km  modo=driving  (sin nombre)
   1.4 km  modo=driving  Acceso a Caleta Loanco     <- Region del Maule, continente
  35.6 km  modo=driving  Ruta M-50-K
  79.4 km  modo=driving  Ruta L-30-K
  56.9 km  modo=driving  Ruta 5 Sur
```

`Acceso a Caleta Loanco` esta cerca de Chanco, en el Maule. La ruta nunca estuvo en la
isla.

Contradiccion adicional que confirmaba el diagnostico: el servicio `/nearest` reportaba
un enganche de **23,9 m** para esa misma coordenada, o sea que si hay camino en la isla.
El `route` lo ignoraba y se iba al continente.

La huella en los datos es `factor_rodeo` muy por debajo de 1 (minimo observado 0,039):
imposible que una ruta sea 25 veces mas corta que la linea recta, salvo que el punto de
partida no sea el que se pidio.

## Fix aplicado

Pasar `radiuses` en toda peticion a OSRM, con tope de 30.000 m por coordenada.

```python
RADIO_M = 30000
...
params={..., "radiuses": ";".join([str(RADIO_M)] * n)}
```

Verificacion, mismos tres casos antes y despues:

| caso | sin radio | radio 30 km |
|---|---|---|
| Juan Fernandez a Valparaiso | 503,1 km | **NoRoute** |
| Santiago a Valparaiso | 119,5 km | 119,5 km |
| Quinchao (Chiloe) a Puerto Montt | 180,2 km | 180,2 km |

El valor 30 km se eligio porque deja pasar las comunas realmente remotas (Cisnes
engancha a 25 km) sin permitir el salto entre componentes conexas.

Chiloe sigue ruteando, y eso es correcto: el perfil `car.lua` incluye transbordos, y en
Chile el transbordo es parte real del transporte carretero de carga.

## Archivos involucrados

| Archivo | Rol |
|---|---|
| `src/04_distancias.py` | matriz comuna-comuna; define `RADIO_M` con el comentario extendido |
| `src/04b_distancias_puntos.py` | matriz comuna-punto |
| `src/05_intracomuna.py` | Monte Carlo y tramo de acceso |

## Preguntas abiertas

- El alcance del error en la primera corrida fue acotado: ~688 pares de 119.025 (0,6%),
  esencialmente la fila y la columna de Juan Fernandez. Isla de Pascua no se vio
  afectada porque esta a 3.500 km, fuera de cualquier radio de busqueda.
- Un enganche de 30 km sigue siendo una distorsion grande para la comuna que lo sufre.
  La columna `snap_m` de `comunas` expone el valor real para que sea filtrable.
