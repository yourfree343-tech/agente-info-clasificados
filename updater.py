"""
Actualizador diario de documentos desclasificados.

Estrategia (v4): solo fuentes que entregan PDFs descargables.
  1. Páginas oficiales con listados de PDFs (JFK, RFK, MLK, Papeles del Pentágono...).
  2. archive.org: colecciones históricas (MK-Ultra, Libro Azul, Northwoods...).
  3. NARA NDC: listas de publicación trimestrales (PDF).
  4. FBI Vault: archivos desclasificados del FBI (RSS; cada item es un PDF).
  5. The Black Vault: documentos obtenidos por FOIA (RSS con los PDF enlazados).

Rotación: cada fuente aporta como máximo N documentos NUEVOS por actualización. En
las colecciones grandes (miles de PDFs) eso hace que el archivo crezca cada día con
material distinto, en vez de quedarse siempre con los mismos primeros N enlaces.

Regla de oro: antes de guardar nada, se comprueba que el documento se puede
descargar. Si no, se descarta (ver _es_descargable). Lo que ya está archivado no se
vuelve a comprobar.
"""

import re
import html
import hashlib
import logging
from datetime import datetime
from functools import partial
from urllib.parse import urljoin, quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

import config
import database
import tareas

# El logging lo configura la app (app.py) al arrancar; aquí solo tomamos el logger.
log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

_NO_DESCARGABLES = (".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip", ".csv")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _get(url):
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"  No se pudo obtener {url}: {e}")
        return None


def _doc_id(prefix, text):
    digest = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()[:8].upper()
    return f"{prefix}-{digest}"


def _clean_text(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _fecha_desde_url(url):
    """Fecha de publicación codificada en la ruta, p. ej. NARA: /releases/2025/0318/ -> 2025-03-18;
       /releases/2023/ -> 2023. '' si no hay."""
    m = re.search(r"/releases?/((?:19|20)\d{2})/(\d{2})(\d{2})/", url or "")
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"/releases?/((?:19|20)\d{2})/", url or "")
    return m.group(1) if m else ""


def _fecha_struct(st):
    """time.struct_time (feedparser) -> 'YYYY-MM-DD', o '' si no hay."""
    try:
        return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d}" if st else ""
    except AttributeError:
        return ""


def _titulo_desde_archivo(nombre_archivo):
    """'00010472_no_information_identifiable.pdf' -> 'No information identifiable'.
       Si solo queda un código (p. ej. '104-10130-10026'), se conserva tal cual."""
    stem = unquote(nombre_archivo).rsplit("/", 1)[-1]
    stem = re.sub(r"\.pdf$", "", stem, flags=re.IGNORECASE)
    legible = re.sub(r"^\d{5,}[_\-\s]+", "", stem).replace("_", " ").strip()
    if not re.search(r"[A-Za-z]{3,}", legible):
        return stem
    legible = re.sub(r"\s+", " ", legible)
    return legible[:1].upper() + legible[1:]


def _es_descargable(url):
    """Comprueba que la URL entrega un documento real (PDF o página legible) y que
       no es demasiado grande para analizarlo. Si no, la fuente no vale para ese item.
    """
    if not url:
        return False
    path = url.lower().split("?")[0]
    if path.endswith(_NO_DESCARGABLES):
        return False
    try:
        h = requests.head(url, headers=BROWSER_HEADERS, timeout=15, allow_redirects=True)
        if h.status_code >= 400 and h.status_code not in (403, 405):
            return False   # 403/405: algunos servidores no aceptan HEAD pero sí GET
        ct = h.headers.get("Content-Type", "").lower()
        cl = h.headers.get("Content-Length", "")
        if cl.isdigit() and int(cl) > config.MAX_DOC_BYTES:
            return False   # demasiado grande para descargar/analizar
        if path.endswith(".pdf"):
            return True
        return any(t in ct for t in ("pdf", "html", "text"))
    except Exception:
        return path.endswith(".pdf")


