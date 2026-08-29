# -*- coding: utf-8 -*-
"""Chequeo previo al push. Devuelve 1 si algo no debe publicarse.

    python3 tools/chequeo.py --busqueda comp-ben

Busca credenciales por la FORMA de la llave, nunca por su texto literal: si el
patrón se escribiera completo aquí, este archivo se detectaría a sí mismo y el
chequeo fallaría siempre. Por eso los prefijos se arman por concatenación.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comun as c

# Prefijos partidos a propósito: así no aparecen enteros en el código.
FORMAS = [
    ("una llave de Google",  re.compile("AI" + "za" + r"[0-9A-Za-z_\-]{35}")),
    ("un token de OpenAI",  re.compile("sk" + "-" + r"[A-Za-z0-9]{20,}")),
    ("un token de GitHub",  re.compile("gh" + "p_" + r"[A-Za-z0-9]{30,}")),
    ("un token de Apify",   re.compile("apify" + "_api_" + r"[A-Za-z0-9]{20,}")),
    ("una llave de AWS",     re.compile("AKIA" + r"[0-9A-Z]{16}")),
    ("una cabecera de llave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# Datos personales que no pueden salir a un repo público.
PERSONALES = [
    ("un correo",   re.compile(r"[\w.\-]+@(?!example\.)[\w\-]+\.[a-z]{2,}", re.I)),
    ("un teléfono", re.compile(r"\b(?:\+57\s?)?3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b")),
]

# Lo que sí puede aparecer: el bot de GitHub, dominios de ejemplo y las
# arrobas de CSS/JSON-LD, que no son correos.
PERMITIDOS = re.compile(
    r"@users\.noreply\.github\.com|noreply@|@example\.|@fonts\.googleapis|"
    r"@fonts\.gstatic|@media|@type|@context|@keyframes|@font-face|@property")


def archivos_a_publicar():
    try:
        r = subprocess.run(["git", "ls-files", "-com", "--exclude-standard"],
                           cwd=c.RAIZ, capture_output=True, text=True, timeout=30)
        vistos = [x for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        vistos = []
    if not vistos:
        vistos = [os.path.relpath(p, c.RAIZ)
                  for p in glob.glob(os.path.join(c.RAIZ, "**", "*"), recursive=True)
                  if os.path.isfile(p)]
    return [v for v in vistos
            if not v.startswith((".git/", ".cache/")) and v != "postulaciones.json"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--busqueda", required=True)
    args = p.parse_args()

    problemas = []

    # 1 · credenciales y datos personales, por forma
    for rel in archivos_a_publicar():
        ruta = os.path.join(c.RAIZ, rel)
        try:
            with open(ruta, encoding="utf-8", errors="ignore") as f:
                texto = f.read()
        except OSError:
            continue
        for nombre, rx in FORMAS:
            if rx.search(texto):
                problemas.append(f"{rel}: parece contener {nombre}")
        for nombre, rx in PERSONALES:
            for m in rx.finditer(texto):
                # Se compara con el CONTEXTO, no con el fragmento: el propio
                # regex corta «…@users.noreply» antes de «.github.com» y la
                # lista de permitidos no llegaba a reconocerlo.
                ventana = texto[max(0, m.start() - 20):m.end() + 30]
                if not PERMITIDOS.search(ventana):
                    problemas.append(f"{rel}: parece contener {nombre} ({m.group(0)[:24]}…)")
                    break

    # 2 · postulaciones.json no puede estar rastreado
    r = subprocess.run(["git", "ls-files", "postulaciones.json"],
                       cwd=c.RAIZ, capture_output=True, text=True)
    if r.stdout.strip():
        problemas.append("postulaciones.json está rastreado por git: es privado, sácalo del índice")

    # 3 · las fichas del HTML deben cuadrar con los avisos
    dir_b = c.dir_busqueda(args.busqueda)
    datos = os.path.join(dir_b, "data.json")
    html = os.path.join(dir_b, "index.html")
    if os.path.exists(datos) and os.path.exists(html):
        d = json.load(open(datos, encoding="utf-8"))
        m = re.search(r"var DATA = (\[.*?\]);\n", open(html, encoding="utf-8").read(), re.S)
        n = len(json.loads(m.group(1))) if m else -1
        if n != len(d["vigentes"]):
            problemas.append(f"descuadre: {n} fichas en el HTML contra "
                             f"{len(d['vigentes'])} avisos en data.json")

    if problemas:
        print("NO PUBLICAR:")
        for x in problemas:
            print("  ·", x)
        return 1
    print("chequeo previo: todo en orden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
