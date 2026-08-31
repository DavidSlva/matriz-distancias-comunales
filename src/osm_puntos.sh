#!/usr/bin/env bash
# Extrae de OpenStreetMap los objetos que pueden ser un punto logistico y los
# entrega como GeoJSON para la etapa 03. No usa ningun catalogo privado.
set -euo pipefail

RAIZ="${1:?uso: osm_puntos.sh <ruta absoluta del repo>}"

docker run --rm -v "${RAIZ}/datos:/data" debian:bookworm-slim bash -c '
  set -e
  apt-get update -qq >/dev/null
  apt-get install -y -qq osmium-tool >/dev/null

  osmium tags-filter --overwrite \
    -o /data/crudo/_puntos.osm.pbf \
    /data/crudo/chile-latest.osm.pbf \
    nwr/aeroway=aerodrome \
    nwr/harbour=yes \
    nwr/landuse=port \
    nwr/industrial=port \
    nwr/seamark:type=harbour \
    nwr/barrier=border_control \
    nwr/amenity=customs

  osmium export --overwrite \
    -f geojson \
    -o /data/crudo/puntos_osm.geojson \
    /data/crudo/_puntos.osm.pbf

  rm -f /data/crudo/_puntos.osm.pbf
  ls -la /data/crudo/puntos_osm.geojson
'
