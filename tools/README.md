# Herramientas

Todo es biblioteca estándar de Python. Sin pandas, sin requests, sin selenium,
sin npm, sin build, sin base de datos. Son JSON en disco.

Todo script recibe `--busqueda <id>` y no sabe nada del contenido de la búsqueda:
los criterios viven en `busquedas/<id>.json`. Para agregar una segunda búsqueda
—otra persona, otro cargo— se copia ese JSON y no se toca una línea de código.

## Qué hace cada cosa

| archivo | qué hace |
|---|---|
| `comun.py` | Configuración, descargas educadas, normalización, identidad, honestidad de datos. |
| `barrido.py` | Recorre las fuentes → `<id>/data.json`. Deduplica, puntúa y compara con ayer. |
| `traslados.py` | Tiempos de viaje casa→oficina, **solo** donde hay dirección real. |
| `render.py` | `<id>/data.json` → `<id>/index.html`. |
| `portada.py` | `index.html` de la raíz, una tarjeta por búsqueda. |
| `chequeo.py` | Freno previo al push: credenciales, datos personales y cuadre de fichas. |

Los cuatro recuadros de la página son: vigentes hoy · nuevas desde ayer · con
salario publicado · cuántas cruzan el piso del perfil. Los dos últimos van
juntos a propósito: la brecha entre ellos (hoy 13 publican salario y solo 2
llegan) dice más que cualquiera de los dos por separado.

## Orden de una corrida

```bash
python3 tools/barrido.py   --busqueda comp-ben --dry   # ver sin escribir
python3 tools/barrido.py   --busqueda comp-ben
python3 tools/traslados.py --busqueda comp-ben
python3 tools/render.py    --busqueda comp-ben
python3 tools/portada.py
python3 tools/chequeo.py   --busqueda comp-ben         # devuelve 1 si algo no debe publicarse
```

Durante el desarrollo, `--dry` imprime el resumen y **no escribe nada**.
`--fuente elempleo` corre una sola fuente. `--sin-cache` ignora la caché de 6 horas.

## Qué NO hace, y por qué

**`render.py` no genera la página.** Reemplaza cuatro bloques marcados dentro de
`<id>/index.html`: `DATOS`, `ENCABEZADO`, `RECUADROS` y `RESUMEN`. El diseño y el
JavaScript se editan a mano en el HTML y el script no los toca nunca. Si arreglas
un dato editando el HTML a mano, **lo pierdes en la corrida siguiente**: arregla
el script y vuelve a renderizar.

**El resumen se reescribe entero cada corrida**, no se le agrega. Si solo se
agregara, en tres días la página estaría contando una historia que sus propios
datos desmienten.

**No hay seguimiento de postulaciones.** Se quitó a propósito: esta herramienta
lista y cataloga vacantes, y decidir a cuáles postularse es de quien las lee. Si
alguna vez vuelve, `postulaciones.json` sigue en `.gitignore` y `chequeo.py`
sigue vigilando que no se suba.

**No se inventa ningún dato.** Un dato que el aviso no publica es «sin dato» y se
ve como `?` en la ficha, con una explicación al pasar el ratón. En particular:

- Un salario que la fuente escribe como `0` significa **no publicado**, no cero
  pesos. Computrabajo y elempleo lo hacen todo el tiempo.
- Workday devuelve `postedOn` como texto relativo («Posted 30+ Days Ago»). Eso no
  es una fecha: se guarda el literal y la fecha queda sin dato.
- Si un aviso dice «remoto» en el título e «híbrido» en el cuerpo, la ficha
  muestra las dos cosas y la marca «modalidad por confirmar».
- **No hay mapa.** Ningún aviso publica dirección de oficina. Un mapa con tres
  puntos de cuarenta vacantes engaña más de lo que informa.

**Una ausencia no es una caída.** Un aviso que falta una vez casi siempre sigue
publicado: la fuente parpadeó. Hacen falta **dos ausencias seguidas** para darlo
por caído, y mientras tanto no desaparece de la página — se queda marcado «no
apareció hoy en la fuente». Si vuelve, se marca **«Vuelve»**, nunca «Nueva».