def _doc_pdf(nombre, titulo, pdf_url, categorias, pais, fiabilidad, prefijo,
             tipo_doc="Documento desclasificado (PDF)", fecha="", descripcion="",
             organismo=None, url_noticia=None, verificacion=None,
             estado="DESCLASIFICADO OFICIALMENTE"):
    """Construye el dict de un documento a partir de un PDF oficial.
       fecha: la de publicación/desclasificación si se conoce; '' si no (mejor vacío
       que la fecha de hoy, que antes hacía pasar un expediente de 1947 por uno de 2026)."""
    confianza = "ALTO" if fiabilidad == "Alta" else "MEDIO"
    hoy = datetime.now().strftime("%Y-%m-%d")
    resumen = descripcion or (f"[Pendiente de análisis con IA] Documento desclasificado disponible "
                              f"en {nombre}. Se resumirá automáticamente; también puedes pulsar "
                              f"'Resumir con IA'.")
    return {
        "id": _doc_id(prefijo, pdf_url),
        "titulo": titulo,
        "titulo_original": titulo,
        "fecha_documento": fecha or "",
        "fecha_acceso": hoy,
        "organismo": organismo or [nombre],
        "tipo_documento": tipo_doc,
        "clasificacion_original": "Desclasificado (variable por documento)",
        "idioma_original": "Inglés",
        "url_fuente": pdf_url,
        "url_noticia": url_noticia or pdf_url,
        "estado_desclasificacion": estado,
        "verificado": "Oficial",
        "fuente_fiabilidad": fiabilidad,
        "verificacion_autenticidad": verificacion or f"Documento PDF descargable publicado por {nombre}.",
        "pais": pais,
        "categorias": categorias,
        "resumen_ejecutivo": resumen,
        "puntos_clave": [f"Fuente: {nombre}"],
        "implicaciones": "",
        "nivel_confianza": confianza,
        "razon_confianza": f"Documento oficial descargable de {nombre} (fiabilidad {fiabilidad.lower()}).",
        "num_documentos": "1 documento (PDF)",
    }


# ---------------------------------------------------------------------------
# Scraper genérico: PDFs enlazados en una página oficial
# ---------------------------------------------------------------------------

def scrape_pdf_page(nombre, url, categorias, pais, fiabilidad, extra=None):
    """Todos los PDFs enlazados en la página (candidatos; la rotación la hace _ingerir).
       extra (opcional, en config.PDF_PAGES): {"fecha": "2011-06-13", "filtro": "regex"}."""
    extra = extra or {}
    r = _get(url)
    if not r:
        return []
    filtro = re.compile(extra["filtro"], re.IGNORECASE) if extra.get("filtro") else None
    soup = BeautifulSoup(r.text, "html.parser")
    docs, vistos = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        full = urljoin(r.url, href)
        if full in vistos:
            continue
        vistos.add(full)
        etiqueta = _clean_text(a.get_text())
        if filtro and not (filtro.search(full) or filtro.search(etiqueta)):
            continue
        etiqueta = re.sub(r"^(download|descargar)\s+(the\s+|el\s+|la\s+)?", "", etiqueta,
                          flags=re.IGNORECASE)
        # Si el texto del enlace es solo el nombre del archivo (o "PDF"), se saca un
        # título legible del propio nombre del archivo.
        if not etiqueta or etiqueta.lower() in ("pdf", "download", "descargar") \
                or "_" in etiqueta or etiqueta.lower().endswith(".pdf"):
            etiqueta = _titulo_desde_archivo(full)
        titulo = f"{nombre} — {etiqueta[:110]}"
        fecha = extra.get("fecha") or _fecha_desde_url(full)
        docs.append(_doc_pdf(nombre, titulo, full, categorias, pais, fiabilidad, "PDF", fecha=fecha))
    return docs


# ---------------------------------------------------------------------------
# archive.org: documentos desclasificados alojados (API de metadatos)
# ---------------------------------------------------------------------------

def scrape_archive_org(nombre, identifier, categorias, pais, fiabilidad, extra=None):
    extra = extra or {}
    r = _get(f"https://archive.org/metadata/{identifier}")
    if not r:
        return []
    try:
        meta = r.json()
    except Exception:
        return []
    pdfs = [f for f in meta.get("files", []) if f.get("name", "").lower().endswith(".pdf")]
    # Los "_text.pdf" y demás derivados son copias del original: solo si no hay original.
    originales = [f for f in pdfs if f.get("source") != "derivative"]
    pdfs = originales or pdfs
    descripcion = ""
    if len(pdfs) == 1:
        # La descripción del item solo describe ESTE documento si el item tiene uno solo
        # (en una colección de 200 PDFs sería engañoso usarla como resumen de cada uno).
        d = (meta.get("metadata") or {}).get("description") or ""
        d = d[0] if isinstance(d, list) else d
        descripcion = _clean_text(d)[:900] if len(_clean_text(d)) > 80 else ""
    docs = []
    for f in pdfs:
        name = f.get("name", "")
        try:
            size = int(f.get("size", 0) or 0)
        except ValueError:
            size = 0
        if size and size > config.MAX_DOC_BYTES:
            continue
        url = f"https://archive.org/download/{identifier}/{quote(name)}"
        etiqueta = name.rsplit(".", 1)[0].replace("_", " ").strip()
        titulo = f"{nombre} — {etiqueta[:80]}"
        docs.append(_doc_pdf(nombre, titulo, url, categorias, pais, fiabilidad, "ARCHV",
                             tipo_doc="Documento desclasificado (archive.org, PDF)",
                             fecha=extra.get("fecha", ""), descripcion=descripcion,
                             verificacion=f"Copia del documento alojada en archive.org "
                                          f"(colección «{identifier}»). Repositorio público verificado."))
    return docs


