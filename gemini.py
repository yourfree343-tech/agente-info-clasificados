"""
Análisis de documentos con la API gratuita de Gemini (Google AI Studio).

Por cada documento:
  1. Intenta descargar el contenido real de su URL.
  2. Envía ese contenido (o, si falla, los metadatos) a Gemini.
  3. Recibe un resumen en español: resumen ejecutivo, puntos clave e implicaciones.

Sin clave configurada, las funciones devuelven un aviso claro y no fallan.
"""

import re
import html
import json
import time
import base64
import logging

import requests
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF, para recortar PDFs grandes
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

import config

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Cabeceras de navegador real: reducen los bloqueos 403 de muchos sitios .gov
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

MAX_PDF_BYTES = 18 * 1024 * 1024   # límite razonable para enviar el PDF inline
MAX_TEXT_CHARS = 12000

PROMPT = """Eres un analista de documentos desclasificados. Te doy información de un documento
oficial (título, fuente y, si está disponible, su contenido). Redacta un análisis en
ESPAÑOL claro y profesional. No inventes datos: si el contenido es limitado, dilo.

Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma exacta:
{{
  "resumen_ejecutivo": "3 a 6 frases que expliquen de qué trata el documento",
  "puntos_clave": ["entre 5 y 10 viñetas concretas"],
  "implicaciones": "2 a 4 frases sobre su importancia política, legal, histórica o de seguridad",
  "nivel_confianza": "ALTO | MEDIO | BAJO según lo fiable y completa que sea la información"
}}

DATOS DEL DOCUMENTO:
Título: {titulo}
Fuente / organismo: {organismo}
País: {pais}
Estado: {estado}
URL: {url}

CONTENIDO (puede estar incompleto o vacío):
\"\"\"
{contenido}
\"\"\"
"""


PROMPT_DETALLADO = """Eres un analista experto en documentos desclasificados. Te entrego un documento
oficial (como PDF adjunto o como texto). Tu tarea es leerlo a fondo y extraer LA INFORMACIÓN
IMPORTANTE QUE CONTIENE, no solo describir de qué trata. Trabaja en ESPAÑOL claro y profesional.
No inventes nada: si algo no está en el documento, no lo incluyas. Mantén nombres propios,
siglas y términos técnicos en su forma original.

Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma exacta:
{{
  "titulo_informe": "título descriptivo del informe",
  "contexto": "1 párrafo: qué es el documento, su origen y por qué importa",
  "hechos_clave": ["8 a 15 hechos CONCRETOS extraídos del documento: nombres, fechas, lugares, cifras, decisiones, operaciones"],
  "revelaciones": ["lo más importante, novedoso o sensible que revela el documento (3 a 8 puntos)"],
  "datos_concretos": ["personas, organismos, fechas, lugares, números de expediente, programas mencionados"],
  "citas_textuales": [{{"cita": "frase textual relevante del documento", "ubicacion": "página o sección si se sabe"}}],
  "implicaciones": "2 a 5 frases sobre el impacto político, legal, histórico o de seguridad",
  "nivel_confianza": "ALTO | MEDIO | BAJO según lo completo y legible que esté el documento"
}}

Cuantos más datos verificables extraigas del propio documento, mejor.

DATOS DEL DOCUMENTO:
Título: {titulo}
Fuente / organismo: {organismo}
País: {pais}
Estado: {estado}
URL: {url}

CONTENIDO (puede estar incompleto o vacío):
\"\"\"
{contenido}
\"\"\"
"""


def traducir_titulos(items, lote=20):
    """Traduce al español una lista de títulos. items: [{'id','titulo'}].
       Devuelve {'ok':True, 'traducciones': {id: titulo_es}} (en una o pocas llamadas).
    """
    if not hay_clave():
        return {"ok": False, "error": "No hay clave de Gemini configurada en config.py."}
    if not items:
        return {"ok": True, "traducciones": {}}

    mapa = {}
    for i in range(0, len(items), lote):
        trozo = items[i:i + lote]
        lineas = "\n".join(f'{it["id"]} ||| {it["titulo"]}' for it in trozo)
        prompt = (
            "Traduce al ESPAÑOL natural y claro los siguientes títulos de documentos "
            "desclasificados. Mantén nombres propios, siglas y números tal cual. "
            "No traduzcas códigos ni identificadores. Devuelve EXCLUSIVAMENTE este JSON:\n"
            '{"traducciones": [{"id": "...", "titulo_es": "..."}]}\n\n'
            "TÍTULOS (formato: ID ||| título):\n" + lineas
        )
        try:
            raw = _llamar_gemini([{"text": prompt}])
            parsed = _parse_json(raw)
            for t in parsed.get("traducciones", []):
                if t.get("id") and t.get("titulo_es"):
                    mapa[t["id"]] = t["titulo_es"].strip()
        except Exception as e:
            log.warning(f"  Error traduciendo títulos: {e}")
            return {"ok": False, "error": str(e), "traducciones": mapa}
    return {"ok": True, "traducciones": mapa}


