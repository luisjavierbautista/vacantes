# -*- coding: utf-8 -*-
"""<id>/data.json → <id>/index.html

    python3 tools/render.py --busqueda comp-ben

NO genera la página: reemplaza los bloques marcados dentro del HTML. El diseño
y el JavaScript se editan a mano en el HTML y este script no los toca nunca.

El párrafo de resumen se REESCRIBE ENTERO en cada corrida. Si solo se agregara,
en tres días la página estaría contando una historia que sus datos desmienten.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comun as c


def reemplazar(html, marca, contenido):
    """Sustituye lo que hay entre «=== MARCA: INICIO … === » y «=== MARCA: FIN ===»."""
    patron = re.compile(
        r"(===\s*" + marca + r":\s*INICIO.*?===\s*(?:-->|\*/))(.*?)(\s*/\*\s*===\s*"
        + marca + r":\s*FIN\s*===|\s*<!--\s*===\s*" + marca + r":\s*FIN\s*===)",
        re.S)
    if not patron.search(html):
        raise SystemExit(f"No encontré el bloque «{marca}» en el HTML.")
    return patron.sub(lambda m: m.group(1) + "\n" + contenido + m.group(3), html)


def pesos(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def texto_resumen(d, bus):
    """Dos o tres frases, sin relleno, reescritas enteras cada corrida."""
    vig = d["vigentes"]
    nuevas = [a for a in vig if a.get("nueva")]
    caidas = d.get("caidas", [])
    con_salario = [a for a in vig if a.get("salario")]
    sobre_piso = [a for a in con_salario
                  if (a["salario"].get("max") or 0) >= bus["salario"]["piso"]]
    frases = []

    if not vig:
        return ("<p>Hoy no quedó ninguna vacante en pie. Revisa la nota de método: "
                "puede que una fuente haya cambiado su HTML.</p>")

    # 1 · qué cambió
    if nuevas:
        frases.append(f"Hoy entraron <b>{len(nuevas)}</b> vacante"
                      f"{'s' if len(nuevas) != 1 else ''} nueva"
                      f"{'s' if len(nuevas) != 1 else ''} y quedan "
                      f"<b>{len(vig)}</b> vigentes.")
    else:
        frases.append(f"Hoy no entró ninguna vacante nueva; siguen en pie las "
                      f"<b>{len(vig)}</b> de ayer.")
    if caidas:
        recientes = [a for a in caidas if a.get("desaparecio") == d["corrida"]]
        if recientes:
                frases.append(f"Se cayó {len(recientes)}." if len(recientes) == 1
                          else f"Se cayeron {len(recientes)}.")

    # 2 · la mejor, y por qué
    mejor = max(vig, key=lambda a: a["puntaje"])
    razones = [x["concepto"] for x in mejor.get("desglose", []) if x["puntos"] > 0]
    quien = ("una empresa que no se revela" if mejor.get("empresa_anonima")
             else f"<b>{mejor['empresa']}</b>")
    frase = (f"La mejor por puntaje es <b>{mejor['cargo']}</b> en {quien}"
             f" ({mejor['puntaje']:+d})")
    if razones:
        frase += ": " + ", ".join(r.lower() for r in razones[:3])
    frases.append(frase + ".")

    # 3 · el estado del dato, que es lo que más engaña
    sin_salario = len(vig) - len(con_salario)
    if sin_salario:
        frases.append(f"{sin_salario} de {len(vig)} no publican salario — eso no es "
                      f"un cero, es un dato que el aviso calla.")
    if sobre_piso:
        n = len(sobre_piso)
        frases.append(f"De las {len(con_salario)} que sí lo publican, "
                      f"<b>{n}</b> {'cruza' if n == 1 else 'cruzan'} tu piso de "
                      f"{pesos(bus['salario']['piso'])}.")
    elif con_salario:
        frases.append(f"Ninguna de las {len(con_salario)} que publican salario llega a "
                      f"{pesos(bus['salario']['piso'])}; el publicado casi nunca es el "
                      f"que se negocia, así que se muestran igual.")

    mitad = 2 if len(frases) > 3 else len(frases)
    return ("<p>" + " ".join(frases[:mitad]) + "</p>"
            + ("<p>" + " ".join(frases[mitad:]) + "</p>" if frases[mitad:] else ""))


def bloque_recuadros(d, bus):
    vig = d["vigentes"]
    piso = bus["salario"]["piso"]
    nuevas = sum(1 for a in vig if a.get("nueva"))
    con_sal = [a for a in vig if a.get("salario")]
    # De las que publican salario, cuántas llegan de verdad. La brecha entre
    # los dos números dice más que cualquiera de los dos por separado.
    cruzan = sum(1 for a in con_sal
                 if (a["salario"].get("moneda") or "COP") == "COP"
                 and (a["salario"].get("max") or 0) >= piso)
    tarjetas = [
        (len(vig), "vigentes hoy", False),
        (nuevas, "nuevas desde ayer", nuevas > 0),
        (len(con_sal), "con salario publicado", False),
        (cruzan, f"cruzan tu piso de {pesos(piso)}", False),
    ]
    filas = []
    for n, rot, destaca in tarjetas:
        filas.append(f'  <div class="recuadro{" destaca" if destaca else ""}">'
                     f'<div class="cifra">{n}</div>'
                     f'<div class="rotulo">{rot}</div></div>')
    return '<div class="recuadros" id="recuadros">\n' + "\n".join(filas) + "\n</div>"


def bloque_encabezado(d, bus):
    fuentes_ok = [k for k, v in d["fuentes"].items() if v["avisos"]]
    vacias = len(d["fuentes"]) - len(fuentes_ok)
    txt = (f'Corrida del <b>{d["corrida_hora"]}</b> · {d["avisos_recogidos"]} avisos '
           f'recogidos · {len(d["fuentes"])} fuentes consultadas, '
           f'{len(fuentes_ok)} con resultados ({", ".join(fuentes_ok)})'
           + (f', {vacias} sin nada hoy' if vacias else "")
           + f' · {d["descartados"]} descartados por criterio')
    return f'<p class="meta-corrida" id="meta-corrida">{txt}</p>'


def bloque_datos(d, bus):
    vig = d["vigentes"]
    # Escala FIJA: una escala que se recalcula cada día hace incomparable la
    # página de ayer, y un solo aviso con el balde «21M a 50M» aplasta al resto.
    techo = bus["umbrales"]["techo_riel_cop"]

    cfg = {
        "piso": bus["salario"]["piso"],
        "deseable": bus["salario"]["deseable"],
        "techo_riel": techo,
        "max_filtros": bus["umbrales"]["max_empresas_visibles_en_filtro"],
        "contratos_marcados": bus["contrato"]["mostrados_marcados"],
    }
    campos = ("id", "cargo", "empresa", "empresa_anonima", "ciudad", "modalidad",
              "modalidad_literal", "modalidad_por_confirmar", "salario", "publicado",
              "publicado_literal", "vigente_hasta", "contrato", "fuentes", "inc",
              "deducidos", "marcas", "puntaje", "desglose", "nueva", "republicaciones",
              "cargo_original", "pais", "visto_desde", "titulos_alternos")
    def limpiar(a):
        o = {k: a[k] for k in campos if a.get(k) not in (None, [], "")}
        legible = c.titulo_legible(a.get("cargo"))
        if legible != a.get("cargo"):
            o["cargo"] = legible
            o["cargo_original"] = a["cargo"]
        return o

    gone = [limpiar(a) | {"desaparecio": a.get("desaparecio"),
                          "visto_desde": a.get("visto_desde")}
            for a in d.get("caidas", [])]
    fuentes = {
        "consultadas": d["fuentes"],
        "descartadas": bus["fuentes"]["_descartadas"],
        "nota_fija": bus["textos"]["nota_metodo_fija"],
    }
    j = lambda o: json.dumps(o, ensure_ascii=False)
    return ("var CONFIG = " + j(cfg) + ";\n"
            + "var DATA = " + j([limpiar(a) for a in vig]) + ";\n"
            + "var GONE = " + j(gone) + ";\n"
            + "var FUENTES = " + j(fuentes) + ";")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--busqueda", required=True)
    args = p.parse_args()

    bus = c.cargar_busqueda(args.busqueda)
    dir_b = c.dir_busqueda(args.busqueda)
    ruta_datos = os.path.join(dir_b, "data.json")
    ruta_html = os.path.join(dir_b, "index.html")
    if not os.path.exists(ruta_datos):
        raise SystemExit(f"Falta {ruta_datos}. Corre primero barrido.py.")

    with open(ruta_datos, encoding="utf-8") as f:
        d = json.load(f)
    with open(ruta_html, encoding="utf-8") as f:
        html = f.read()

    html = reemplazar(html, "DATOS", bloque_datos(d, bus))
    html = reemplazar(html, "ENCABEZADO", bloque_encabezado(d, bus))
    html = reemplazar(html, "RECUADROS", bloque_recuadros(d, bus))
    html = reemplazar(html, "RESUMEN",
                      '<div class="resumen" id="resumen">' + texto_resumen(d, bus) + "</div>")

    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(html)

    # Freno 3 de la sección 11: las fichas del HTML deben cuadrar con los avisos.
    en_html = len(json.loads(re.search(r"var DATA = (\[.*?\]);\n", html, re.S).group(1)))
    if en_html != len(d["vigentes"]):
        raise SystemExit(f"DESCUADRE: {en_html} fichas en el HTML "
                         f"contra {len(d['vigentes'])} avisos en data.json")
    print(f"{ruta_html} · {en_html} fichas · {len(d.get('caidas', []))} caídas")


if __name__ == "__main__":
    main()
