"""Verifica que los enlaces externos de la documentacion sigan vivos.

Existe porque ya se publico un 404: una URL copiada de un buscador, nunca abierta.
Los enlaces institucionales chilenos se mueven, y varios viven en rutas con UUID que
no sobreviven a una reorganizacion del sitio.

Falla con codigo distinto de 0 si alguno no responde.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

DOCS = ["README.md", "docs", "notas"]
# Algunos servidores rechazan HEAD y responden bien a GET, asi que un fallo con HEAD se
# reintenta con GET antes de darlo por roto.
#
# Un 4xx significa que el recurso no esta: eso es un enlace roto y hace fallar el
# comando. Un 5xx o un error de conexion significa que el servidor tuvo un problema o
# nos esta bloqueando, y eso no dice nada sobre el enlace: se reporta como advertencia.
# Caso real: Geofabrik responde 200 desde el host y 502 desde dentro del contenedor,
# porque rechaza la salida de red de Docker.
CABECERAS = {"User-Agent": "matriz-distancias-comunales/1.0 (verificador de enlaces)"}
PATRON = re.compile(r"https?://[^\s)\"'<>\]]+")
# Los bloques de codigo llevan URLs de ejemplo, no referencias: una base que se usa
# concatenada con un nombre de archivo no resuelve por si sola, y no es un enlace roto.
BLOQUE_CODIGO = re.compile(r"```.*?```", re.DOTALL)


def urls_de(ruta: Path):
    texto = BLOQUE_CODIGO.sub("", ruta.read_text(encoding="utf-8"))
    for u in PATRON.findall(texto):
        yield u.rstrip(".,;:")


def estado(url: str) -> tuple[int, str]:
    """HEAD primero; si falla, GET. Algunos servidores rechazan HEAD o son lentos."""
    ultimo = (0, "sin intento")
    for metodo, espera in (("HEAD", 30), ("GET", 90), ("GET", 90)):
        try:
            r = requests.request(
                metodo, url, headers=CABECERAS, timeout=espera,
                allow_redirects=True, stream=(metodo == "GET"),
            )
            if metodo == "GET":
                r.close()
            if r.status_code < 400:
                return r.status_code, metodo
            ultimo = (r.status_code, metodo)
        except requests.RequestException as e:
            ultimo = (0, type(e).__name__)
    return ultimo


def main():
    encontradas: dict[str, set[str]] = {}
    for entrada in DOCS:
        p = Path(entrada)
        archivos = [p] if p.is_file() else sorted(p.rglob("*.md"))
        for a in archivos:
            for u in urls_de(a):
                encontradas.setdefault(u, set()).add(str(a))

    rotas = []
    for url in sorted(encontradas):
        code, via = estado(url)
        ok = 0 < code < 400
        print(f"  [{code if code else 'ERR':>3}] {'ok ' if ok else 'ROTO'} {url}")
        if not ok:
            rotas.append((url, code, via, sorted(encontradas[url])))

    print(f"\n{len(encontradas)} enlaces revisados, {len(rotas)} rotos")
    if rotas:
        print()
        for url, code, via, archivos in rotas:
            print(f"  {url}\n    {code} ({via})  en: {', '.join(archivos)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