def analizar_detallado(doc, tipo=None, dato=None, url=None):
    """Análisis profundo para el informe PDF. Si no se pasa el contenido, lo descarga.
       Devuelve dict con ok + campos detallados.
    """
    if not hay_clave():
        return {"ok": False, "error": "No hay clave de Gemini configurada en config.py."}

    if tipo is None:
        tipo, dato, url = obtener_contenido(doc)

    if tipo == "pdf":
        contenido = "(Se adjunta el documento PDF original para que lo leas íntegramente.)"
    elif tipo == "text":
        contenido = dato
    else:
        contenido = "(No se pudo acceder al contenido. Usa solo estos metadatos y dilo claramente.)\n" + \
                    (doc.get("resumen_ejecutivo", "") or "") + " " + \
                    " ".join(doc.get("puntos_clave", []) or [])

    prompt = PROMPT_DETALLADO.format(
        titulo=doc.get("titulo", ""),
        organismo=", ".join(doc.get("organismo", []) or []),
        pais=doc.get("pais", ""),
        estado=doc.get("estado_desclasificacion", ""),
        url=url or doc.get("url_fuente", ""),
        contenido=contenido,
    )
    parts = _parts_desde_contenido(tipo, dato, prompt)

    try:
        raw = _llamar_gemini(parts)
        parsed = _parse_json(raw)
    except Exception as e:
        log.warning(f"  Error en análisis detallado de {doc.get('id')}: {e}")
        return {"ok": False, "error": str(e)}

    nc_raw = (parsed.get("nivel_confianza") or "").upper()
    m = re.search(r"\b(ALTO|MEDIO|BAJO)\b", nc_raw)
    parsed["nivel_confianza"] = m.group(1) if m else "MEDIO"
    parsed["ok"] = True
    parsed["_tipo_fuente"] = tipo
    return parsed


def hay_clave():
    return bool(config.GEMINI_API_KEY)


def _descargar(url):
    """Descarga una URL. Devuelve (tipo, dato):
       ("pdf", bytes) | ("text", str) | ("none", None).
    """
    if not url or not url.startswith("http"):
        return ("none", None)
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log.info(f"  No se pudo descargar {url}: {e}")
        return ("none", None)

    ctype = r.headers.get("Content-Type", "").lower()
    path = url.lower().split("?")[0]

    # PDF: se enviará directamente a Gemini, que lo lee de forma nativa.
    if "application/pdf" in ctype or path.endswith(".pdf"):
        contenido = r.content
        if len(contenido) > config.INLINE_PDF_SAFE_BYTES:
            recortado = _recortar_pdf(contenido)
            if recortado is None:
                log.info(f"  PDF demasiado grande y no se pudo recortar: {url}")
                return ("none", None)
            log.info(f"  PDF grande recortado a las primeras páginas ({url}).")
            contenido = recortado
        return ("pdf", contenido)

    # Formatos binarios que aún no sabemos leer (hojas de cálculo, Word, etc.).
    if path.endswith((".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip", ".csv")):
        return ("none", None)

    # HTML / texto plano / XML: extraemos el texto legible.
    es_textual = any(t in ctype for t in ("text/html", "text/plain", "xml")) or not ctype
    if es_textual:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
            tag.decompose()
        texto = html.unescape(re.sub(r"\s+", " ", soup.get_text(" "))).strip()
        # Validar que sea texto real y no binario mal decodificado.
        if texto and _ratio_imprimible(texto[:2000]) > 0.85:
            return ("text", texto[:MAX_TEXT_CHARS])

    return ("none", None)


def _ratio_imprimible(s):
    if not s:
        return 0.0
    imprimibles = sum(1 for ch in s if ch.isprintable() or ch in "\n\t ")
    return imprimibles / len(s)


def obtener_contenido(doc):
    """Descarga el documento probando url_fuente y luego url_noticia.
       Devuelve (tipo, dato, url_leida): tipo en {'pdf','text','none'}.
    """
    for url in (doc.get("url_fuente"), doc.get("url_noticia")):
        if not url:
            continue
        tipo, dato = _descargar(url)
        if tipo != "none":
            return (tipo, dato, url)
    return ("none", None, doc.get("url_fuente", ""))


