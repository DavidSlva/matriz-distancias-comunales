"""Duracion de las travesias en transbordador.

OSRM no sabe cuanto demora un transbordador salvo que la via traiga `duration` en
OpenStreetMap. Cuando falta, el perfil `car.lua` cae a **5 km/h**, que no es la
velocidad de ninguna barcaza. De los 60 cruces de vehiculos del extracto de Chile,
35 traen el dato y 25 no.

Este modulo corrige ese tiempo despues de rutear, no dentro del grafo. Meter las
duraciones en el `.pbf` obligaria a reconstruir 7,4 GB de grafo por un cambio en 22
vias, y dejaria el supuesto escondido dentro del ruteador. Asi queda a la vista, y
cada par del dataset declara de donde salio su minuto en `minutos_fuente`.
"""
from __future__ import annotations

# Maniobra fija mas velocidad de crucero.
#
# Ajustado sobre los 35 cruces de vehiculos que SI traen `duration`, de 0,2 a 555,6 km:
# `horas = 0,0997 + 0,0530 x km`, R2 = 0,9958, error mediano 9,4 minutos. Son 6,0
# minutos de maniobra y atraque mas 18,9 km/h de crucero, o sea 10,2 nudos, que es la
# velocidad de un ro-ro costero.
#
# Esos 35 valores son confiables: coinciden exactamente con lo que publican Somarco,
# Naviera Austral y Transportes Puelche. Y el modelo valida contra dos tramos que no
# entraron al ajuste: predice 1:50 donde el operador publica 1h45, y 2:45 donde
# publica 3h.
#
# El termino fijo domina en los cruces cortos, y ahi corrige hacia arriba: una balsa de
# 70 metros no tarda 50 segundos, tarda lo que toma cargarla y descargarla.
MANIOBRA_H = 0.0997
H_POR_KM = 0.05300

# Velocidad a la que cae `car.lua` cuando la via de ferry no trae `duration`. Sirve de
# discriminador: un paso de ferry a exactamente 5 km/h es un cruce sin dato, y uno a
# cualquier otra velocidad trae su `duration` de OSM y no hay que tocarlo. Verificado
# contra el ruteador: Pargua-Chacao da 11,06 km/h y Niebla-Corral da 5,00 exacto.
VEL_SIN_DATO = 5.0
TOLERANCIA = 0.05


def horas(km):
    """Duracion modelada de una travesia de `km` kilometros."""
    return MANIOBRA_H + H_POR_KM * km


def corrige(pasos):
    """Kilometros navegados y correccion de tiempo de una ruta, paso por paso.

    Agrupa los pasos de ferry CONSECUTIVOS en una sola travesia. Importa porque un
    mismo servicio puede venir partido en varias vias de OSM (`CAL0013` esta en dos),
    y la maniobra de atraque se paga una vez por travesia, no una por via. Si entre
    dos tramos navegados hay camino, OSRM intercala un paso que no es ferry y quedan
    como travesias distintas, que es lo correcto.

    Solo corrige la travesia cuando TODOS sus pasos van a 5 km/h, o sea cuando ninguna
    de sus vias trae `duration`. Una travesia mixta se deja intacta: preferimos el dato
    de OSM antes que un valor calculado.

    Devuelve (km navegados, segundos a sumar al tiempo total, hubo correccion).
    """
    km_total = 0.0
    correccion_s = 0.0
    modelado = False
    i = 0
    while i < len(pasos):
        if pasos[i].get("mode") != "ferry":
            i += 1
            continue
        j = i
        km_tr = 0.0
        seg_tr = 0.0
        sin_dato = True
        while j < len(pasos) and pasos[j].get("mode") == "ferry":
            km = pasos[j]["distance"] / 1000
            seg = pasos[j]["duration"]
            km_tr += km
            seg_tr += seg
            vel = km / (seg / 3600) if seg > 0 else 0.0
            if abs(vel - VEL_SIN_DATO) > TOLERANCIA:
                sin_dato = False
            j += 1
        km_total += km_tr
        if sin_dato and km_tr > 0:
            correccion_s += horas(km_tr) * 3600 - seg_tr
            modelado = True
        i = j
    return km_total, correccion_s, modelado