Medido el 31-ago-2026 sobre tres corridas: de 3 movimientos reportados, 1 era
puro parpadeo de Computrabajo. Sin esto, el contador de nuevas que ella mira
cada mañana miente, y «cuánto dura abierta una vacante» —el único dato de
mercado que produce esta herramienta— queda inservible.

**El puntaje solo ordena.** Ninguna vacante se esconde por puntuar bajo: el
modelo no sabe lo que sabes tú. Los pesos están en el JSON, no en el código, y la
ficha muestra el desglose completo. Si un componente no se puede evaluar porque
falta el dato, vale cero y lo dice — nunca se penaliza la ausencia de dato,
porque eso castigaría justo a los avisos incompletos, que son la mayoría.

## Las fuentes, y las que quedaron fuera

Antes de tocar cualquier sitio se lee y se respeta su `robots.txt`; el
`Descargador` lo comprueba solo, una vez por host. Una petición por segundo,
User-Agent real y caché de 6 horas.

**Se consultan:** elempleo (JSON-LD por rutas del sitemap), Computrabajo (JSON-LD
por rutas `/trabajo-de-*`), 12 portales Workday de empresas objetivo, Greenhouse
de AB InBev, Arbeitnow y LinkedIn a través de Apify.

**No se consultan, con nombre propio:**

- **SmartRecruiters** — su `robots.txt` dice `Disallow: /` para todos; solo
  `LinkedInBot` tiene permiso. El endpoint responde 200, pero no se toca.
- **Remotive** — su `robots.txt` prohíbe `/api/*`. Su propia API.
- **Ashby** — su `robots.txt` responde 401. Sin robots legible, no se consulta.
- **Indeed** — devuelve 403 al listado.
- **LinkedIn directo** — sus condiciones prohíben el acceso automatizado. Va por
  Apify y solo por Apify.

**La regla del cookie, que no se negocia:** si un actor de Apify pide la cookie
`li_at`, usuario y contraseña de LinkedIn o «tu sesión» de cualquier forma, no se
usa. Entregar la sesión de LinkedIn a un tercero le da acceso a la red, los
mensajes y la identidad de la persona. Si el único actor que sirve la pidiera,
LinkedIn queda fuera y se dice en la página. Se piden vacantes: nunca perfiles de
personas, nunca contactos, nunca datos de reclutadores.

## Llaves

Dos clases distintas, y conviene no confundirlas:

**Llaves de servidor** (`APIFY_TOKEN`, `LLAVE_RUTAS`). Secretas. Van en Secrets
del repositorio y en `~/.config/vacantes-comp-ben/` en local, con permisos `600`.
Nunca en el repo, nunca en la página, nunca en un commit. Si el barrido corre sin
llave, no falla: deja los campos que dependen de ella marcados como «pendiente» y
sigue.

**Llaves de navegador** (mapa base, embebidos). Son públicas por diseño: el
navegador de cualquiera que abra la página las puede leer, así que esconderlas no
tiene sentido. Van como *variable* del repositorio, se inyectan al renderizar, y
se protegen **restringiéndolas por dominio en el panel del proveedor**, que es la
única protección que sirve para ese tipo de llave. Hoy no hay ninguna, porque no
hay mapa.

`chequeo.py` busca credenciales por la **forma** de la llave, no por su texto
literal: si el patrón se escribiera completo, el archivo se detectaría a sí mismo
y el chequeo fallaría siempre. Por eso los prefijos se arman por concatenación.

## Frenos antes de publicar

1. Si el barrido devuelve menos del 40 % de la corrida anterior, no se publica:
   un parser roto devuelve cero en silencio, y eso se parece demasiado a «hoy no
   había nada».
2. Si una sola fuente devuelve cero pero las demás funcionan, se publica y queda
   marcado en la página. (Arbeitnow devuelve cero casi siempre: está declarada
   con `cero_es_normal` para no dar una falsa alarma diaria.)
3. El número de fichas del HTML tiene que cuadrar con los avisos de `data.json`.
4. `chequeo.py` tiene que pasar.
5. Nunca `git push --force`. Si el push falla: `pull --rebase` y **un** reintento.
   Si vuelve a fallar, el commit queda hecho y se reporta.