# ---------------------------------------------------------------------------
# NARA NDC: listas de publicación (PDF)
# ---------------------------------------------------------------------------

def scrape_nara_ndc():
    r = _get(config.NARA_NDC_URL)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    docs = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "release" not in href.lower() or not href.lower().endswith(".pdf"):
            continue
        full = href if href.startswith("http") else "https://www.archives.gov" + href
        texto = _clean_text(link.get_text())
        titulo = f"NARA NDC — {texto or 'Lista de publicaciones desclasificadas'}"
        d = _doc_pdf("National Declassification Center (NARA)", titulo, full,
                     ["Seguridad y defensa", "Política exterior y diplomacia"],
                     "EE. UU.", "Alta", "NARA",
                     tipo_doc="Lista de publicaciones desclasificadas (PDF)",
                     fecha=_fecha_desde_url(full))
        docs.append(d)
    return docs


# ---------------------------------------------------------------------------
# FBI Vault: archivos desclasificados (RSS; cada item es un PDF)
# ---------------------------------------------------------------------------

def scrape_fbi_vault():
    if not HAS_FEEDPARSER:
        log.warning("  feedparser no instalado; se omite el FBI Vault.")
        return []
    parsed = feedparser.parse(config.FBI_VAULT_RSS, agent=BROWSER_HEADERS["User-Agent"])
    docs = []
    for entry in parsed.entries:
        titulo = _clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not titulo or not link:
            continue
        # En el FBI Vault, la URL del PDF es la del item sin el sufijo '/view'.
        pdf_url = re.sub(r"/view/?$", "", link)
        d = _doc_pdf("FBI Vault", f"FBI Vault — {titulo}", pdf_url,
                     ["Inteligencia y espionaje", "Corrupción y gobernanza"],
                     "EE. UU.", "Alta", "FBI",
                     tipo_doc="Archivo desclasificado del FBI (PDF)",
                     fecha=_fecha_struct(entry.get("published_parsed") or entry.get("updated_parsed")))
        docs.append(d)
    return docs


# ---------------------------------------------------------------------------
# The Black Vault: documentos obtenidos vía FOIA (RSS; cada entrada enlaza sus PDFs)
# ---------------------------------------------------------------------------

_BV_AGENCIAS = {
    "cia": "CIA", "fbi": "FBI", "nsa": "NSA", "navy": "U.S. Navy", "army": "U.S. Army",
    "airforce": "U.S. Air Force", "usaf": "U.S. Air Force", "af": "U.S. Air Force",
    "usmc": "U.S. Marine Corps", "osd": "Office of the Secretary of Defense",
    "dod": "Department of Defense", "dia": "Defense Intelligence Agency",
    "doe": "Department of Energy", "nasa": "NASA", "state": "Department of State",
    "dhs": "Department of Homeland Security", "nro": "National Reconnaissance Office",
    "nga": "National Geospatial-Intelligence Agency", "odni": "ODNI", "aaro": "AARO",
    "faa": "FAA", "doj": "Department of Justice", "nara": "NARA", "usss": "Secret Service",
    "darpa": "DARPA", "socom": "U.S. Special Operations Command", "northcom": "NORTHCOM",
}

# (palabras en las etiquetas/título de la entrada) -> categoría del archivo
_BV_CATEGORIAS = [
    (("ufo", "uap", "unidentified", "mysteries", "aaro"), "Ciencia y tecnología militar"),
    (("cia", "nsa", "fbi", "intelligence", "spy", "espionage", "surveillance", "qanon"),
     "Inteligencia y espionaje"),
    (("military", "pentagon", "defense", "navy", "army", "air force", "nuclear", "weapon"),
     "Seguridad y defensa"),
    (("government", "controvers", "corruption", "congress", "epstein", "scandal"),
     "Corrupción y gobernanza"),
    (("human rights", "torture", "civil rights", "detainee"), "Derechos humanos"),
    (("foreign", "diplomac", "state department", "embassy"), "Política exterior y diplomacia"),
]


