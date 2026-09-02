RAIZ := $(shell pwd)
GEO   := docker compose run --rm geo python

.PHONY: all descargar centroides grafos intracomuna distancias puntos ensamblar validar enlaces limpiar

all: descargar centroides grafos puntos intracomuna distancias ensamblar validar

descargar:
	$(GEO) src/01_descargar.py

## `centroides` produce el poligono de recorte que `grafos` necesita, asi que en una
## reconstruccion desde cero tiene que correr ANTES de los grafos.
centroides:
	$(GEO) src/02_centroides.py
	$(GEO) src/02b_poligono_recorte.py

## Dos grafos, y los dos hacen falta:
##   `osrm_int`  Chile mas Argentina. Sin el, `solo_via_argentina` no se puede calcular:
##               el extracto de Chile no contiene caminos argentinos.
##   `osrm_cl`   Chile recortado a su territorio, AGUAS INCLUIDAS. Recortar con la union
##               de comunas (tierra) eliminaba las rutas de transbordador.
grafos:
	bash src/osrm_build_internacional.sh "$(RAIZ)"
	bash src/osrm_build_recortado.sh "$(RAIZ)"

puntos:
	bash src/osm_puntos.sh "$(RAIZ)"
	docker compose up -d osrm_cl
	$(GEO) src/03_puntos_logisticos.py

intracomuna:
	docker compose up -d osrm_cl
	$(GEO) src/05_intracomuna.py

distancias:
	docker compose up -d osrm osrm_cl
	$(GEO) src/04_distancias.py
	$(GEO) src/04b_distancias_puntos.py

ensamblar:
	$(GEO) src/06_ensamblar.py

validar:
	$(GEO) src/travesias_test.py
	$(GEO) src/validar.py

## Los enlaces institucionales chilenos se mueven. Ya se publico un 404 una vez.
enlaces:
	$(GEO) src/verificar_enlaces.py

## Justifica N_MUESTRA y SNAP_MAX. No entra en `all`: se corre al revisar la eleccion.
parametros:
	docker compose up -d osrm_cl
	$(GEO) src/analisis_parametros.py

limpiar:
	docker compose down
	rm -rf datos/salida
