"""Comprueba la correccion de tiempo de las travesias.

La logica de `travesias.corrige` es sutil en dos puntos que no se ven mirando una
matriz de salida: agrupar los pasos de ferry contiguos en una sola travesia, y no
tocar las que ya traen su duracion en OpenStreetMap. Esto los fija.

Corre con `make validar`, sin datos ni ruteador.
"""
from __future__ import annotations

import sys

import travesias as t


def paso(km, vel_kmh, modo="ferry"):
    """Un paso de ruta de OSRM, con la velocidad que implicaria."""
    return {"mode": modo, "distance": km * 1000, "duration": (km / vel_kmh) * 3600}


def check(nombre, condicion, detalle=""):
    print(f"  [{'OK   ' if condicion else 'FALLA'}] {nombre}" + (f": {detalle}" if detalle else ""))
    return bool(condicion)


def main():
    print("travesias")
    r = []

    km, seg, mod = t.corrige([paso(50, 80, "driving")])
    r.append(check("una ruta sin ferry no se toca", km == 0 and seg == 0 and not mod))

    # Niebla-Corral: 3,99 km sin `duration`. OSRM lo cruza a 5 km/h, 47,9 minutos.
    km, seg, mod = t.corrige([paso(3.99, 5.0)])
    esperado = t.horas(3.99) * 3600 - 3.99 / 5.0 * 3600
    r.append(check("un cruce sin dato se corrige", mod and abs(seg - esperado) < 1,
                   f"{seg/60:+.1f} min"))

    # Pargua-Chacao trae `duration=00:25`, que son 11,06 km/h. No se toca.
    km, seg, mod = t.corrige([paso(4.61, 11.06)])
    r.append(check("un cruce con dato de OSM se respeta", not mod and seg == 0))

    # `CAL0013` esta partido en dos vias contiguas: es UNA travesia, una sola maniobra.
    km, seg, mod = t.corrige([paso(9.12, 5.0), paso(1.54, 5.0)])
    esperado = t.horas(10.66) * 3600 - 10.66 / 5.0 * 3600
    r.append(check("dos vias contiguas son una sola travesia",
                   mod and abs(seg - esperado) < 1, f"km={km:.2f}"))

    # Con camino en medio son dos travesias distintas, y se paga maniobra dos veces.
    km, seg, mod = t.corrige([paso(4.0, 5.0), paso(30, 80, "driving"), paso(4.0, 5.0)])
    esperado = 2 * (t.horas(4.0) * 3600 - 4.0 / 5.0 * 3600)
    r.append(check("dos travesias separadas pagan dos maniobras",
                   mod and abs(seg - esperado) < 1, f"km={km:.2f}"))

    # Ante la duda mandan los datos de OSM, no el modelo.
    km, seg, mod = t.corrige([paso(5.0, 5.0), paso(60, 16.86)])
    r.append(check("una travesia mixta se deja intacta", not mod and seg == 0))

    # Puerto Montt a Chaiten cruza tres veces, las tres con dato en OSM.
    km, seg, mod = t.corrige([paso(6.07, 8.09), paso(40, 80, "driving"),
                              paso(58.99, 16.86), paso(10, 80, "driving"),
                              paso(7.31, 10.97)])
    r.append(check("una ruta real toda tagueada no se toca",
                   not mod and seg == 0 and abs(km - 72.37) < 0.01))

    # El termino de maniobra domina en los cruces cortos, y ahi corrige hacia ARRIBA:
    # cargar y descargar una balsa de 70 metros no toma los 50 segundos de los 5 km/h.
    _, seg, mod = t.corrige([paso(0.07, 5.0)])
    r.append(check("una balsa de 70 m se hace mas lenta, no mas rapida",
                   mod and seg > 0, f"{seg/60:+.1f} min"))

    # La velocidad de crucero tiene que ser la de un barco, no la de un camion.
    v = 1 / t.H_POR_KM
    r.append(check("la velocidad de crucero es de un ro-ro costero", 15 < v < 25,
                   f"{v:.1f} km/h, {v/1.852:.1f} nudos"))

    print(f"\n{sum(r)}/{len(r)} comprobaciones OK")
    return 0 if all(r) else 1


if __name__ == "__main__":
    sys.exit(main())