def _bv_agencia(pdf_url):
    """Agencia emisora: carpeta de la ruta en theblackvault.com (/documents/cia/...) o, si
       el PDF está en la web de la propia agencia (aaro.mil, cia.gov...), su dominio."""
    url = (pdf_url or "").lower()
    m = re.search(r"theblackvault\.com/documents/([a-z0-9_\-]+)/", url)
    if m:
        clave = m.group(1)
    else:
        host = (urlparse(url).hostname or "").split(".")
        clave = host[-2] if len(host) >= 2 else ""
    if not clave:
        return "Agencia federal de EE. UU."
    return _BV_AGENCIAS.get(clave, clave.upper())


def _bv_categorias(texto):
    t = texto.lower()
    cats = [cat for claves, cat in _BV_CATEGORIAS if any(k in t for k in claves)]
    return list(dict.fromkeys(cats))[:3] or ["Inteligencia y espionaje"]


def _bv_resumen(entry):
    s = _clean_text(entry.get("summary", ""))
    s = re.sub(r"\s*The post .*? (first )?appeared (first )?on The Black Vault\.?\s*$", "", s)
    s = s.replace("[…]", "…").replace("[...]", "…").strip()
    return s[:900]


def scrape_black_vault():
    if not HAS_FEEDPARSER:
        log.warning("  feedparser no instalado; se omite The Black Vault.")
        return []
    r = _get(config.BLACK_VAULT_RSS)
    if not r:
        return []
    parsed = feedparser.parse(r.content)
    por_entrada = getattr(config, "BLACK_VAULT_PDFS_POR_ENTRADA", 2)
    docs = []
    for entry in parsed.entries:
        titulo = _clean_text(entry.get("title", ""))
        if not titulo:
            continue
        cuerpo = " ".join(c.get("value", "") for c in (entry.get("content") or [])) or entry.get("summary", "")
        pdfs = list(dict.fromkeys(re.findall(r'href="(https?://[^"]+?\.pdf)"', cuerpo, re.IGNORECASE)))
        # Primero los alojados por la propia Black Vault (los .mil suelen bloquear descargas).
        pdfs.sort(key=lambda u: 0 if "theblackvault.com" in u else 1)
        etiquetas = " ".join(t.get("term", "") for t in (entry.get("tags") or []))
        categorias = _bv_categorias(f"{etiquetas} {titulo}")
        resumen = _bv_resumen(entry)
        fecha = _fecha_struct(entry.get("published_parsed"))
        for k, pdf in enumerate(pdfs[:por_entrada], 1):
            agencia = _bv_agencia(pdf)
            docs.append(_doc_pdf(
                "The Black Vault (FOIA)",
                f"The Black Vault — {titulo}" + (f" (documento {k})" if k > 1 else ""),
                pdf, categorias, "EE. UU.", "Media", "BVAULT",
                tipo_doc="Documento obtenido vía FOIA (PDF)",
                fecha=fecha, descripcion=resumen,
                organismo=[agencia, "The Black Vault (FOIA)"],
                url_noticia=entry.get("link") or pdf,
                estado="PUBLICADO VÍA FOIA",
                verificacion=(f"Documento entregado por {agencia} en respuesta a una solicitud FOIA y "
                              f"alojado por The Black Vault (archivo privado de referencia). "
                              f"Contrasta con la agencia emisora antes de citarlo."),
            ))
    return docs


# ---------------------------------------------------------------------------
# Coordinador principal
# ---------------------------------------------------------------------------

def _ingerir(nombre, docs, max_nuevos=None):
    """Inserta hasta max_nuevos documentos descargables que aún no estén archivados.
       A los ya archivados solo se les corrige la fecha si tenían la provisional.
       Devuelve nº de nuevos."""
    existentes = database.ids_existentes([d["id"] for d in docs])
    fechas = sum(1 for d in docs if d["id"] in existentes
                 and database.actualizar_fecha_provisional(d["id"], d.get("fecha_documento")))

    candidatos = [d for d in docs if d["id"] not in existentes]
    # Tope de comprobaciones HEAD por ciclo: si una colección tiene cientos de PDFs
    # demasiado grandes, no se revisan todos cada día.
    tope = max(20, (max_nuevos or 10) * 4)
    nuevos = descartados = 0
    for d in candidatos[:tope]:
        if max_nuevos is not None and nuevos >= max_nuevos:
            break
        if not _es_descargable(d["url_fuente"]):
            descartados += 1
            continue
        if database.insert_document(d):
            nuevos += 1

    detalle = []
    if descartados:
        detalle.append(f"{descartados} descartados (no descargables o demasiado grandes)")
    if fechas:
        detalle.append(f"{fechas} fechas corregidas")
    pendientes = max(0, len(candidatos) - nuevos - descartados)
    if pendientes and max_nuevos is not None:
        detalle.append(f"{pendientes} por incorporar en próximos ciclos")
    database.log_update(nombre, len(docs), nuevos, "OK", " · ".join(detalle))
    log.info(f"  {nombre}: {len(docs)} en la fuente, {nuevos} nuevos, {descartados} descartados, "
             f"{fechas} fechas corregidas")
    return nuevos


