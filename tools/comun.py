# -*- coding: utf-8 -*-
"""Utilidades compartidas del buscador de vacantes.

Reglas que este módulo hace cumplir, para que ningún script pueda saltárselas:
  · Se lee y se respeta el robots.txt de cada host ANTES de pedir nada.
  · Una petición por segundo y por host, User-Agent real, caché en disco.
  · Un dato que la fuente no publica es «sin dato», nunca cero y nunca el mínimo.

Sin dependencias externas: solo biblioteca estándar.
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import date, datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CACHE = os.path.join(RAIZ, ".cache")
DIR_CONFIG = os.path.expanduser("~/.config/vacantes-comp-ben")

AGENTE = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

SEGUNDOS_ENTRE_PETICIONES = 1.0
VIDA_CACHE_HORAS = 6


# ─────────────────────────────────────────────────────────────── configuración

def cargar_busqueda(id_busqueda):
    """Lee busquedas/<id>.json. Es la única fuente de verdad de los criterios."""
    ruta = os.path.join(RAIZ, "busquedas", f"{id_busqueda}.json")
    if not os.path.exists(ruta):
        raise SystemExit(f"No existe la búsqueda «{id_busqueda}» ({ruta})")
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def dir_busqueda(id_busqueda):
    d = os.path.join(RAIZ, id_busqueda)
    os.makedirs(d, exist_ok=True)
    return d


def llave(nombre):
    """Lee una llave de la variable de entorno o de ~/.config/<proyecto>/.

    Devuelve None si no está. Quien la use debe seguir funcionando sin ella,
    dejando marcados como «pendiente» los campos que dependan de la llave.
    """
    if os.environ.get(nombre):
        return os.environ[nombre].strip()
    for archivo in os.listdir(DIR_CONFIG) if os.path.isdir(DIR_CONFIG) else []:
        ruta = os.path.join(DIR_CONFIG, archivo)
        try:
            with open(ruta, encoding="utf-8") as f:
                for linea in f:
                    if linea.strip().startswith(f"{nombre}="):
                        return linea.split("=", 1)[1].strip()
        except OSError:
            continue
    return None


def log(*partes):
    print(f"[{datetime.now():%H:%M:%S}]", *partes, file=sys.stderr, flush=True)


# ───────────────────────────────────────────────────────────────── descargas

class Descargador:
    """Cliente HTTP educado: robots.txt, un req/s por host y caché en disco."""

    def __init__(self, usar_cache=True, verbose=True):
        self.usar_cache = usar_cache
        self.verbose = verbose
        self._robots = {}          # host -> RobotFileParser | None
        self._ultima = {}          # host -> timestamp
        self.fallos = []           # [(url, motivo)] para el reporte
        os.makedirs(DIR_CACHE, exist_ok=True)

    # -- robots -------------------------------------------------------------
    def permitido(self, url):
        """False si el robots.txt del host prohíbe esta ruta a un agente genérico.

        Si el robots.txt responde 401 o 403, el sitio no quiere tráfico
        automático: se trata como prohibido y no se busca la vuelta.
        """
        host = urllib.parse.urlsplit(url)
        base = f"{host.scheme}://{host.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(base + "/robots.txt")
            try:
                pedido = urllib.request.Request(
                    base + "/robots.txt", headers={"User-Agent": AGENTE})
                with urllib.request.urlopen(pedido, timeout=20) as r:
                    rp.parse(r.read().decode("utf-8", "replace").splitlines())
                self._robots[base] = rp
            except urllib.error.HTTPError as e:
                # 401/403 = no quiere robots. 404 = no hay reglas, se permite.
                self._robots[base] = False if e.code in (401, 403) else None
            except Exception:
                self._robots[base] = None
            time.sleep(SEGUNDOS_ENTRE_PETICIONES)
        rp = self._robots[base]
        if rp is False:
            return False
        if rp is None:
            return True
        return rp.can_fetch(AGENTE, url) or rp.can_fetch("*", url)

    # -- caché --------------------------------------------------------------
    def _ruta_cache(self, url, cuerpo):
        import hashlib
        h = hashlib.sha256((url + (cuerpo or "")).encode()).hexdigest()[:24]
        return os.path.join(DIR_CACHE, h)

    def _espera(self, url):
        host = urllib.parse.urlsplit(url).netloc
        falta = SEGUNDOS_ENTRE_PETICIONES - (time.time() - self._ultima.get(host, 0))
        if falta > 0:
            time.sleep(falta)
        self._ultima[host] = time.time()

    # -- petición -----------------------------------------------------------
    def pedir(self, url, cuerpo=None, cabeceras=None, saltar_robots=False):
        """Devuelve el texto de la respuesta, o None si falla o está prohibida."""
        cuerpo_txt = json.dumps(cuerpo, sort_keys=True) if cuerpo else None

        ruta = self._ruta_cache(url, cuerpo_txt)
        if self.usar_cache and os.path.exists(ruta):
            edad = (time.time() - os.path.getmtime(ruta)) / 3600
            if edad < VIDA_CACHE_HORAS:
                with open(ruta, encoding="utf-8") as f:
                    return f.read()

        if not saltar_robots and not self.permitido(url):
            self.fallos.append((url, "prohibido por robots.txt"))
            if self.verbose:
                log("  ROBOTS prohíbe", url)
            return None

        self._espera(url)
        cab = {"User-Agent": AGENTE, "Accept-Language": "es-CO,es;q=0.9,en;q=0.8"}
        if cuerpo is not None:
            cab["Content-Type"] = "application/json"
            cab["Accept"] = "application/json"
        else:
            cab["Sec-Fetch-Mode"] = "navigate"
            cab["Sec-Fetch-Dest"] = "document"
        cab.update(cabeceras or {})

        datos = cuerpo_txt.encode() if cuerpo_txt else None
        try:
            pedido = urllib.request.Request(url, data=datos, headers=cab)
            with urllib.request.urlopen(pedido, timeout=40) as r:
                texto = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            self.fallos.append((url, f"HTTP {e.code}"))
            return None
        except Exception as e:
            self.fallos.append((url, f"{type(e).__name__}"))
            return None

        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        return texto

    def json(self, url, cuerpo=None, **kw):
        texto = self.pedir(url, cuerpo=cuerpo, **kw)
        if texto is None:
            return None
        try:
            return json.loads(texto)
        except ValueError:
            self.fallos.append((url, "respuesta no es JSON"))
            return None


# ────────────────────────────────────────────────────────────── normalización

_SUFIJOS_SOCIETARIOS = re.compile(
    r"\b(s\s*a\s*s|sas|s\s*a|sa|ltda|limitada|s\s*e\s*n\s*c|sca|bic|zomac|"
    r"y\s*cia|cia|compania|inc|llc|corp|corporation|gmbh|plc|nv|bv|ag|"
    r"srl|sl|spa|holding|group|grupo|colombia|de\s*colombia)\b", re.I)

_ADORNOS_CARGO = re.compile(
    r"\b(urgente|inmediato|postulate\s*ya|aplica\s*ya|nuevo|nueva|vacante|oferta|"
    r"se\s*busca|se\s*requiere|importante\s*empresa|excelente|excelentes|"
    r"con\s*experiencia|bilingue|remoto|hibrido|presencial|teletrabajo|"
    r"medio\s*tiempo|tiempo\s*completo|home\s*office|work\s*from\s*home|"
    r"remote\s*work|remote|hybrid|on\s*site|onsite|full\s*time|part\s*time)\b", re.I)

_CIUDADES = ("bogota", "medellin", "cali", "barranquilla", "cartagena", "bucaramanga",
             "pereira", "manizales", "cucuta", "ibague", "villavicencio", "chia",
             "cota", "soacha", "funza", "mosquera", "colombia", "d c", "dc")


def sin_tildes(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(texto):
    """Minúsculas, sin tildes, sin puntuación, espacios colapsados."""
    t = sin_tildes(texto).lower()
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalizar_empresa(nombre):
    """Además de normalizar, quita los sufijos societarios."""
    t = normalizar(nombre)
    t = _SUFIJOS_SOCIETARIOS.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalizar_cargo(cargo):
    """Además de normalizar, quita los adornos de portal y la ciudad del final."""
    t = re.sub(r"\([^)]*\)", " ", str(cargo or ""))      # códigos entre paréntesis
    t = re.sub(r"[¡!¿?]+", " ", t)
    t = normalizar(t)
    t = _ADORNOS_CARGO.sub(" ", t)
    t = re.sub(r"\b(m\s*w\s*d|f\s*m\s*d|h\s*f|mfd)\b", " ", t)
    t = re.sub(r"\b\d{4,}\b", " ", t)                     # códigos de requisición
    palabras = re.sub(r"\s+", " ", t).strip().split()
    while palabras and palabras[-1] in _CIUDADES:         # ciudad repetida al final
        palabras.pop()
    while palabras and palabras[-1] in ("en", "de", "para", "-"):
        palabras.pop()
    return " ".join(palabras)


SIN_EMPRESA = "empresa no revelada"

_ANONIMAS = re.compile(
    r"confidential|confidencial|importante\s+(empresa|compania|organizacion|"
    r"grupo|multinacional|firma)|empresa\s+del\s+sector|reconocida\s+empresa|"
    r"empresa\s+lider|nuestro\s+cliente|our\s+client|company\s+confidential", re.I)


def empresa_es_anonima(nombre):
    return (not nombre) or bool(_ANONIMAS.search(sin_tildes(str(nombre))))


# Un mismo lugar se escribe de seis formas distintas según el portal:
# «Bogotá D.C.», «Bogota, Capital District, RAP Central, Colombia», «BOG».
# Sin canonizar la ciudad, el mismo aviso en dos portales no colapsa nunca.
#
# Se compara contra el PRIMER segmento (antes de la primera coma), que es la
# localidad. Comparar contra la cadena entera haría que «Santa Fe de Antioquia,
# Antioquia» se fusionara con Medellín, que es otro municipio.
_CANON_CIUDAD = [
    (re.compile(r"^bogot|capital\s*district|^bog$|^chapinero|^usaquen|^teusaquillo"),
     "bogota"),
    (re.compile(r"^medellin|^envigado|^itagui|^sabaneta|^bello$"), "medellin"),
    (re.compile(r"^cali$|^santiago de cali|^yumbo|^palmira"), "cali"),
    (re.compile(r"^barranquilla|^soledad$"), "barranquilla"),
    (re.compile(r"^cartagena"), "cartagena"),
    (re.compile(r"^bucaramanga|^floridablanca|^giron$"), "bucaramanga"),
    (re.compile(r"^chia$|^cota$|^cajica|^zipaquira|^funza|^mosquera|^tocancipa|"
                r"^soacha|alrededores"), "bogota alrededores"),
    (re.compile(r"remot|teletrabajo|anywhere|worldwide|home\s*based|"
                r"work\s*from\s*home"), "remoto"),
]

# Solo se usa cuando el aviso NO da localidad, únicamente la región.
_REGION_SOLA = {
    "cundinamarca": "bogota alrededores",
    "antioquia": "antioquia",
    "valle del cauca": "valle del cauca",
    "atlantico": "atlantico",
}

_PAISES = {"colombia", "peru", "chile", "argentina", "mexico", "panama", "brasil",
           "brazil", "ecuador", "uruguay", "paraguay", "bolivia", "venezuela",
           "espana", "spain", "usa", "eeuu", "united states", "portugal",
           "costa rica", "guatemala", "republica dominicana", "latam", "latinoamerica"}


def normalizar_ciudad(ciudad):
    """Reduce las mil formas de escribir un lugar a una sola.

    Si no reconoce el lugar lo devuelve normalizado tal cual, entero: una ciudad
    desconocida es una ciudad desconocida, no Bogotá. «Ciudad de Panamá» no
    puede volverse «ciudad», ni «Santa Fe de Antioquia» volverse «Medellín».
    """
    crudo = normalizar(ciudad)
    if not crudo:
        return ""
    segmentos = [normalizar(x) for x in str(ciudad).split(",")]
    segmentos = [x for x in segmentos if x]
    if not segmentos:
        return ""

    principal = segmentos[0]
    for rx, canon in _CANON_CIUDAD:
        if rx.search(principal):
            return canon
    # «Remoto» puede venir en cualquier segmento («Colombia, Remote»)
    if _CANON_CIUDAD[-1][0].search(crudo):
        return "remoto"
    if principal in _REGION_SOLA:
        return _REGION_SOLA[principal]
    if principal in _PAISES and len(segmentos) > 1:
        return segmentos[1]
    return principal


def identidad(empresa, cargo, ciudad, agencia=None):
    """La identidad de una vacante. Deduplicar por URL no sirve de nada.

    Los avisos sin nombre de empresa no se pueden deduplicar por empresa:
    se marcan y se deduplican por (cargo, ciudad, agencia).
    """
    c = normalizar_cargo(cargo)
    u = normalizar_ciudad(ciudad)
    if empresa_es_anonima(empresa):
        e = normalizar_empresa(agencia) if agencia else SIN_EMPRESA
        e = e or SIN_EMPRESA
    else:
        e = normalizar_empresa(empresa)
    return f"{e}|{c}|{u}"


# ───────────────────────────────────────────────────────── honestidad de datos

def salario_honesto(base_salary):
    """Traduce un baseSalary de schema.org a (min, max, moneda, periodo).

    Devuelve None cuando NO hay salario publicado. Ojo: Computrabajo y elempleo
    escriben value == 0 para «no publicado». Cero no es un salario.
    """
    if not isinstance(base_salary, dict):
        return None
    moneda = base_salary.get("currency") or base_salary.get("salaryCurrency")
    v = base_salary.get("value")
    if isinstance(v, (int, float)):
        v = {"value": v}
    if not isinstance(v, dict):
        return None

    def num(x):
        try:
            n = float(x)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None          # 0 significa «no publicado»

    minimo = num(v.get("minValue"))
    maximo = num(v.get("maxValue"))
    unico = num(v.get("value"))
    if minimo is None and maximo is None:
        if unico is None:
            return None
        minimo = maximo = unico
    if minimo is None:
        minimo = maximo
    if maximo is None:
        maximo = minimo
    periodo = (v.get("unitText") or base_salary.get("unitText") or "").upper() or None
    return {"min": minimo, "max": maximo, "moneda": moneda, "periodo": periodo}


def extraer_jobpostings(html):
    """Saca todos los JobPosting de schema.org incrustados en un HTML.

    elempleo y Computrabajo publican los dos el JSON-LD completo, así que un
    solo parser sirve para ambos y no hay que raspar etiquetas frágiles.
    """
    hallados = []

    def caza(o):
        if isinstance(o, dict):
            if o.get("@type") == "JobPosting":
                hallados.append(o)
            for v in o.values():
                caza(v)
        elif isinstance(o, list):
            for v in o:
                caza(v)

    for bloque in re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html or "", re.S | re.I):
        try:
            caza(json.loads(bloque.strip()))
        except ValueError:
            continue
    return hallados


def limpiar_html(texto):
    """Convierte la descripción HTML del aviso en texto plano legible."""
    if not texto:
        return ""
    t = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(texto), flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _entidades(t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _entidades(t):
    import html as _h
    return _h.unescape(t)


def fecha_iso(valor):
    """Normaliza una fecha a AAAA-MM-DD. Devuelve None si no se puede leer.

    Nunca inventa una fecha: si la fuente no la publica, es «sin dato».
    """
    if not valor:
        return None
    s = str(valor).strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


def dias_desde(iso):
    if not iso:
        return None
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except ValueError:
        return None


def hoy():
    return date.today().isoformat()


# ───────────────────────────────────────────────────────────── modalidad

_REMOTO = re.compile(r"\b(remoto|remota|remote|teletrabajo|100%\s*remoto|"
                     r"work\s+from\s+home|home\s*office|fully\s+remote)\b", re.I)
_HIBRIDO = re.compile(r"\b(hibrido|hybrid|semipresencial|mixto|"
                      r"\d\s*d[ií]as?\s+(en\s+)?(la\s+)?oficina)\b", re.I)
_PRESENCIAL = re.compile(r"\b(presencial|on\s*site|onsite|in\s*office|"
                         r"trabajo\s+en\s+sitio)\b", re.I)


def clasificar_modalidad(titulo, cuerpo):
    """Devuelve (clasificacion, literal, hay_contradiccion).

    «Remoto» en el título muchas veces significa híbrido en el cuerpo. Se guarda
    la cadena literal del aviso además de la clasificación, y si las dos se
    contradicen la ficha muestra las dos y la marca «modalidad por confirmar».
    """
    t = sin_tildes(titulo or "")
    c = sin_tildes(cuerpo or "")

    def leer(texto):
        if _HIBRIDO.search(texto):
            return "híbrido"
        if _REMOTO.search(texto):
            return "remoto"
        if _PRESENCIAL.search(texto):
            return "presencial"
        return None

    en_titulo, en_cuerpo = leer(t), leer(c)
    literales = []
    for rx in (_REMOTO, _HIBRIDO, _PRESENCIAL):
        for m in rx.finditer(c):
            literales.append(m.group(0))
    literal = literales[0] if literales else (
        (_REMOTO.search(t) or _HIBRIDO.search(t) or _PRESENCIAL.search(t) or [None])
        and (m.group(0) if (m := (_REMOTO.search(t) or _HIBRIDO.search(t)
                                  or _PRESENCIAL.search(t))) else None))

    contradice = bool(en_titulo and en_cuerpo and en_titulo != en_cuerpo)
    return (en_cuerpo or en_titulo), literal, contradice


def titulo_legible(cargo):
    """Quita del título el ruido de portal, dejando el cargo. Para MOSTRAR.

    El título original se conserva y se enseña al pasar el ratón: esto limpia la
    lectura, no reescribe lo que el aviso dice.
    """
    t = re.sub(r"\s*[-–—|]\s*\d[\d\-]{5,}\s*$", "", str(cargo or "").strip())
    t = re.sub(r"\s*\(\s*(req|requisicion|id)?\s*[\d\-]{5,}\s*\)\s*", " ", t, flags=re.I)
    t = re.sub(r"\s*[-–—|]\s*$", "", t)
    return re.sub(r"\s{2,}", " ", t).strip() or str(cargo or "").strip()


def contiene(texto, patrones):
    """¿El texto contiene alguno de estos patrones, como PALABRA? Devuelve la lista.

    Con límites de palabra a propósito. Buscando por subcadena, «LTI» aparece
    dentro de «multimedia», «consultivas» y «multinacional», y el barrido se
    llena de diseñadores gráficos. Pasó de verdad el 2026-08-28.
    """
    t = normalizar(texto)
    hallados = []
    for p in patrones:
        n = normalizar(p)
        if n and re.search(r"\b" + re.escape(n) + r"\b", t):
            hallados.append(p)
    return hallados
