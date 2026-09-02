#!/usr/bin/env bash
# Construye el grafo "internacional": Chile mas Argentina.
#
# Sin esto la columna `solo_via_argentina` no puede existir. El extracto de Geofabrik
# para Chile **no contiene caminos argentinos**: medido el 2026-09-02, en la franja de
# longitud -65 a -56 tiene 0 vias con `highway`. Durante semanas el dataset publico una
# columna que decia "solo se llega por Argentina" sobre un grafo donde Argentina no
# existia; lo que en realidad marcaba eran las rutas de transbordador, porque el
# poligono de recorte era solo tierra.
#
# Con los dos paises en el grafo, la comparacion contra el grafo nacional pasa a medir
# lo que su nombre dice.
set -euo pipefail

RAIZ="${1:?uso: osrm_build_internacional.sh <ruta absoluta del repo>}"

echo "== fusionando los extractos de Chile y Argentina =="
docker run --rm \
  -v "${RAIZ}/datos:/data" \
  debian:bookworm-slim bash -c '
    set -e
    apt-get update -qq >/dev/null
    apt-get install -y -qq osmium-tool >/dev/null
    mkdir -p /data/osrm_int
    osmium merge --overwrite \
      -o /data/osrm_int/cono-sur.osm.pbf \
      /data/crudo/chile-latest.osm.pbf \
      /data/crudo/argentina-latest.osm.pbf
    ls -la /data/osrm_int/
  '

echo "== construyendo el grafo =="
for etapa in "osrm-extract -p /opt/car.lua /data/cono-sur.osm.pbf" \
             "osrm-partition /data/cono-sur.osrm" \
             "osrm-customize /data/cono-sur.osrm"; do
  echo "-- ${etapa}"
  docker run --rm -v "${RAIZ}/datos/osrm_int:/data" osrm/osrm-backend ${etapa} 2>&1 | tail -3
done

echo "== listo =="
du -sh "${RAIZ}/datos/osrm_int"