def _parts_desde_contenido(tipo, dato, prompt):
    """Construye las 'parts' para Gemini: PDF inline si procede, o texto."""
    if tipo == "pdf":
        return [
            {"inline_data": {"mime_type": "application/pdf",
                             "data": base64.b64encode(dato).decode("ascii")}},
            {"text": prompt},
        ]
    return [{"text": prompt}]


def _recortar_pdf(pdf_bytes):
    """Reduce un PDF grande a sus primeras páginas hasta que quepa en el límite seguro.
       Devuelve los bytes recortados, o None si no se puede.
    """
    if not HAS_FITZ:
        return None
    try:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None
    limite = config.INLINE_PDF_SAFE_BYTES
    try:
        for n in (config.TRIM_PDF_PAGINAS, 15, 10, 6, 3, 1):
            n = min(n, src.page_count)
            out = fitz.open()
            out.insert_pdf(src, from_page=0, to_page=n - 1)
            b = out.tobytes(deflate=True, garbage=4)
            out.close()
            if len(b) <= limite:
                return b
    except Exception:
        return None
    finally:
        src.close()
    return None


def _llamar_gemini(parts):
    """parts: lista de partes (texto y/o inline_data) para la API de Gemini."""
    url = API_URL.format(model=config.GEMINI_MODEL)
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }
    # Reintentos ante saturación (503) o límite de ritmo (429), que son transitorios.
    r = None
    for intento in range(4):
        r = requests.post(
            url, params={"key": config.GEMINI_API_KEY}, json=payload, timeout=120,
        )
        if r.status_code == 200:
            break
        if r.status_code in (429, 503) and intento < 3:
            espera = 3 * (intento + 1)
            log.info(f"  Gemini {r.status_code} (saturado); reintento en {espera}s...")
            time.sleep(espera)
            continue
        break
    if r.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Respuesta inesperada de Gemini: {json.dumps(data)[:300]}")


def _parse_json(texto):
    """Extrae el JSON de la respuesta, tolerando razonamiento <think>, vallas de
       código y texto sobrante (típico de modelos locales como Qwen3)."""
    t = (texto or "").strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL | re.IGNORECASE).strip()
    t = re.sub(r"^```(json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def analizar_documento(doc):
    """Analiza un documento. Devuelve dict con ok + campos, o ok=False + error."""
    if not hay_clave():
        return {"ok": False, "error": "No hay clave de Gemini configurada en config.py."}

    # Intenta descargar el documento real: primero la fuente oficial, luego la noticia.
    tipo, dato = "none", None
    fuente_leida = ""
    for url in (doc.get("url_fuente"), doc.get("url_noticia")):
        if not url:
            continue
        tipo, dato = _descargar(url)
        if tipo != "none":
            fuente_leida = url
            break

    pdf_part = None
    if tipo == "pdf":
        contenido = "(Se adjunta el documento PDF original para que lo leas directamente.)"
        pdf_part = {
            "inline_data": {
                "mime_type": "application/pdf",
                "data": base64.b64encode(dato).decode("ascii"),
            }
        }
    elif tipo == "text":
        contenido = dato
    else:
        # No se pudo leer el documento: usar los metadatos como contexto, avisando.
        contenido = "(No se pudo acceder al contenido del documento. Usa solo los metadatos " \
                    "siguientes y deja claro que el resumen se basa en información limitada.)\n" + \
                    (doc.get("resumen_ejecutivo", "") or "") + " " + \
                    " ".join(doc.get("puntos_clave", []) or [])

    prompt = PROMPT.format(
        titulo=doc.get("titulo", ""),
        organismo=", ".join(doc.get("organismo", []) or []),
        pais=doc.get("pais", ""),
        estado=doc.get("estado_desclasificacion", ""),
        url=fuente_leida or doc.get("url_fuente", ""),
        contenido=contenido,
    )

    parts = [{"text": prompt}]
    if pdf_part:
        parts.insert(0, pdf_part)

    try:
        raw = _llamar_gemini(parts)
        parsed = _parse_json(raw)
    except Exception as e:
        log.warning(f"  Error analizando {doc.get('id')}: {e}")
        return {"ok": False, "error": str(e)}

    # El modelo a veces devuelve una frase entera; quedarnos solo con ALTO/MEDIO/BAJO.
    nc_raw = (parsed.get("nivel_confianza") or "").upper()
    m = re.search(r"\b(ALTO|MEDIO|BAJO)\b", nc_raw)
    nivel = m.group(1) if m else (doc.get("nivel_confianza") or "MEDIO").upper()

    return {
        "ok": True,
        "resumen_ejecutivo": (parsed.get("resumen_ejecutivo") or "").strip(),
        "puntos_clave": parsed.get("puntos_clave") or [],
        "implicaciones": (parsed.get("implicaciones") or "").strip(),
        "nivel_confianza": nivel,
    }
