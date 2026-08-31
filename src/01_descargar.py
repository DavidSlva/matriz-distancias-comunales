"""Etapa 01: baja las fuentes publicas declaradas en `datos/manifiesto.yml`.

Idempotente: si el archivo ya esta y su md5 coincide con el manifiesto, no lo
vuelve a bajar. Si el manifiesto no declara md5 (BCN republica sin versionar),
se conforma con que el archivo exista y reporta el md5 observado.
"""
from __future__ import annotations

import hashlib
import os
import zipfile

import requests
import yaml

CRUDO = "datos/crudo"
MANIFIESTO = "datos/manifiesto.yml"
# BCN responde 401 y Geofabrik corta la conexion si no se envia User-Agent.
CABECERAS = {"User-Agent": "matriz-distancias-comunales/1.0 (+https://github.com/DavidSlva)"}


def md5_de(ruta, bloque=1 << 20):
    h = hashlib.md5()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def bajar(url, destino):
    with requests.get(url, headers=CABECERAS, stream=True, timeout=1800) as r:
        r.raise_for_status()
        with open(destino, "wb") as fh:
            for trozo in r.iter_content(1 << 20):
                fh.write(trozo)


def main():
    os.makedirs(CRUDO, exist_ok=True)
    with open(MANIFIESTO, encoding="utf-8") as fh:
        manifiesto = yaml.safe_load(fh)

    for f in manifiesto["fuentes"]:
        destino = os.path.join(CRUDO, f["archivo"])
        esperado = f.get("md5")

        if os.path.exists(destino) and (esperado is None or md5_de(destino) == esperado):
            print(f"  {f['nombre']:16s} ya esta ({os.path.getsize(destino)/1e6:.1f} MB)")
        else:
            print(f"  {f['nombre']:16s} bajando...")
            bajar(f["url"], destino)
            obtenido = md5_de(destino)
            if esperado and obtenido != esperado:
                # No se continua con un insumo distinto al declarado: el dataset
                # dejaria de ser reproducible y nadie se enteraria.
                raise SystemExit(
                    f"md5 no coincide para {f['nombre']}:\n"
                    f"  esperado {esperado}\n  obtenido {obtenido}\n"
                    f"Si la fuente se actualizo a proposito, actualiza el manifiesto."
                )
            print(f"  {f['nombre']:16s} ok ({os.path.getsize(destino)/1e6:.1f} MB, md5 {obtenido})")

        if f.get("descomprimir_en"):
            carpeta = os.path.join(CRUDO, f["descomprimir_en"])
            os.makedirs(carpeta, exist_ok=True)
            with zipfile.ZipFile(destino) as z:
                z.extractall(carpeta)
            print(f"  {'':16s} descomprimido en {carpeta}")

    print("\natribuciones exigidas por las fuentes:")
    for f in manifiesto["fuentes"]:
        print(f"  - {f['atribucion']} ({f['licencia']})")


if __name__ == "__main__":
    main()
