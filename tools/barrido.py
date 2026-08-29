# -*- coding: utf-8 -*-
"""Recorre las fuentes de una búsqueda y escribe <id>/data.json.

    python3 tools/barrido.py --busqueda comp-ben --dry
    python3 tools/barrido.py --busqueda comp-ben --fuente elempleo --dry

Este script no sabe nada del contenido de la búsqueda: todo sale del JSON.
Con --dry imprime el resumen y NO escribe nada.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comun as c


# ──────────────────────────────────────────────────── criterios (leídos del JSON)

class Criterios:
    """Envuelve el JSON de la búsqueda. No decide nada por su cuenta."""

    # Cargos por debajo de jefatura. El perfil pide 10+ años y descarta
    # explícitamente «cualquier cargo bajo jefatura»: no es un castigo de
    # puntaje, es que el aviso no es para ella.
    BAJO_JEFATURA = re.compile(
        r"\b(auxiliar|asistente|practicante|aprendiz|pasante|becario|estudiante|"
        r"tecnico|tecnologo|operario|operador|junior|jr|trainee|intern|"
        r"analista|assistant|clerk|especialista junior)\b")

    # Un aviso entra al barrido por su TÍTULO, no por su cuerpo. Casi todo
    # aviso de ventas menciona «compensación variable» en el cuerpo; si el
    # cuerpo bastara para entrar, la página sería un tablero de vacantes
    # comerciales. El cuerpo se usa para PUNTUAR, no para incluir.
    TITULO_COMPENSACION = re.compile(
        r"\b(compensacion|compensaciones|compensation|total rewards|rewards|"
        r"reward|remuneracion|remuneration|retribucion|salarial|salariales|"
        r"c b|comp ben|payroll benefits|job evaluation|valoracion de cargos)\b")

    SENIORITY = re.compile(
        r"\b(gerente|jefe|director|directora|lider|leader|lead|head|manager|"
        r"coordinador|coordinadora|senior|sr|principal|superintendente|"
        r"subgerente|associate director|vp|vicepresidente|chief)\b")

    def __init__(self, bus):
        self.bus = bus
        self.objetivo = [c.normalizar(x) for x in bus["cargos"]["objetivo"]]
        self.secundarios = [c.normalizar(x) for x in bus["cargos"]["secundarios"]]
        self.excluidos = [c.normalizar(x) for x in bus["cargos"]["excluidos"]]
        self.tematicas = [c.normalizar(x) for x in bus["exclusiones_tematicas"]["patrones"]]
        self.palabras = [c.normalizar(x) for x in bus["palabras_cuerpo"]]
        self.vetadas = [c.normalizar_empresa(x) for x in bus["empresas"]["vetadas"]]
        self.euro = [c.normalizar_empresa(x) for x in bus["empresas"]["objetivo_europeas"]]
        self.latam = [c.normalizar_empresa(x) for x in bus["empresas"]["objetivo_latam"]]
        self.piso = bus["salario"]["piso"]

    # -- cargo --------------------------------------------------------------
    def es_objetivo(self, cargo):
        n = c.normalizar_cargo(cargo)
        return any(o in n for o in self.objetivo)

    def es_secundario(self, cargo):
        n = c.normalizar_cargo(cargo)
        return any(o in n for o in self.secundarios)

    def es_excluido(self, cargo):
        n = c.normalizar_cargo(cargo)
        return any(o in n for o in self.excluidos)

    def nivel(self, cargo):
        """«jefatura», «bajo» o «indeterminado». Lo indeterminado NO se descarta."""
        n = c.normalizar_cargo(cargo)
        if self.SENIORITY.search(n) and not self.BAJO_JEFATURA.search(n):
            return "jefatura"
        if self.BAJO_JEFATURA.search(n):
            # «Analista Senior» y «Coordinador Junior» son ambiguos: no se botan.
            return "indeterminado" if self.SENIORITY.search(n) else "bajo"
        return "indeterminado"

    def titulo_relevante(self, cargo):
        """¿El título dice, por sí solo, que esto es de compensación?"""
        n = c.normalizar_cargo(cargo)
        return bool(self.TITULO_COMPENSACION.search(n))

    def tema_excluido(self, texto):
        n = c.normalizar(texto)
        return [t for t in self.tematicas if t in n]

    def toca_compensacion(self, texto):
        """Palabras técnicas del cuerpo. Solo para puntuar (+12), nunca para incluir."""
        return c.contiene(texto, self.palabras)

    def empresa_vetada(self, empresa):
        n = c.normalizar_empresa(empresa)
        return bool(n) and any(v and v in n for v in self.vetadas)

    def origen_empresa(self, empresa):
        """«europea», «latam» o None. Solo por la lista objetivo; no adivina."""
        n = c.normalizar_empresa(empresa)
        if not n:
            return None
        if any(e and e in n for e in self.euro):
            return "europea"
        if any(e and e in n for e in self.latam):
            return "latam"
        return None


# ─────────────────────────────────────────────────────── forma común del aviso

def aviso(fuente, url, cargo, empresa, ciudad, **extra):
    """Crea un aviso con la forma común. `inc` lista lo que la fuente NO publicó."""
    a = {
        "cargo": c.limpiar_html(cargo),
        "empresa": c.limpiar_html(empresa),
        "empresa_anonima": c.empresa_es_anonima(empresa),
        "ciudad": c.limpiar_html(ciudad),
        "descripcion": extra.get("descripcion") or "",
        "salario": extra.get("salario"),
        "publicado": extra.get("publicado"),
        "vigente_hasta": extra.get("vigente_hasta"),
        "contrato": extra.get("contrato"),
        "agencia": extra.get("agencia"),
        "direccion": extra.get("direccion"),
        "lat": extra.get("lat"),
        "lon": extra.get("lon"),
        "id_fuente": extra.get("id_fuente"),
        "fuentes": [{"fuente": fuente, "url": url, "id_fuente": extra.get("id_fuente")}],
        "inc": [],
        "deducidos": [],
    }
    for campo in ("empresa", "ciudad", "salario", "publicado", "contrato", "descripcion"):
        if not a.get(campo):
            a["inc"].append(campo)
    return a


# ──────────────────────────────────────────────────────────── fuente: elempleo

def fuente_elempleo(desc, bus, cri, limites):
    """elempleo.com — landings por RUTA (las que publica su propio sitemap).

    NO se usa /busqueda?: su robots.txt lo prohíbe. Las landings por cargo y el
    área de RR.HH. son rutas normales y sí están permitidas.
    """
    cfg = bus["fuentes"]["elempleo"]
    avisos = []

    # 1. De los sitemaps salen las landings por cargo que interesan.
    landings = []
    for sm in cfg["sitemaps"]:
        xml = desc.pedir(sm)
        if not xml:
            c.log("  elempleo: sitemap no disponible", sm)
            continue
        for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
            slug = loc.rsplit("/", 1)[-1].replace("trabajo-", "").replace("-", " ")
            if cri.tema_excluido(slug):
                continue
            if cri.es_objetivo(slug) or cri.titulo_relevante(slug):
                landings.append(loc)
    landings = list(dict.fromkeys(landings))
    landings.insert(0, cfg["landing_area_rrhh"])
    landings = landings[: limites["landings"]]
    c.log(f"  elempleo: {len(landings)} landings por ruta")

    # 2. De cada landing salen enlaces a avisos. Se filtran POR EL SLUG antes de
    #    pedir el detalle: así no se gastan peticiones en avisos irrelevantes.
    enlaces = []
    for url in landings:
        html = desc.pedir(url)
        if not html:
            continue
        for ruta in re.findall(r'href="(/co/ofertas-trabajo/[^"#?]+)"', html):
            enlaces.append("https://www.elempleo.com" + ruta)
    enlaces = list(dict.fromkeys(enlaces))

    candidatos = []
    for e in enlaces:
        slug = e.rsplit("/", 1)[-1]
        slug = re.sub(r"-\d{6,}$", "", slug).replace("-", " ")
        if cri.tema_excluido(slug) and not cri.es_objetivo(slug):
            continue
        if cri.nivel(slug) == "bajo" and not cri.es_objetivo(slug):
            continue
        if cri.es_excluido(slug) and not cri.es_objetivo(slug):
            continue
        if cri.es_objetivo(slug) or cri.es_secundario(slug) or cri.titulo_relevante(slug):
            candidatos.append(e)
    c.log(f"  elempleo: {len(enlaces)} avisos vistos, {len(candidatos)} candidatos por título")

    # 3. Solo de los candidatos se pide el detalle, que trae el JSON-LD completo.
    for url in candidatos[: limites["detalles"]]:
        html = desc.pedir(url)
        if not html:
            continue
        for jp in c.extraer_jobpostings(html):
            org = (jp.get("hiringOrganization") or {}).get("name")
            loc = ((jp.get("jobLocation") or {}).get("address") or {})
            cuerpo = c.limpiar_html(jp.get("description"))
            ident = jp.get("identifier")
            avisos.append(aviso(
                "elempleo", url,
                jp.get("title"), org,
                loc.get("addressLocality") or loc.get("addressRegion"),
                descripcion=cuerpo,
                salario=c.salario_honesto(jp.get("baseSalary")),
                publicado=c.fecha_iso(jp.get("datePosted")),
                vigente_hasta=c.fecha_iso(jp.get("validThrough")),
                contrato=jp.get("employmentType"),
                direccion=loc.get("streetAddress"),
                id_fuente=(ident or {}).get("value") if isinstance(ident, dict) else ident,
            ))
    return avisos


# ───────────────────────────────────────────────────────── fuente: computrabajo

def fuente_computrabajo(desc, bus, cri, limites):
    """Computrabajo — listados por RUTA (/trabajo-de-*), que su robots permite.

    Las variantes con query (dis=, cont=, sal=…) están prohibidas: no se usan.
    El detalle publica JSON-LD JobPosting igual que elempleo, así que sirve el
    mismo parser. Ojo: escribe baseSalary.value = 0 cuando NO hay salario.
    """
    cfg = bus["fuentes"]["computrabajo"]
    base = cfg["base"]
    enlaces = []
    for url in cfg["listados"]:
        html = desc.pedir(url)
        if not html:
            continue
        # Computrabajo pega un ancla «#lc=ListOffers-…» a cada enlace: se recorta.
        for ruta in re.findall(r'href="(/ofertas-de-trabajo/[^"#?]+)[^"]*"', html):
            enlaces.append(base + ruta)
    enlaces = list(dict.fromkeys(enlaces))

    candidatos = []
    for e in enlaces:
        slug = e.rsplit("/", 1)[-1]
        slug = re.sub(r"^oferta-de-trabajo-de-", "", slug)
        slug = re.sub(r"-[0-9A-F]{24,}$", "", slug).replace("-", " ")
        if cri.tema_excluido(slug) and not cri.es_objetivo(slug):
            continue
        if cri.es_excluido(slug) and not cri.es_objetivo(slug):
            continue
        if cri.nivel(slug) == "bajo" and not cri.es_objetivo(slug):
            continue
        if cri.es_objetivo(slug) or cri.es_secundario(slug) or cri.titulo_relevante(slug):
            candidatos.append(e)
    c.log(f"  computrabajo: {len(enlaces)} avisos vistos, {len(candidatos)} candidatos")

    avisos = []
    for url in candidatos[: limites["detalles"]]:
        html = desc.pedir(url)
        if not html:
            continue
        for jp in c.extraer_jobpostings(html):
            org = (jp.get("hiringOrganization") or {}).get("name")
            loc = ((jp.get("jobLocation") or {}).get("address") or {})
            ident = jp.get("identifier")
            avisos.append(aviso(
                "computrabajo", jp.get("url") or url,
                jp.get("title"), org,
                loc.get("addressLocality") or loc.get("addressRegion"),
                descripcion=c.limpiar_html(jp.get("description")),
                salario=c.salario_honesto(jp.get("baseSalary")),
                publicado=c.fecha_iso(jp.get("datePosted")),
                vigente_hasta=c.fecha_iso(jp.get("validThrough")),
                contrato=jp.get("employmentType"),
                id_fuente=(ident or {}).get("value") if isinstance(ident, dict) else ident,
            ))
    return avisos


# ────────────────────────────────────────────────────────────── fuente: workday

# Workday escribe la ubicación con su propia jerga: «COL - Office - Edificio
# Calle 127», «COL - Plant - Tocancipá». normalizar_ciudad no tiene por qué
# saber eso; se traduce aquí, que es donde se sabe que COL es Colombia.
_WD_LUGAR = re.compile(r"^([A-Z]{2,3})\s*-\s*\w+\s*-\s*(.+)$")


# Cuando la vacante está en varias sedes, Workday escribe «2 Locations» /
# «Ubicaciones: 2». Eso no es una ciudad: es la ausencia de una ciudad.
_WD_VARIAS = re.compile(r"^(\d+\s+locations?|ubicaciones?\s*:?\s*\d+)$", re.I)


def _wd_ciudad(texto):
    t = (texto or "").strip()
    if _WD_VARIAS.match(t):
        return None
    m = _WD_LUGAR.match(t)
    if m:
        return m.group(2).strip()
    return t


def fuente_workday(desc, bus, cri, limites):
    """Portales Workday de las empresas objetivo — la fuente primaria.

    Sin intermediarios, sin avisos repetidos y sin reclutadores que escondan el
    nombre de la empresa. Limitación real: el listado no trae descripción ni
    salario, y postedOn es relativo («Posted 30+ Days Ago»), así que la fecha
    exacta queda SIN DATO salvo que el detalle la publique.
    """
    cfg = bus["fuentes"]["workday"]
    avisos = []
    for t in cfg["tenants"]:
        tenant, wd = t["tenant"], t["wd"]
        for sitio in t["sitios"]:
            raiz = f"https://{tenant}.{wd}.myworkdayjobs.com"
            url = f"{raiz}/wday/cxs/{tenant}/{sitio}/jobs"
            vistos = 0
            for termino in ("compensation", "rewards", "compensacion"):
                d = desc.json(url, cuerpo={"limit": 20, "offset": 0,
                                           "searchText": termino, "appliedFacets": {}})
                if not d:
                    continue
                for jp in d.get("jobPostings", []):
                    titulo = jp.get("title")
                    if cri.es_excluido(titulo) and not cri.es_objetivo(titulo):
                        continue
                    if cri.nivel(titulo) == "bajo" and not cri.es_objetivo(titulo):
                        continue
                    if not (cri.es_objetivo(titulo) or cri.es_secundario(titulo)
                            or cri.titulo_relevante(titulo)):
                        continue
                    ruta = jp.get("externalPath") or ""
                    a = aviso(
                        "workday", raiz + "/" + sitio + ruta.replace("/job/", "/job/"),
                        titulo, t["empresa"], _wd_ciudad(jp.get("locationsText")),
                        contrato=jp.get("timeType"),
                        id_fuente=ruta.rsplit("_", 1)[-1] if "_" in ruta else ruta,
                    )
                    # postedOn es texto relativo: no es una fecha y no se finge.
                    a["publicado_literal"] = jp.get("postedOn")
                    if jp.get("locationsText") and not a["ciudad"]:
                        a["ciudad_literal"] = jp.get("locationsText")
                    if "publicado" not in a["inc"]:
                        a["inc"].append("publicado")
                    a["inc"].append("descripcion") if "descripcion" not in a["inc"] else None
                    avisos.append(a)
                    vistos += 1
            if vistos:
                c.log(f"  workday {tenant}/{sitio}: {vistos} candidatos")
    return avisos


# ─────────────────────────────────────────────────────────── fuente: greenhouse

def fuente_greenhouse(desc, bus, cri, limites):
    cfg = bus["fuentes"]["greenhouse"]
    avisos = []
    for e in cfg["empresas"]:
        d = desc.json(f"https://boards-api.greenhouse.io/v1/boards/{e['slug']}/jobs")
        if not d:
            continue
        n = 0
        for jp in d.get("jobs", []):
            titulo = jp.get("title")
            if cri.es_excluido(titulo) and not cri.es_objetivo(titulo):
                continue
            if not (cri.es_objetivo(titulo) or cri.es_secundario(titulo)
                    or cri.titulo_relevante(titulo)):
                continue
            avisos.append(aviso(
                "greenhouse", jp.get("absolute_url"), titulo, e["empresa"],
                (jp.get("location") or {}).get("name"),
                publicado=c.fecha_iso((jp.get("updated_at") or "")[:10]),
                id_fuente=str(jp.get("id")),
            ))
            n += 1
        c.log(f"  greenhouse {e['slug']}: {len(d.get('jobs', []))} avisos, {n} candidatos")
    return avisos


# ──────────────────────────────────────────────────────────── fuente: arbeitnow

def fuente_arbeitnow(desc, bus, cri, limites):
    """Aporta poco para este perfil, pero es gratis. Filtro estricto por título."""
    d = desc.json(bus["fuentes"]["arbeitnow"]["url"])
    if not d:
        return []
    avisos = []
    for jp in d.get("data", []):
        titulo = jp.get("title")
        if not (cri.es_objetivo(titulo) or cri.titulo_relevante(titulo)):
            continue
        if cri.es_excluido(titulo) and not cri.es_objetivo(titulo):
            continue
        a = aviso("arbeitnow", jp.get("url"), titulo, jp.get("company_name"),
                  jp.get("location"),
                  descripcion=c.limpiar_html(jp.get("description")),
                  id_fuente=jp.get("slug"))
        if jp.get("remote"):
            a["modalidad_fuente"] = "remoto"
        avisos.append(a)
    c.log(f"  arbeitnow: {len(d.get('data', []))} avisos, {len(avisos)} candidatos")
    return avisos


# ──────────────────────────────────────────────── fuente: LinkedIn vía Apify

def fuente_apify_linkedin(desc, bus, cri, limites):
    """LinkedIn a través de Apify, que es un intermediario comercial.

    LinkedIn no se consulta directo: sus condiciones lo prohíben. Si el actor
    pidiera cookie li_at, usuario/contraseña o «tu sesión», no se usa y punto.
    Se piden VACANTES: nunca perfiles, contactos ni datos de reclutadores.
    Si falla o se acaba el crédito, el barrido sigue y lo dice en el reporte.
    """
    cfg = bus["fuentes"]["apify_linkedin"]
    token = c.llave("APIFY_TOKEN")
    if not token:
        c.log("  apify: sin APIFY_TOKEN, se salta (los demás siguen)")
        desc.fallos.append(("apify_linkedin", "sin APIFY_TOKEN"))
        return []

    entrada = dict(cfg["entrada"])
    entrada["limit"] = min(entrada.get("limit", 100), cfg["max_items"])
    url = cfg["endpoint"].format(actor=cfg["actor"]) + f"?token={token}"

    items = desc.json(url, cuerpo=entrada, saltar_robots=True)
    if items is None:
        c.log("  apify: la corrida falló; el barrido sigue con las demás fuentes")
        return []
    costo = len(items) * cfg["costo_usd_por_aviso"]
    c.log(f"  apify: {len(items)} avisos, costo aprox US${costo:.2f}")

    avisos = []
    for jp in items:
        titulo = jp.get("title")
        if cri.tema_excluido(titulo) and not cri.es_objetivo(titulo):
            continue
        if cri.es_excluido(titulo) and not cri.es_objetivo(titulo):
            continue
        if cri.nivel(titulo) == "bajo" and not cri.es_objetivo(titulo):
            continue
        if not (cri.es_objetivo(titulo) or cri.es_secundario(titulo)
                or cri.titulo_relevante(titulo)):
            continue
        ciudades = jp.get("cities_derived") or jp.get("locations_derived") or []
        lats = jp.get("lats_derived") or []
        lons = jp.get("lngs_derived") or []
        sal = None
        if jp.get("ai_salary_min_value") or jp.get("ai_salary_max_value"):
            sal = {"min": jp.get("ai_salary_min_value"),
                   "max": jp.get("ai_salary_max_value"),
                   "moneda": jp.get("ai_salary_currency"),
                   "periodo": (jp.get("ai_salary_unit_text") or "").upper() or None}
        a = aviso(
            "linkedin", jp.get("url"), titulo, jp.get("organization"),
            (ciudades[0] if ciudades else None),
            descripcion=jp.get("description_text") or "",
            salario=sal,
            publicado=c.fecha_iso((jp.get("date_posted") or "")[:10]),
            vigente_hasta=c.fecha_iso((jp.get("date_valid_through") or "")[:10]),
            contrato=jp.get("employment_type"),
            lat=(lats[0] if lats else None),
            lon=(lons[0] if lons else None),
            id_fuente=str(jp.get("linkedin_id") or jp.get("id") or ""),
        )
        # Campos que el intermediario DEDUCE, no lee. Van marcados como tales.
        arreglo = jp.get("ai_work_arrangement")
        if arreglo:
            a["modalidad_fuente"] = arreglo
            a["deducidos"].append("modalidad")
        if sal:
            a["deducidos"].append("salario")
        if jp.get("org_linkedin_recruitment_agency_derived"):
            a["agencia"] = jp.get("organization")
            a["empresa_anonima"] = True
            a["deducidos"].append("agencia")
        a["empleados"] = jp.get("org_linkedin_headcount")
        a["sede"] = jp.get("org_linkedin_headquarters")
        avisos.append(a)
    c.log(f"  apify: {len(avisos)} candidatos tras filtrar por título")
    return avisos


FUENTES = {
    "elempleo": fuente_elempleo,
    "computrabajo": fuente_computrabajo,
    "workday": fuente_workday,
    "greenhouse": fuente_greenhouse,
    "arbeitnow": fuente_arbeitnow,
    "apify_linkedin": fuente_apify_linkedin,
}


def geografia(a, cri):
    """¿El lugar del aviso sirve? Devuelve (sirve, motivo, marca).

    El perfil acepta Bogotá si es presencial o híbrido, y cualquier país si es
    remoto. Una ciudad DESCONOCIDA no se descarta: desconocido no es «no».
    """
    canon = c.normalizar_ciudad(a["ciudad"])
    remoto = (a.get("modalidad") == "remoto"
              or a.get("modalidad_fuente") in ("remoto", "Remote", "remote")
              or canon == "remoto")
    if not canon:
        return True, None, "ciudad sin publicar"
    if canon in ("bogota", "bogota alrededores", "colombia", "remoto"):
        return True, None, None
    if remoto:
        # Remoto fuera de Colombia: puede o no contratar desde aquí. No se
        # esconde y no se afirma lo que no se sabe.
        return True, None, "remoto fuera de Colombia, contratación por confirmar"
    return False, f"presencial fuera de Bogotá ({canon})", None


# ─────────────────────────────────────────────────────────────── deduplicación

def deduplicar(avisos):
    """Colapsa por identidad. La misma vacante sale en tres portales.

    Se conserva la que MÁS informa, se guardan TODOS los enlaces, se conserva la
    fecha de publicación MÁS ANTIGUA y se cuenta cuántas veces se republicó.
    Si la fuente primaria (un ATS) da un id estable, ese manda sobre la
    heurística: dos vacantes reales del mismo cargo no se fusionan.
    """
    def riqueza(a):
        """Cuántos campos publica de verdad. Más alto = más informativo."""
        n = 0
        n += 3 if a.get("salario") else 0
        n += 2 if a.get("publicado") else 0
        n += 2 if not a.get("empresa_anonima") else 0
        n += 1 if a.get("descripcion") else 0
        n += 1 if a.get("modalidad") else 0
        n += 1 if a.get("vigente_hasta") else 0
        return n

    grupos = {}
    for a in avisos:
        base = c.identidad(a["empresa"], a["cargo"], a["ciudad"], a.get("agencia"))
        # Un id estable del ATS distingue dos vacantes reales con el mismo cargo.
        if a["fuentes"][0]["fuente"] in ("workday", "greenhouse") and a.get("id_fuente"):
            base += "#" + str(a["id_fuente"])
        # Dos avisos «empresa no revelada» con el mismo cargo y ciudad NO son la
        # misma vacante: son dos empleadores distintos que ocultan su nombre. Sin
        # agencia que los distinga, se separan por salario y fecha. Preferimos
        # mostrar dos veces una vacante a esconder una: mostrarla de más se ve y
        # se corrige, esconderla no se nota nunca.
        elif a.get("empresa_anonima") and not a.get("agencia"):
            sal = a.get("salario") or {}
            base += "#anon:{}-{}-{}".format(
                int(sal.get("min") or 0), int(sal.get("max") or 0), a.get("publicado") or "")
        grupos.setdefault(base, []).append(a)

    salida = []
    for ident, grupo in grupos.items():
        grupo.sort(key=riqueza, reverse=True)
        mejor = dict(grupo[0])
        mejor["id"] = ident
        # todos los enlaces, para poder postularse por donde convenga
        vistos, fuentes = set(), []
        for a in grupo:
            for f in a["fuentes"]:
                if f["url"] and f["url"] not in vistos:
                    vistos.add(f["url"])
                    fuentes.append(f)
        mejor["fuentes"] = fuentes
        fechas = [a["publicado"] for a in grupo if a.get("publicado")]
        mejor["publicado"] = min(fechas) if fechas else None
        # Los campos que al mejor le faltan pero otro sí publica, se rescatan.
        for campo in ("salario", "descripcion", "vigente_hasta", "contrato",
                      "lat", "lon", "sede", "empleados"):
            if not mejor.get(campo):
                for a in grupo:
                    if a.get(campo):
                        mejor[campo] = a[campo]
                        break
        mejor["inc"] = [k for k in ("empresa", "ciudad", "salario", "publicado",
                                    "contrato", "descripcion", "modalidad")
                        if not mejor.get(k)]
        mejor["duplicados_hoy"] = len(grupo)
        if mejor.get("empresa_anonima") and not mejor.get("agencia"):
            mejor.setdefault("marcas", []).append(
                "empresa no revelada: puede estar repetida")
        salida.append(mejor)
    return salida


# Palabras que no distinguen un cargo de otro y solo inflan el parecido.
_VACIAS = {"de", "del", "la", "el", "los", "las", "en", "y", "e", "para", "con",
           "a", "al", "por", "and", "or", "of", "the", "to", "rrhh", "rh",
           "recursos", "humanos", "hr", "gestion", "talento", "humano"}


def _palabras_cargo(cargo):
    return {p for p in c.normalizar_cargo(cargo).split() if p not in _VACIAS and len(p) > 1}


def fusionar_similares(avisos, umbral, cri):
    """Segunda pasada: fusiona el MISMO puesto escrito con otro orden de palabras.

    «Total Rewards Lead / Líder de Compensación y Beneficios» y «Líder en
    Beneficios y Compensación / Total Rewards» son el mismo aviso de Manpower en
    dos portales, pero la identidad exacta no los colapsa.

    Tres frenos, porque fusionar de más ESCONDE una vacante:
      · solo entre empresas con nombre conocido — dos «empresa no revelada»
        parecidas pueden ser dos empleadores distintos;
      · solo dentro de la misma ciudad;
      · nunca si las dos traen id estable del ATS y son distintos: ahí manda el id;
      · nunca si una cae en una exclusión temática y la otra no — «Director de
        Compensación» y «Director de Compensación Ambiental» comparten 0.67 de
        las palabras y son cosas distintas;
      · nunca entre niveles opuestos: un Gerente no se fusiona con un Auxiliar.
    """
    fusiones = []
    salida = list(avisos)
    i = 0
    while i < len(salida):
        j = i + 1
        while j < len(salida):
            a, b = salida[i], salida[j]
            if (a.get("empresa_anonima") or b.get("empresa_anonima")
                    or not a["empresa"] or not b["empresa"]
                    or c.normalizar_empresa(a["empresa"]) != c.normalizar_empresa(b["empresa"])
                    or c.normalizar_ciudad(a["ciudad"]) != c.normalizar_ciudad(b["ciudad"])):
                j += 1
                continue
            if (a.get("id_fuente") and b.get("id_fuente")
                    and a["id_fuente"] != b["id_fuente"]
                    and a["fuentes"][0]["fuente"] == b["fuentes"][0]["fuente"]):
                j += 1
                continue
            if bool(cri.tema_excluido(a["cargo"])) != bool(cri.tema_excluido(b["cargo"])):
                j += 1
                continue
            if {cri.nivel(a["cargo"]), cri.nivel(b["cargo"])} == {"jefatura", "bajo"}:
                j += 1
                continue
            pa, pb = _palabras_cargo(a["cargo"]), _palabras_cargo(b["cargo"])
            if not pa or not pb:
                j += 1
                continue
            jaccard = len(pa & pb) / len(pa | pb)
            if jaccard < umbral:
                j += 1
                continue
            # se queda el que más informa; el otro aporta sus enlaces
            if len(b.get("fuentes", [])) and (
                    (b.get("salario") and not a.get("salario"))
                    or (b.get("descripcion") and not a.get("descripcion"))):
                a, b = b, a
                salida[i] = a
            urls = {f["url"] for f in a["fuentes"]}
            a["fuentes"] += [f for f in b["fuentes"] if f["url"] not in urls]
            for campo in ("salario", "descripcion", "vigente_hasta", "contrato",
                          "lat", "lon", "sede", "empleados"):
                if not a.get(campo) and b.get(campo):
                    a[campo] = b[campo]
            fechas = [x for x in (a.get("publicado"), b.get("publicado")) if x]
            a["publicado"] = min(fechas) if fechas else None
            a["inc"] = [k for k in ("empresa", "ciudad", "salario", "publicado",
                                    "contrato", "descripcion", "modalidad")
                        if not a.get(k)]
            a.setdefault("titulos_alternos", []).append(b["cargo"])
            fusiones.append((a["cargo"], b["cargo"], round(jaccard, 2)))
            salida.pop(j)
        i += 1
    return salida, fusiones


# ──────────────────────────────────────────────────────────────────── puntaje

_EUROPA = re.compile(r"\b(spain|espana|france|francia|germany|alemania|italy|italia|"
                     r"netherlands|holanda|belgium|belgica|switzerland|suiza|sweden|"
                     r"denmark|dinamarca|norway|finland|austria|portugal|ireland|"
                     r"irlanda|united kingdom|england|london|madrid|paris|berlin|"
                     r"amsterdam|zurich|basel|copenhagen|stockholm|milan|munich)\b", re.I)
_LATAM = re.compile(r"\b(colombia|mexico|brazil|brasil|argentina|chile|peru|"
                    r"uruguay|panama|ecuador|bogota|sao paulo|buenos aires|"
                    r"santiago|lima|monterrey)\b", re.I)
_EEUU = re.compile(r"\b(united states|usa|u s a|new york|california|texas|"
                   r"massachusetts|illinois|new jersey|chicago|boston)\b", re.I)
_OTRO_IDIOMA = re.compile(r"\b(portugues|portuguese|frances|french|"
                          r"idioma portugues|nivel de frances)\b")


def puntuar(a, cri, bus):
    """Puntaje explicable. Solo ORDENA: nada se esconde por puntaje bajo.

    Si un componente no se puede evaluar porque el dato no está, vale CERO y se
    dice. Nunca se penaliza la falta de dato: eso castigaría a los avisos
    incompletos, que son la mayoría, y escondería buenas vacantes.
    """
    P = bus["pesos"]
    piso = bus["salario"]["piso"]
    cuerpo = a.get("descripcion") or ""
    d = []

    def suma(concepto, puntos, nota=""):
        d.append({"concepto": concepto, "puntos": puntos, "nota": nota})

    # cargo
    if cri.es_objetivo(a["cargo"]):
        suma("cargo objetivo de compensación", P["cargo_objetivo"], a["cargo"])
    elif cri.es_secundario(a["cargo"]):
        suma("cargo secundario de RR.HH.", 0, "solo suma si el cuerpo habla de compensación")
    if cri.es_excluido(a["cargo"]):
        suma("cargo de ventas, desarrollo de negocio o selección",
             P["cargo_de_ventas_o_seleccion"], a["cargo"])

    # origen de la empresa
    origen = cri.origen_empresa(a["empresa"])
    sede = a.get("sede") or ""
    if not origen and sede:
        if _EUROPA.search(sede):
            origen = "europea"
        elif _LATAM.search(sede):
            origen = "latam"
    if origen in ("europea", "latam"):
        suma(f"multinacional {origen}", P["multinacional_euro_latam"], sede or "por la lista objetivo")
    elif sede and _EEUU.search(sede):
        suma("multinacional estadounidense", P["multinacional_estadounidense"], sede)
    elif a.get("empresa_anonima"):
        suma("origen de la empresa", 0, "el aviso no revela la empresa: no suma ni resta")
    else:
        suma("origen de la empresa", 0, "no se pudo determinar: no suma ni resta")

    if cri.origen_empresa(a["empresa"]):
        suma("está en la lista de empresas objetivo", P["empresa_en_lista_objetivo"], a["empresa"])

    # modalidad
    if a.get("modalidad") == "remoto" and c.clasificar_modalidad("", cuerpo)[0] == "remoto":
        suma("remoto confirmado en el cuerpo del aviso",
             P["remoto_confirmado_en_cuerpo"], a.get("modalidad_literal") or "")
    elif not cuerpo:
        suma("modalidad remota", 0, "el aviso no publica cuerpo: no suma ni resta")

    # palabras técnicas
    tec = cri.toca_compensacion(cuerpo)
    if tec:
        suma("el cuerpo menciona técnica de compensación",
             P["palabras_tecnicas_en_cuerpo"], ", ".join(tec[:6]))
    elif not cuerpo:
        suma("técnica de compensación en el cuerpo", 0,
             "el aviso no publica cuerpo: no suma ni resta")

    # salario
    sal = a.get("salario")
    if not sal:
        suma("salario", 0, "sin salario publicado, no suma ni resta")
    else:
        tope = sal.get("max") or sal.get("min") or 0
        moneda = (sal.get("moneda") or "").upper()
        if moneda and moneda != "COP":
            suma("salario", 0, f"publicado en {moneda}: no se convierte ni se compara")
        elif tope >= piso:
            suma(f"salario publicado igual o sobre ${piso:,.0f}".replace(",", "."),
                 P["salario_publicado_sobre_piso"], f"{tope:,.0f} COP".replace(",", "."))
        else:
            suma(f"salario publicado por debajo de ${piso:,.0f}".replace(",", "."),
                 P["salario_publicado_bajo_piso"],
                 f"{tope:,.0f} COP — se muestra igual: el publicado casi nunca es el negociado"
                 .replace(",", "."))

    # frescura
    dias = c.dias_desde(a.get("publicado"))
    if dias is None:
        suma("fecha de publicación", 0,
             (a.get("publicado_literal") or "sin fecha publicada") + ": no suma ni resta")
    elif dias <= bus["umbrales"]["dias_para_considerar_reciente"]:
        suma("publicada hace menos de 3 días", P["publicada_hace_menos_de_3_dias"],
             f"hace {dias} día(s)")

    # idiomas
    otros = _OTRO_IDIOMA.findall(c.normalizar(cuerpo))
    if otros:
        suma("exige portugués o francés", P["exige_portugues_o_frances"], otros[0])

    # startup
    emp = a.get("empleados")
    if isinstance(emp, int) and emp and emp < 50:
        suma("empresa pequeña / etapa temprana", P["startup_etapa_temprana"],
             f"{emp} empleados")

    a["desglose"] = d
    a["puntaje"] = sum(x["puntos"] for x in d)
    return a


# ─────────────────────────────────────────────────────────── diferencial diario

def diferencial(hoy_avisos, anterior, olvido_dias=45):
    """nuevas · caídas · republicadas. Confundirlas hace postularse dos veces."""
    previos = {a["id"]: a for a in (anterior or {}).get("vigentes", [])}
    ids_hoy = {a["id"] for a in hoy_avisos}

    nuevas, republicadas = [], []
    for a in hoy_avisos:
        ant = previos.get(a["id"])
        if not ant:
            a["nueva"] = True
            a["visto_desde"] = c.hoy()
            a["republicaciones"] = 0
            nuevas.append(a["id"])
        else:
            a["nueva"] = False
            a["visto_desde"] = ant.get("visto_desde") or c.hoy()
            urls_ant = {f["url"] for f in ant.get("fuentes", [])}
            urls_hoy = {f["url"] for f in a["fuentes"]}
            a["republicaciones"] = ant.get("republicaciones", 0)
            if urls_hoy - urls_ant:
                a["republicaciones"] += 1
                republicadas.append(a["id"])
            # la fecha más antigua que se haya visto nunca
            if ant.get("publicado") and (not a.get("publicado")
                                         or ant["publicado"] < a["publicado"]):
                a["publicado"] = ant["publicado"]

    caidas = []
    for ident, ant in previos.items():
        if ident not in ids_hoy:
            ant = dict(ant)
            ant["desaparecio"] = c.hoy()
            ant["dias_publicada"] = (
                (c.dias_desde(ant.get("visto_desde")) or 0))
            caidas.append(ant)
    caidas.extend(a for a in (anterior or {}).get("caidas", [])
                  if a["id"] not in ids_hoy)
    vistas = set()
    caidas = [a for a in caidas if not (a["id"] in vistas or vistas.add(a["id"]))]
    # Se olvidan las viejas: si no, la lista crece para siempre y deja de decir
    # nada sobre cuánto dura abierta una vacante de este perfil.
    caidas = [a for a in caidas
              if (c.dias_desde(a.get("desaparecio")) or 0) <= olvido_dias]
    return nuevas, republicadas, caidas


def cruzar_postulaciones(avisos, caidas):
    """Lee postulaciones.json. NUNCA lo escribe, lo reordena ni lo borra.

    Si el script lo pisa, ella pierde semanas de trabajo. Solo se lee.
    """
    ruta = os.path.join(c.RAIZ, "postulaciones.json")
    if not os.path.exists(ruta):
        return {}, []
    with open(ruta, encoding="utf-8") as f:
        post = json.load(f)
    for a in avisos:
        if a["id"] in post:
            a["postulacion"] = post[a["id"]]
    # Una vacante con proceso en curso no se cae de la página aunque el aviso sí.
    en_curso = []
    for a in caidas:
        est = (post.get(a["id"]) or {}).get("estado")
        if est and est not in ("sin_ver", "descartada", "cerrada"):
            a["postulacion"] = post[a["id"]]
            en_curso.append(a)
    return post, en_curso


# ─────────────────────────────────────────────────────────────────── principal

def main():
    p = argparse.ArgumentParser(description="Barrido de vacantes")
    p.add_argument("--busqueda", required=True)
    p.add_argument("--fuente", action="append",
                   help="corre solo esta fuente (se puede repetir)")
    p.add_argument("--dry", action="store_true", help="no escribe nada")
    p.add_argument("--sin-cache", action="store_true")
    p.add_argument("--landings", type=int, default=25)
    p.add_argument("--detalles", type=int, default=120)
    args = p.parse_args()

    bus = c.cargar_busqueda(args.busqueda)
    cri = Criterios(bus)
    desc = c.Descargador(usar_cache=not args.sin_cache)
    limites = {"landings": args.landings, "detalles": args.detalles}

    pedidas = args.fuente or [n for n, f in bus["fuentes"].items()
                              if isinstance(f, dict) and f.get("activa")]
    crudos, por_fuente = [], {}
    for nombre in pedidas:
        if nombre not in FUENTES:
            c.log(f"(fuente «{nombre}» aún no implementada, se salta)")
            continue
        c.log(f"fuente: {nombre}")
        try:
            r = FUENTES[nombre](desc, bus, cri, limites)
        except Exception as e:
            c.log(f"  ERROR en {nombre}: {type(e).__name__}: {e}")
            por_fuente[nombre] = {"avisos": 0, "error": f"{type(e).__name__}: {e}"}
            continue
        por_fuente[nombre] = {"avisos": len(r), "error": None}
        crudos.extend(r)
        c.log(f"  {nombre}: {len(r)} avisos")

    # Descarte final con el cuerpo del aviso ya en mano.
    utiles, descartados = [], []
    for a in crudos:
        texto = f"{a['cargo']} {a['descripcion']}"
        mod, literal, choca = c.clasificar_modalidad(a["cargo"], a["descripcion"])
        a["modalidad"] = mod or a.get("modalidad_fuente")
        a["modalidad_literal"] = literal
        a["modalidad_por_confirmar"] = choca
        if not a["modalidad"]:
            a["inc"].append("modalidad")
        motivo = None
        if cri.empresa_vetada(a["empresa"]):
            motivo = "empresa vetada"
        elif cri.tema_excluido(a["cargo"]) and not cri.es_objetivo(a["cargo"]):
            motivo = f"tema ajeno ({cri.tema_excluido(a['cargo'])[0]})"
        elif cri.nivel(a["cargo"]) == "bajo" and not cri.es_objetivo(a["cargo"]):
            motivo = "por debajo de jefatura"
        elif cri.es_excluido(a["cargo"]) and not cri.es_objetivo(a["cargo"]):
            motivo = "cargo excluido (ventas / selección / nómina)"
        elif not (cri.es_objetivo(a["cargo"]) or cri.es_secundario(a["cargo"])
                  or cri.titulo_relevante(a["cargo"])):
            motivo = "el título no es de compensación"
        if not motivo:
            sirve, m_geo, marca = geografia(a, cri)
            if not sirve:
                motivo = m_geo
            elif marca:
                a.setdefault("marcas", []).append(marca)
        if motivo:
            descartados.append((a["cargo"], a["empresa"], motivo))
        else:
            utiles.append(a)

    # ── deduplicar, puntuar, comparar con ayer ───────────────────────────
    avisos = deduplicar(utiles)
    avisos, fusiones = fusionar_similares(
        avisos, bus["umbrales"]["similitud_para_fusionar"], cri)
    for a in avisos:
        puntuar(a, cri, bus)
    avisos.sort(key=lambda a: (-a["puntaje"], a["cargo"]))

    dir_b = c.dir_busqueda(args.busqueda)
    ruta_datos = os.path.join(dir_b, "data.json")
    anterior = None
    if os.path.exists(ruta_datos):
        with open(ruta_datos, encoding="utf-8") as f:
            anterior = json.load(f)

    nuevas, republicadas, caidas = diferencial(
        avisos, anterior, bus["umbrales"]["dias_para_olvidar_caidas"])
    post, en_curso = cruzar_postulaciones(avisos, caidas)

    # ── frenos de la sección 11 ──────────────────────────────────────────
    frenos = []
    antes = len((anterior or {}).get("vigentes", []))
    umbral = bus["umbrales"]["caida_relativa_para_no_publicar"]
    if antes and len(avisos) < antes * umbral:
        frenos.append(f"el barrido devolvió {len(avisos)} avisos frente a {antes} "
                      f"de la corrida anterior (menos del {umbral:.0%}): NO se publica")
    for nombre, d in por_fuente.items():
        # Que una fuente devuelva cero no detiene la publicación (regla 2 de la
        # sección 11), pero se dice. Salvo las que devolver cero es lo normal.
        if d["avisos"] == 0 and not bus["fuentes"].get(nombre, {}).get("cero_es_normal"):
            frenos.append(f"la fuente «{nombre}» devolvió cero — se publica igual, "
                          f"pero queda marcado en la página")

    # ── reporte ──────────────────────────────────────────────────────────
    print()
    print(f"══ {args.busqueda} · {len(avisos)} vigentes "
          f"({len(nuevas)} nuevas, {len(caidas)} caídas, "
          f"{len(republicadas)} republicadas) de {len(crudos)} recogidos")
    for n, d in por_fuente.items():
        print(f"   {n:16s} {d['avisos']:4d} avisos"
              + (f"  ERROR {d['error']}" if d["error"] else ""))
    if desc.fallos:
        print(f"\n   peticiones fallidas: {len(desc.fallos)}")
        for u, m in desc.fallos[:6]:
            print(f"     {m:28s} {u[:78]}")
    if fusiones:
        print(f"\n── fusionados por parecido ({len(fusiones)}):")
        for x, y, j in fusiones:
            print(f"   {j:.2f}  «{x[:44]}»\n         + «{y[:44]}»")
    if descartados:
        print(f"\n── descartados ({len(descartados)}):")
        for cargo, emp, m in descartados[:10]:
            print(f"   [{m}] {cargo[:52]} · {emp[:26]}")

    print(f"\n── vigentes, por puntaje:")
    for a in avisos:
        sal = a["salario"]
        s_txt = (f"{sal['max']:,.0f} {sal['moneda']}".replace(",", ".")
                 if sal else "sin salario")
        sello = "NUEVA " if a.get("nueva") else "      "
        print(f"   {a['puntaje']:+4d} {sello}{a['cargo'][:46]:46s} | "
              f"{(a['empresa'] or '¿?')[:22]:22s} | {c.normalizar_ciudad(a['ciudad'])[:14]:14s} | "
              f"{s_txt:22s} | {len(a['fuentes'])} fuente(s)")

    if caidas:
        print(f"\n── se cayeron ({len(caidas)}):")
        for a in caidas[:10]:
            print(f"   {a['cargo'][:52]:52s} | visto desde {a.get('visto_desde')} "
                  f"| desapareció {a.get('desaparecio')}")
    if en_curso:
        print(f"\n── ya no están publicadas, pero con proceso en curso ({len(en_curso)})")

    if frenos:
        print(f"\n⚠  FRENOS:")
        for f_ in frenos:
            print(f"   · {f_}")

    if args.dry:
        print("\n--dry: no se escribió nada.")
        return 0

    if frenos and any("NO se publica" in f_ for f_ in frenos):
        print("\nNo se escribe data.json. Revisa qué fuente se cayó.")
        return 1

    datos = {
        "busqueda": args.busqueda,
        "corrida": c.hoy(),
        "corrida_hora": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fuentes": por_fuente,
        "fallos": [{"url": u, "motivo": m} for u, m in desc.fallos],
        "avisos_recogidos": len(crudos),
        "descartados": len(descartados),
        "fusionados": [{"conservado": x, "absorbido": y, "parecido": j}
                       for x, y, j in fusiones],
        "nuevas": nuevas,
        "republicadas": republicadas,
        "vigentes": avisos,
        "caidas": caidas,
        "en_curso_no_publicadas": [a["id"] for a in en_curso],
        "avisos_pendientes": 0,
    }
    with open(ruta_datos, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    print(f"\nescrito {ruta_datos} · {len(avisos)} vigentes")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
