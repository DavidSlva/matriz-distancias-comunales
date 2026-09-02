#!/usr/bin/env bash
# Construye el segundo grafo OSRM, el recortado al territorio nacional.
#
# Un par con ruta en el grafo completo y sin ruta en este es, por construccion,
# `solo_via_argentina`: la unica forma de llegar es saliendo del pais.
#
# El poligono lo produce `src/02b_poligono_recorte.py` e INCLUYE LAS AGUAS. Recortar
# con la union de comunas (tierra) eliminaba las rutas de transbordador y hacia que
# Puerto Montt a Chaiten, 239,7 km enteramente chilenos, apareciera como accesible
# solo por Argentina.
set -euo pipefail

RAIZ="${1:?uso: osrm_build_recortado.sh <ruta absoluta del repo>}"

echo "== recortando el extracto OSM al poligono de Chile =="
docker run --rm \
  -v "${RAIZ}/datos:/data" \
  debian:bookworm-slim bash -c '
    set -e
    apt-get update -qq >/dev/null
    apt-get install -y -qq osmium-tool >/dev/null
    mkdir -p /data/osrm_cl
    osmium extract \
      --polygon /data/salida/chile_recorte.geojson \
      --set-bounds --overwrite \
      -o /data/osrm_cl/chile-recortado.osm.pbf \
      /data/crudo/chile-latest.osm.pbf
    ls -la /data/osrm_cl/
  '

echo "== construyendo el grafo =="
for etapa in "osrm-extract -p /opt/car.lua /data/chile-recortado.osm.pbf" \
             "osrm-partition /data/chile-recortado.osrm" \
             "osrm-customize /data/chile-recortado.osrm"; do
  echo "-- ${etapa}"
  docker run --rm -v "${RAIZ}/datos/osrm_cl:/data" osrm/osrm-backend ${etapa} 2>&1 | tail -3
done

echo "== listo =="
du -sh "${RAIZ}/datos/osrm_cl"
