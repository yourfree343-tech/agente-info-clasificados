"""
Detective conspiranoico autónomo.

Flujo:
  1. Elige un tema jugoso (o usa el que le des).
  2. Reúne material: Wikipedia (base factual), noticias recientes y búsqueda web
     (DuckDuckGo), más los documentos OFICIALES del propio archivo que traten el tema.
  3. Sintetiza un "dossier" multi-rol (investigador, conspiranoico, analista,
     detective jefe) en tono inmersivo PERO etiquetando qué es especulación.
  4. Guarda el dossier en una tabla SEPARADA (no se mezcla con los desclasificados).

Motor LLM intercambiable (Gemini / LM Studio / OpenRouter) vía llm.py.
"""

import re
import html
import time
import random
import logging
from datetime import datetime
from urllib.parse import urlparse, quote

import requests

import config
import database
import llm
import analisis
import tareas

log = logging.getLogger(__name__)

_UA = {"User-Agent": "AgenteInfoClasificados/4.0 (investigacion-publica; uso local)"}


# ---------------------------------------------------------------------------
# Búsqueda web (librería ddgs; gestiona DuckDuckGo correctamente)
# ---------------------------------------------------------------------------

def buscar_web(query, n=5):
    """Devuelve [{titulo, url, snippet}]. Vacío si falla.
       Reintenta una vez ante fallos transitorios (rate-limit de DuckDuckGo)."""
    try:
        from ddgs import DDGS
    except ImportError:
        log.warning("  Falta la librería 'ddgs' (pip install ddgs).")
        return []
    for intento in range(2):
        out = []
        try:
            for x in DDGS().text(query, max_results=n):
                titulo = _limpia(x.get("title", ""))
                url = x.get("href", "") or x.get("url", "")
                snippet = _limpia(x.get("body", ""))
                if titulo and url:
                    out.append({"titulo": titulo, "url": url, "snippet": snippet})
            return out
        except Exception as e:
            if intento == 0:
                log.info(f"  Búsqueda '{query}' falló ({e}); reintento en 3s...")
                time.sleep(3)
                continue
            log.warning(f"  Búsqueda fallida '{query}': {e}")
            return []


def buscar_imagenes(query, n=4):
    """Devuelve URLs de imágenes relevantes (portadas, fotos, etc.)."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out = []
    try:
        for x in DDGS().images(query, max_results=n * 2):
            url = x.get("image") or x.get("url")
            thumb = x.get("thumbnail") or url
            titulo = _limpia(x.get("title", ""))
            origen = _limpia(x.get("source", "") or x.get("hostname", ""))
            if not origen and url:
                origen = urlparse(url).netloc  # dominio como pie de imagen
            if url:
                out.append({"url": url, "thumb": thumb, "titulo": titulo, "origen": origen})
            if len(out) >= n:
                break
    except Exception as e:
        log.warning(f"  Búsqueda de imágenes fallida '{query}': {e}")
    return out


def buscar_noticias(query, n=4):
    """Noticias recientes sobre el tema (DuckDuckGo News): el detective vive en 2026 y
       los resultados web genéricos suelen ser artículos viejos."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out = []
    try:
        for x in DDGS().news(query, max_results=n):
            titulo = _limpia(x.get("title", ""))
            url = x.get("url", "") or x.get("href", "")
            if titulo and url:
                fecha = (x.get("date") or "")[:10]
                medio = _limpia(x.get("source", ""))
                snippet = _limpia(x.get("body", ""))
                out.append({"titulo": titulo, "url": url, "fecha": fecha,
                            "snippet": (f"[{medio} {fecha}] " if medio or fecha else "") + snippet})
    except Exception as e:
        log.info(f"  Búsqueda de noticias fallida '{query}': {e}")
    return out


