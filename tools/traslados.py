# -*- coding: utf-8 -*-
"""Tiempos de viaje casa→oficina. SOLO donde hay dirección real.

    python3 tools/traslados.py --busqueda comp-ben

Casi ningún aviso publica dirección. Este script no inventa un punto en el mapa
ni estima un tiempo: si no hay dirección, no hay traslado, y lo dice.

Sin llave no falla: deja los campos que dependen de ella como «pendiente».
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comun as c


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--busqueda", required=True)
    args = p.parse_args()

    bus = c.cargar_busqueda(args.busqueda)
    ruta = os.path.join(c.dir_busqueda(args.busqueda), "data.json")
    if not os.path.exists(ruta):
        raise SystemExit(f"Falta {ruta}. Corre primero barrido.py.")
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)

    con_direccion = [a for a in d["vigentes"] if a.get("direccion")]
    print(f"{len(d['vigentes'])} vigentes · {len(con_direccion)} con dirección publicada")

    if not con_direccion:
        print("Ningún aviso publica dirección: no hay traslados que calcular y la\n"
              "página no lleva mapa. Un mapa con tres puntos de cuarenta vacantes engaña.")
        return

    base = bus["perfil"]["direccion_base"]
    llave = c.llave("LLAVE_RUTAS")
    if not llave:
        print("Sin LLAVE_RUTAS: los tiempos quedan marcados como «pendiente».")
        for a in con_direccion:
            a["traslado"] = {"estado": "pendiente", "motivo": "falta la llave del servicio"}
    else:
        # Aquí iría la llamada al servicio de rutas, con hora pico como referencia.
        # No se implementa a ciegas: se implementa el día que haya direcciones que
        # geocodificar y se pueda comprobar contra un caso real.
        print(f"Llave presente. Origen: {base['texto']} (vigente hasta {base['vigente_hasta']}).")
        for a in con_direccion:
            a["traslado"] = {"estado": "pendiente", "motivo": "servicio de rutas sin implementar"}

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"actualizado {ruta}")


if __name__ == "__main__":
    main()
