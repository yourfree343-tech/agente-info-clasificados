"""
Actualizador diario de documentos desclasificados.

Estrategia (v3): solo fuentes que entregan PDFs descargables.
  1. Páginas oficiales con listados de PDFs (p. ej. registros JFK 2025).
  2. NARA NDC: listas de publicación trimestrales (PDF/Excel).
  3. FBI Vault: archivos desclasificados del FBI (RSS; cada item es un PDF).

Regla de oro: antes de guardar nada, se comprueba que el documento se puede
descargar. Si no, se descarta (ver _es_descargable).
"""

import re
import html
import hashlib
import logging
import os
from datetime import datetime
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

import config
import database

# El logging lo configura la app (app.py) al arrancar; aquí solo tomamos el logger.
log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


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


def _es_descargable(url):
    """Comprueba que la URL entrega un documento real (PDF o página legible) y que
       no es demasiado grande para analizarlo. Si no, la fuente no vale para ese item.
    """
    if not url:
        return False
    path = url.lower().split("?")[0]
    if path.endswith((".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip", ".csv")):
        return False
    try:
        h = requests.head(url, headers=BROWSER_HEADERS, timeout=15, allow_redirects=True)
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
             tipo_doc="Documento desclasificado (PDF)"):
    """Construye el dict de un documento a partir de un PDF oficial."""
    confianza = "ALTO" if fiabilidad == "Alta" else "MEDIO"
    return {
        "id": _doc_id(prefijo, pdf_url),
        "titulo": titulo,
        "titulo_original": titulo,
        "fecha_documento": datetime.now().strftime("%Y-%m-%d"),
        "fecha_acceso": datetime.now().strftime("%Y-%m-%d"),
        "organismo": [nombre],
        "tipo_documento": tipo_doc,
        "clasificacion_original": "Desclasificado (variable por documento)",
        "idioma_original": "Inglés",
        "url_fuente": pdf_url,
        "url_noticia": pdf_url,
        "estado_desclasificacion": "DESCLASIFICADO OFICIALMENTE",
        "verificado": "Oficial",
        "fuente_fiabilidad": fiabilidad,
        "verificacion_autenticidad": f"Documento PDF descargable publicado por {nombre}.",
        "pais": pais,
        "categorias": categorias,
        "resumen_ejecutivo": f"[Pendiente de análisis con IA] Documento desclasificado disponible "
                             f"en {nombre}. Pulsa 'Resumir con IA' o 'Descargar informe PDF' "
                             f"para leer su contenido.",
        "puntos_clave": [
            f"Fuente: {nombre}",
            f"Documento (PDF): {pdf_url}",
            "Contenido pendiente de análisis con IA.",
        ],
        "implicaciones": "Pendiente de análisis. Documento descargable; usa la IA para extraer su contenido.",
        "nivel_confianza": confianza,
        "razon_confianza": f"Documento oficial descargable de {nombre} (fiabilidad {fiabilidad}).",
        "num_documentos": "1 documento (PDF)",
    }


# ---------------------------------------------------------------------------
# Scraper genérico: PDFs enlazados en una página oficial
# ---------------------------------------------------------------------------

def scrape_pdf_page(nombre, url, categorias, pais, fiabilidad, max_pdfs):
    r = _get(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    docs, vistos = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        full = urljoin(url, href)
        if full in vistos:
            continue
        vistos.add(full)
        nombre_archivo = full.rstrip("/").split("/")[-1]
        etiqueta = _clean_text(a.get_text()) or nombre_archivo
        titulo = f"{nombre} — {etiqueta[:90]}"
        docs.append(_doc_pdf(nombre, titulo, full, categorias, pais, fiabilidad, "PDF"))
        if len(docs) >= max_pdfs:
            break
    return docs


# ---------------------------------------------------------------------------
# archive.org: documentos desclasificados alojados (API de metadatos)
# ---------------------------------------------------------------------------

def scrape_archive_org(nombre, identifier, categorias, pais, fiabilidad, max_pdfs):
    r = _get(f"https://archive.org/metadata/{identifier}")
    if not r:
        return []
    try:
        meta = r.json()
    except Exception:
        return []
    docs = []
    for f in meta.get("files", []):
        name = f.get("name", "")
        if not name.lower().endswith(".pdf"):
            continue
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
                             tipo_doc="Documento desclasificado (archive.org, PDF)"))
        if len(docs) >= max_pdfs:
            break
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
                     tipo_doc="Lista de publicaciones desclasificadas (PDF)")
        docs.append(d)
    return docs


# ---------------------------------------------------------------------------
# FBI Vault: archivos desclasificados (RSS; cada item es un PDF)
# ---------------------------------------------------------------------------