def buscar_wikipedia(tema, n=2):
    """Base factual: introducción de los artículos de Wikipedia más relevantes (primero en
       español; si no hay, en inglés). Devuelve [{titulo, url, snippet}]."""
    for idioma in ("es", "en"):
        api = f"https://{idioma}.wikipedia.org/w/api.php"
        try:
            r = requests.get(api, headers=_UA, timeout=15, params={
                "action": "query", "list": "search", "srsearch": tema, "srlimit": n,
                "format": "json", "srprop": ""})
            titulos = [h["title"] for h in r.json().get("query", {}).get("search", [])]
            if not titulos:
                continue
            r = requests.get(api, headers=_UA, timeout=15, params={
                "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                "exchars": 900, "titles": "|".join(titulos), "format": "json", "redirects": 1})
            paginas = r.json().get("query", {}).get("pages", {}).values()
            out = []
            for p in paginas:
                texto = _limpia(p.get("extract", ""))
                if len(texto) < 80:
                    continue
                t = p.get("title", "")
                out.append({"titulo": f"Wikipedia: {t}",
                            "url": f"https://{idioma}.wikipedia.org/wiki/{quote(t.replace(' ', '_'))}",
                            "snippet": texto})
            if out:
                return out
        except Exception as e:
            log.info(f"  Wikipedia ({idioma}) no disponible para '{tema}': {e}")
    return []


def _limpia(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PROMPT_DOSSIER = """Estamos en el AÑO 2026. Eres un PANEL de investigación con cuatro roles que colaboran:
🕵️ Investigador (recopila hechos y fuentes), 👁️ Conspiranoico (propone conexiones e hipótesis),
🧠 Analista (separa lo PROBADO de lo ESPECULATIVO) y 📕 Detective Jefe (concluye).

TEMA A INVESTIGAR: {tema}

MATERIAL REUNIDO (úsalo como base y cita las URLs; las de Wikipedia y las de documentos
oficiales son las más fiables para los hechos, los resultados web sirven para las teorías):
{contexto}
{oficiales}
Escribe en ESPAÑOL, con tono INMERSIVO y enganchón de detective conspiranoico, PERO
etiquetando con honestidad qué es hecho verificado y qué es pura especulación.
No presentes teorías como verdades. No inventes fuentes: usa SOLO las URLs de arriba.
En "hechos_verificados" pon solo lo que respalde una fuente fiable del material.

Devuelve EXCLUSIVAMENTE este JSON:
{{
  "titulo": "título llamativo del caso",
  "categoria": "una de: {categorias}",
  "gancho": "1-2 frases de apertura intrigantes",
  "hechos_verificados": ["hechos contrastables, cada uno con su fuente entre paréntesis"],
  "hipotesis": ["teorías y conexiones que propone el conspiranoico"],
  "especulacion": ["afirmaciones NO probadas, claramente marcadas como especulación"],
  "conexiones": ["patrones, símbolos, coincidencias, portadas, etc."],
  "veredicto": "conclusión sobria del analista: qué hay de real y qué es ruido (2-4 frases)",
  "nivel_certeza": "ALTO | MEDIO | BAJO",
  "fuentes": ["las URLs usadas"]
}}"""


# ---------------------------------------------------------------------------
# Elección de tema (sin LLM)
# ---------------------------------------------------------------------------

def _busquedas_desde_tema(tema):
    """Deriva 3-4 consultas de búsqueda a partir de un tema, sin usar el LLM."""
    base = (tema or "").strip()
    # Foco corto: corta por el primer conector para quedarse con el núcleo del tema.
    corto = re.split(r"\s+y\s+|\s+—\s+|:|,|\(", base, maxsplit=1)[0].strip() or base
    consultas = [base, f"{corto} documentos desclasificados",
                 f"{corto} evidencia 2026", f"{corto} investigación"]
    vistas, out = set(), []
    for q in consultas:
        q = q.strip()
        if q and q.lower() not in vistas:
            vistas.add(q.lower())
            out.append(q)
    return out


def _elegir_tema_local():
    """Elige un tema: primero de la cola sugerida por el usuario (FIFO); si está vacía,
       del banco semilla, prefiriendo los que aún no se han usado. Sustituye a la antigua
       llamada al LLM para 'elegir tema' (lenta y frágil en CPU)."""
    en_cola = database.pop_tema_cola()
    if en_cola:
        return en_cola, _busquedas_desde_tema(en_cola)
    semillas = getattr(config, "DETECTIVE_TEMAS_SEMILLA", []) or ["una conspiración famosa"]
    ya = {(t or "").strip().lower() for t in database.get_temas_investigados(40)}
    frescas = [s for s in semillas if s.strip().lower() not in ya]
    tema = random.choice(frescas or semillas)
    return tema, _busquedas_desde_tema(tema)


# ---------------------------------------------------------------------------
# Investigación
# ---------------------------------------------------------------------------

def _lista_str(x):
    """El modelo a veces devuelve un texto donde se pidió una lista (o dicts sueltos)."""
    if isinstance(x, str):
        return [x.strip()] if x.strip() else []
    return [str(i).strip() for i in (x or []) if str(i).strip()]


def _fase(texto):
    _tarea.actualizar(fase=texto)


def _terminos_tema(tema):
    """Términos para cruzar con el archivo oficial: entidades reconocidas y, si no hay,
       las palabras largas del tema."""
    terminos = list(dict.fromkeys(analisis.extraer_terminos(tema)))
    if not terminos:
        terminos = [w for w in re.findall(r"[\wÁÉÍÓÚáéíóúñÑ-]{5,}", tema)
                    if w.lower() not in analisis._STOPWORDS][:4]
    return terminos


def investigar(tema=None):
    if not llm.disponible():
        return {"ok": False, "error": llm.mensaje_no_disponible()}

    # 1) Elegir tema y consultas. Antes esto gastaba una llamada extra al LLM
    #    (lenta en CPU y un punto de fallo más); ahora se deriva del banco de
    #    temas semilla, que ya da variedad y evita repetir lo ya investigado.
    if tema:
        busquedas = _busquedas_desde_tema(tema)
    else:
        tema, busquedas = _elegir_tema_local()
    _tarea.actualizar(tema=tema)

    # 2) Reunir material: Wikipedia (hechos), noticias recientes y web (teorías).
    _fase("consultando Wikipedia")
    wiki = buscar_wikipedia(tema) if getattr(config, "DETECTIVE_WIKIPEDIA", True) else []
    _fase("buscando noticias recientes")
    noticias = buscar_noticias(busquedas[0], getattr(config, "DETECTIVE_NOTICIAS", 4))
    _fase("buscando en internet")
    web = []
    for q in busquedas[:config.DETECTIVE_MAX_BUSQUEDAS]:
        web.extend(buscar_web(q, config.DETECTIVE_RESULTADOS_POR_BUSQUEDA))

    resultados, vistos = [], set()
    for res in wiki + noticias + web:
        if res["url"] in vistos:
            continue
        vistos.add(res["url"])
        resultados.append(res)
    if not wiki and not web and not noticias:
        return {"ok": False, "error": "No se obtuvieron resultados de búsqueda en internet."}

    # Documentos OFICIALES del propio archivo que tratan el tema: van al prompt para que
    # los hechos se apoyen en ellos (antes solo se enlazaban después, sin que el modelo los viera).
    _fase("cruzando con el archivo oficial")
    oficiales = database.buscar_documentos_por_texto(_terminos_tema(tema), limit=3)

    # Contexto acotado: en CPU (LM Studio) menos texto = mucho más rápido; en la nube
    # cabe bastante más material sin coste de tiempo apreciable.
    if llm.es_local():
        max_res, max_snip = 10, 220
    else:
        max_res, max_snip = 16, 420
    contexto = "\n".join(
        f"- {r['titulo']} ({r['url']})\n  {r['snippet'][:max_snip if not r['titulo'].startswith('Wikipedia') else 900]}"
        for r in resultados[:max_res]
    )
    bloque_oficial = ""
    if oficiales:
        bloque_oficial = "\nDOCUMENTOS OFICIALES DEL ARCHIVO (fuente primaria, muy fiable):\n" + "\n".join(
            f"- {o['titulo']} ({o['url_fuente']})" + (f"\n  {o['resumen'][:300]}" if o.get("resumen") else "")
            for o in oficiales) + "\n"

    # 3) Sintetizar el dossier
    _fase("redactando el dossier")
    categorias = getattr(config, "DETECTIVE_CATEGORIAS", ["Otras"])
    prompt_dossier = PROMPT_DOSSIER.format(
        tema=tema, contexto=contexto, oficiales=bloque_oficial, categorias=" | ".join(categorias))
    r2 = llm.generar_json(prompt_dossier, temperature=0.8)
    if not r2.get("ok"):
        return {"ok": False, "error": "No se pudo redactar el dossier: " + r2.get("error", "")}
    d = r2["data"]
    certeza = llm.norm_nivel(d.get("nivel_certeza"), "MEDIO")
    # Validar categoría contra la lista permitida
    categoria = (d.get("categoria") or "").strip()
    if categoria not in categorias:
        categoria = next((c for c in categorias if c.lower() in categoria.lower()), "Otras")

    # Fuentes: solo las que el modelo citó Y existen en el material reunido (así no se
    # cuela una URL inventada), seguidas del resto de URLs reales encontradas.
    reales = [r["url"] for r in resultados] + [o["url_fuente"] for o in oficiales if o.get("url_fuente")]
    citadas = [u for u in _lista_str(d.get("fuentes")) if u in reales]
    fuentes = list(dict.fromkeys(citadas + reales))

    # Imágenes relacionadas (portadas, fotos, símbolos del tema investigado).
    imagenes = []
    n_imgs = getattr(config, "DETECTIVE_IMAGENES", 4)
    if n_imgs > 0:
        _fase("buscando imágenes")
        consulta_img = (d.get("titulo") or tema)
        imagenes = buscar_imagenes(consulta_img, n=n_imgs)

    # Cruce con los documentos OFICIALES ya archivados: los que el modelo vio en el prompt
    # más los que casen con las entidades del título final.
    terminos_cruce = analisis.extraer_terminos(f"{tema} {d.get('titulo', '')}")
    documentos_relacionados = oficiales + [
        o for o in database.buscar_documentos_por_texto(list(dict.fromkeys(terminos_cruce)), limit=3)
        if o["id"] not in {x["id"] for x in oficiales}]
    documentos_relacionados = [{"id": o["id"], "titulo": o["titulo"], "url_fuente": o["url_fuente"]}
                               for o in documentos_relacionados[:4]]

    inv = {
        "id": "INV-" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "fecha": datetime.now().isoformat(),
        "tema": tema,
        "titulo": d.get("titulo") or tema,
        "gancho": d.get("gancho", ""),
        "hechos_verificados": _lista_str(d.get("hechos_verificados")),
        "hipotesis": _lista_str(d.get("hipotesis")),
        "especulacion": _lista_str(d.get("especulacion")),
        "conexiones": _lista_str(d.get("conexiones")),
        "veredicto": d.get("veredicto", ""),
        "nivel_certeza": certeza,
        "fuentes": fuentes[:25],
        "motor": llm.nombre_motor(),
        "imagenes": imagenes,
        "categoria": categoria,
        "documentos_relacionados": documentos_relacionados,
    }
    database.insert_investigacion(inv)
    log.info(f"  Detective: nuevo dossier '{inv['titulo'][:50]}' "
             f"({len(resultados)} fuentes, {len(imagenes)} imágenes).")
    return {"ok": True, "investigacion": inv}


# ---------------------------------------------------------------------------
# Ejecución en segundo plano
#
# Un único cerrojo compartido por el botón "Investigar ahora" y el planificador
# automático: así NUNCA corren dos investigaciones a la vez contra el mismo
# modelo local (en CPU eso las arrastraría a ambas). `lanzar()` no bloquea: deja
# la investigación en un hilo y devuelve enseguida, para que la petición HTTP no
# se quede colgada los minutos que tarda el modelo.
# ---------------------------------------------------------------------------

_tarea = tareas.TareaFondo("detective", tema=None, ultimo_titulo=None, ultimo_id=None)


def estado_actual():
    """Copia del estado de la investigación en segundo plano (para la API/UI)."""
    return _tarea.estado()


def _run(tema):
    res = investigar(tema)
    if res.get("ok"):
        _tarea.actualizar(ultimo_titulo=res["investigacion"].get("titulo"),
                          ultimo_id=res["investigacion"].get("id"), ultimo_error=None)
    else:
        _tarea.actualizar(ultimo_error=res.get("error"))
        log.info(f"  Detective: {res.get('error')}")


def lanzar(tema=None):
    """Inicia una investigación en segundo plano si no hay otra en curso.
       Devuelve (iniciada: bool, mensaje: str). NO bloquea."""
    iniciada, msg = _tarea.lanzar(_run, tema, al_iniciar={"tema": tema},
                                  ocupado="Ya hay una investigación en curso; espera a que termine.")
    if not iniciada:
        return False, msg
    return True, (f"Investigando: {tema}" if tema else "Investigación iniciada.")


# ---------------------------------------------------------------------------
# Voz escéptica: contraargumento racional bajo demanda para un dossier ya existente.
# ---------------------------------------------------------------------------

PROMPT_CONTRAARGUMENTO = """Eres un escéptico profesional (divulgador científico, tipo investigador
de fraudes y desinformación). Te doy un caso ya investigado por un panel conspiranoico. Tu trabajo
es cuestionar sus hipótesis con la explicación más racional y probable: sesgos cognitivos, errores
lógicos, coincidencias sobrevaloradas, falta de pruebas verificables, motivos mundanos. Sé concreto:
señala qué parte exacta de la hipótesis es más débil. Escribe en ESPAÑOL, tono sobrio y directo.

CASO: {titulo}
HIPÓTESIS A CUESTIONAR: {hipotesis}
ESPECULACIÓN: {especulacion}

Devuelve EXCLUSIVAMENTE este JSON:
{{"contraargumento": "3 a 6 frases con la explicación escéptica más probable"}}"""


def generar_contraargumento(inv_id):
    """Genera (o regenera) la réplica escéptica de un dossier ya guardado."""
    inv = database.get_investigacion(inv_id)
    if not inv:
        return {"ok": False, "error": "Dossier no encontrado."}
    if not llm.disponible():
        return {"ok": False, "error": llm.mensaje_no_disponible()}
    prompt = PROMPT_CONTRAARGUMENTO.format(
        titulo=inv.get("titulo") or inv.get("tema") or "",
        hipotesis="; ".join(inv.get("hipotesis") or []) or "(ninguna registrada)",
        especulacion="; ".join(inv.get("especulacion") or []) or "(ninguna registrada)",
    )
    r = llm.generar_json(prompt, temperature=0.6)
    if not r.get("ok"):
        return {"ok": False, "error": "No se pudo generar el contraargumento: " + r.get("error", "")}
    texto = (r["data"].get("contraargumento") or "").strip()
    if not texto:
        return {"ok": False, "error": "El motor no devolvió un contraargumento válido."}
    database.set_contraargumento(inv_id, texto)
    return {"ok": True, "contraargumento": texto}


def investigar_auto():
    """Entrada para el planificador: lanza una investigación si no hay otra activa."""
    iniciada, msg = lanzar(None)
    if not iniciada:
        log.info(f"  Detective auto: {msg}")