def _fuentes():
    """(nombre, función sin argumentos que devuelve candidatos, máx. nuevos por ciclo)."""
    out = []
    for nombre, url, cats, pais, fiab, maxp, *extra in config.PDF_PAGES:
        out.append((nombre, partial(scrape_pdf_page, nombre, url, cats, pais, fiab,
                                    extra[0] if extra else None), maxp))
    for nombre, idf, cats, pais, fiab, maxp, *extra in getattr(config, "ARCHIVE_ORG_ITEMS", []):
        out.append((nombre, partial(scrape_archive_org, nombre, idf, cats, pais, fiab,
                                    extra[0] if extra else None), maxp))
    if config.SCRAPE_NARA_NDC:
        out.append(("NARA NDC", scrape_nara_ndc, None))
    if config.FBI_VAULT_ENABLED:
        out.append(("FBI Vault", scrape_fbi_vault, config.FBI_VAULT_MAX))
    if getattr(config, "BLACK_VAULT_ENABLED", False):
        out.append(("The Black Vault (FOIA)", scrape_black_vault, getattr(config, "BLACK_VAULT_MAX", 8)))
    return out


def run_update():
    log.info("=== Iniciando actualización de documentos ===")
    total_nuevos = 0
    fuentes = _fuentes()
    for i, (nombre, scraper, max_nuevos) in enumerate(fuentes):
        _tarea.actualizar(fase=nombre, progreso=[i, len(fuentes)])
        log.info(f"Fuente: {nombre}")
        try:
            total_nuevos += _ingerir(nombre, scraper(), max_nuevos)
        except Exception as e:
            log.error(f"  Error en {nombre}: {e}")
            database.log_update(nombre, 0, 0, "ERROR", str(e)[:200])
    _tarea.actualizar(progreso=[len(fuentes), len(fuentes)])

    log.info(f"=== Actualización completada. Total nuevos: {total_nuevos} ===")

    # Traducción automática de títulos al español (una sola llamada para todos)
    if total_nuevos > 0:
        _tarea.actualizar(fase="traduciendo títulos")
        try:
            import llm
            if llm.disponible():
                pendientes = database.get_titulos_pendientes()
                res = llm.traducir_titulos(pendientes)
                for doc_id, titulo_es in res.get("traducciones", {}).items():
                    database.set_titulo(doc_id, titulo_es)
                log.info(f"  Títulos traducidos al español: {len(res.get('traducciones', {}))}")
        except Exception as e:
            log.error(f"  Error traduciendo títulos: {e}")

    # Resumen con IA de los nuevos: en su propia tarea de fondo (no alarga esta).
    if config.AUTO_ANALYZE_NEW and total_nuevos > 0:
        try:
            import analizador
            iniciada, msg = analizador.lanzar()
            if not iniciada:
                log.info(f"  IA: {msg}")
        except Exception as e:
            log.error(f"  Error lanzando el análisis IA: {e}")

    return total_nuevos


# ---------------------------------------------------------------------------
# Ejecución en segundo plano: un cerrojo compartido por el botón "Actualizar ahora"
# y el planificador diario, para que la petición HTTP no se quede colgada los
# minutos que tarda el scraping.
# ---------------------------------------------------------------------------

_tarea = tareas.TareaFondo("actualizacion", ultimo_nuevos=None)


def estado_actual():
    """Copia del estado de la actualización en segundo plano (para la API/UI)."""
    return _tarea.estado()


def _run():
    nuevos = run_update()
    _tarea.actualizar(ultimo_nuevos=nuevos, ultimo_error=None)


def lanzar():
    """Inicia una actualización en segundo plano si no hay otra en curso.
       Devuelve (iniciada: bool, mensaje: str). NO bloquea."""
    iniciada, msg = _tarea.lanzar(_run, ocupado="Ya hay una actualización en curso; espera a que termine.")
    return iniciada, (msg or "Actualización iniciada.")


def actualizar_auto():
    """Entrada para el planificador: lanza una actualización si no hay otra activa."""
    iniciada, msg = lanzar()
    if not iniciada:
        log.info(f"  Actualización auto: {msg}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    database.init_db()
    database.seed_initial_data()
    run_update()