def scrape_fbi_vault(max_items):
    if not HAS_FEEDPARSER:
        log.warning("  feedparser no instalado; se omite el FBI Vault.")
        return []
    parsed = feedparser.parse(config.FBI_VAULT_RSS, agent=BROWSER_HEADERS["User-Agent"])
    docs = []
    for entry in parsed.entries[:max_items]:
        titulo = _clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not titulo or not link:
            continue
        # En el FBI Vault, la URL del PDF es la del item sin el sufijo '/view'.
        pdf_url = re.sub(r"/view/?$", "", link)
        d = _doc_pdf("FBI Vault", f"FBI Vault — {titulo}", pdf_url,
                     ["Inteligencia y espionaje", "Corrupción y gobernanza"],
                     "EE. UU.", "Alta", "FBI",
                     tipo_doc="Archivo desclasificado del FBI (PDF)")
        docs.append(d)
    return docs


# ---------------------------------------------------------------------------
# Coordinador principal
# ---------------------------------------------------------------------------

def _ingerir(nombre, docs):
    """Inserta solo los documentos descargables. Devuelve nº de nuevos."""
    nuevos = 0
    descartados = 0
    for d in docs:
        if not _es_descargable(d["url_fuente"]):
            descartados += 1
            continue
        if database.insert_document(d):
            nuevos += 1
    estado = "OK"
    detalle = f"{descartados} descartados (no descargables)" if descartados else ""
    database.log_update(nombre, len(docs), nuevos, estado, detalle)
    log.info(f"  {nombre}: {len(docs)} encontrados, {nuevos} nuevos, {descartados} descartados")
    return nuevos


def run_update():
    log.info("=== Iniciando actualización de documentos ===")
    total_nuevos = 0

    # 1) Páginas con PDFs (JFK, etc.)
    for nombre, url, cats, pais, fiab, maxp in config.PDF_PAGES:
        log.info(f"Página PDF: {nombre}")
        try:
            total_nuevos += _ingerir(nombre, scrape_pdf_page(nombre, url, cats, pais, fiab, maxp))
        except Exception as e:
            log.error(f"  Error en {nombre}: {e}")
            database.log_update(nombre, 0, 0, "ERROR", str(e)[:200])

    # 2) archive.org (UFOs, MK-Ultra, y otros desclasificados conspiranoicos)
    for nombre, idf, cats, pais, fiab, maxp in getattr(config, "ARCHIVE_ORG_ITEMS", []):
        log.info(f"archive.org: {nombre}")
        try:
            total_nuevos += _ingerir(nombre, scrape_archive_org(nombre, idf, cats, pais, fiab, maxp))
        except Exception as e:
            log.error(f"  Error en {nombre}: {e}")
            database.log_update(nombre, 0, 0, "ERROR", str(e)[:200])

    # 3) NARA NDC
    if config.SCRAPE_NARA_NDC:
        log.info("NARA NDC")
        try:
            total_nuevos += _ingerir("NARA NDC", scrape_nara_ndc())
        except Exception as e:
            log.error(f"  Error en NARA NDC: {e}")
            database.log_update("NARA NDC", 0, 0, "ERROR", str(e)[:200])

    # 3) FBI Vault
    if config.FBI_VAULT_ENABLED:
        log.info("FBI Vault")
        try:
            total_nuevos += _ingerir("FBI Vault", scrape_fbi_vault(config.FBI_VAULT_MAX))
        except Exception as e:
            log.error(f"  Error en FBI Vault: {e}")
            database.log_update("FBI Vault", 0, 0, "ERROR", str(e)[:200])

    log.info(f"=== Actualización completada. Total nuevos: {total_nuevos} ===")

    # Traducción automática de títulos al español (una sola llamada para todos)
    if total_nuevos > 0:
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

    # Análisis automático con IA de los documentos pendientes (si el motor está disponible)
    if config.AUTO_ANALYZE_NEW and total_nuevos > 0:
        try:
            import llm
            if llm.disponible():
                pendientes = database.get_pending_analysis(limit=config.ANALYZE_BATCH)
                analizados = 0
                for doc in pendientes:
                    res = llm.analizar_documento(doc)
                    if res.get("ok"):
                        database.update_analysis(
                            doc["id"], res["resumen_ejecutivo"], res["puntos_clave"],
                            res["implicaciones"], res["nivel_confianza"]
                        )
                        analizados += 1
                log.info(f"  IA: {analizados} documento(s) resumido(s) automáticamente.")
                database.log_update(f"IA auto-análisis ({llm.backend()})", len(pendientes), analizados, "OK")
            else:
                log.info("  IA: motor no disponible; se omite el resumen automático.")
        except Exception as e:
            log.error(f"  Error en auto-análisis IA: {e}")
            database.log_update("IA auto-análisis", 0, 0, "ERROR", str(e)[:200])

    return total_nuevos


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    database.init_db()
    database.seed_initial_data()
    run_update()
