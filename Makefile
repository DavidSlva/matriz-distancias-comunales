RAIZ := $(shell pwd)
GEO   := docker compose run --rm geo python

.PHONY: all descargar grafos centroides distancias intracomuna ensamblar validar enlaces limpiar

all: descargar grafos centroides intracomuna distancias ensamblar validar

descargar:
	$(GEO) src/01_descargar.py

## Grafo de Chile completo (incluye el corredor vial argentino) y grafo recortado
## al poligono nacional. La diferencia entre ambos define `solo_via_argentina`.
grafos:
	docker run --rm -v "$(RAIZ)/datos/osrm:/data" osrm/osrm-backend \
	  osrm-extract -p /opt/car.lua /data/chile-latest.osm.pbf
	docker run --rm -v "$(RAIZ)/datos/osrm:/data" osrm/osrm-backend \
	  osrm-partition /data/chile-latest.osrm
	docker run --rm -v "$(RAIZ)/datos/osrm:/data" osrm/osrm-backend \
	  osrm-customize /data/chile-latest.osrm
	bash src/osrm_build_recortado.sh "$(RAIZ)"

## `centroides` produce el geojson que `grafos` necesita para recortar, asi que en
## una reconstruccion desde cero hay que correrlo antes del segundo grafo.
centroides:
	docker compose up -d osrm
	$(GEO) src/02_centroides.py

intracomuna:
	docker compose up -d osrm
	$(GEO) src/05_intracomuna.py

distancias:
	docker compose up -d osrm osrm_cl
	$(GEO) src/04_distancias.py

ensamblar:
	$(GEO) src/06_ensamblar.py

validar:
	$(GEO) src/validar.py

## Los enlaces institucionales chilenos se mueven. Ya se publico un 404 una vez.
enlaces:
	$(GEO) src/verificar_enlaces.py

limpiar:
	docker compose down
	rm -rf datos/salida
