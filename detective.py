"""
Detective conspiranoico autónomo.

Flujo:
  1. Elige un tema jugoso (o usa el que le des).
  2. Busca en internet (DuckDuckGo) — funciona con cualquier motor LLM.
  3. Sintetiza un "dossier" multi-rol (investigador, conspiranoico, analista,
     detective jefe) en tono inmersivo PERO etiquetando qué es especulación.
  4. Guarda el dossier en una tabla SEPARADA (no se mezcla con los desclasificados).

Motor LLM intercambiable (Gemini / LM Studio) vía llm.py.
"""

import re
import html
import logging
from datetime import datetime

import config
import database
import llm

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Búsqueda web (librería ddgs; gestiona DuckDuckGo correctamente)
# ---------------------------------------------------------------------------

def buscar_web(query, n=5):
    """Devuelve [{titulo, url, snippet}]. Vacío si falla."""
    try:
        from ddgs import DDGS
    except ImportError:
        log.warning("  Falta la librería 'ddgs' (pip install ddgs).")
        return []
    out = []
    try:
        for x in DDGS().text(query, max_results=n):
            titulo = _limpia(x.get("title", ""))
            url = x.get("href", "") or x.get("url", "")
            snippet = _limpia(x.get("body", ""))
            if titulo and url:
                out.append({"titulo": titulo, "url": url, "snippet": snippet})
    except Exception as e:
        log.warning(f"  Búsqueda fallida '{query}': {e}")
    return out


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
            if url:
                out.append({"url": url, "thumb": thumb, "titulo": titulo, "origen": origen})
            if len(out) >= n:
                break
    except Exception as e:
        log.warning(f"  Búsqueda de imágenes fallida '{query}': {e}")
    return out


def _limpia(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PROMPT_TEMA = """Estamos en el AÑO 2026. Eres un detective conspiranoico autónomo. Elige UN tema
intrigante y ACTUAL para investigar hoy: conspiraciones, documentos desclasificados
recientes, símbolos, élites, OVNIs/UAP, sociedades secretas (Illuminati, masonería),
portadas de la revista The Economist (especialmente The World Ahead 2026),
operaciones encubiertas, MK-Ultra, Project Stargate, etc. Varía el tema, sé original
y prefiere asuntos recientes (2024-2026) cuando proceda.

Devuelve EXCLUSIVAMENTE este JSON:
{"tema": "el tema elegido en una frase", "busquedas": ["3 a 5 consultas de búsqueda en internet para investigarlo (incluye el año 2026 si es relevante)"]}"""

PROMPT_DOSSIER = """Estamos en el AÑO 2026. Eres un PANEL de investigación con cuatro roles que colaboran:
🕵️ Investigador (recopila hechos y fuentes), 👁️ Conspiranoico (propone conexiones e hipótesis),
🧠 Analista (separa lo PROBADO de lo ESPECULATIVO) y 📕 Detective Jefe (concluye).

TEMA A INVESTIGAR: {tema}

RESULTADOS DE BÚSQUEDA EN INTERNET (úsalos como base, cita las URLs):
{contexto}

Escribe en ESPAÑOL, con tono INMERSIVO y enganchón de detective conspiranoico, PERO
etiquetando con honestidad qué es hecho verificado y qué es pura especulación.
No presentes teorías como verdades. No inventes fuentes: usa solo las de arriba.

Devuelve EXCLUSIVAMENTE este JSON:
{{
  "titulo": "título llamativo del caso",
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
# Investigación
# ---------------------------------------------------------------------------

def investigar(tema=None):
    if not llm.disponible():
        return {"ok": False, "error": f"El motor LLM ({llm.backend()}) no está disponible. "
                f"Si usas LM Studio, abre la app, carga un modelo y arranca el servidor local."}

    # 1) Elegir tema y consultas (si no se da tema)
    if tema:
        busquedas = [tema, f"{tema} documentos", f"{tema} conspiración"]
    else:
        r = llm.generar_json(PROMPT_TEMA, temperature=0.95)
        if not r.get("ok"):
            return {"ok": False, "error": "No se pudo elegir tema: " + r.get("error", "")}
        tema = (r["data"].get("tema") or "Misterio sin título").strip()
        busquedas = r["data"].get("busquedas") or [tema]

    # 2) Buscar en internet
    busquedas = busquedas[:config.DETECTIVE_MAX_BUSQUEDAS]
    resultados, vistos = [], set()
    for q in busquedas:
        for res in buscar_web(q, config.DETECTIVE_RESULTADOS_POR_BUSQUEDA):
            if res["url"] in vistos:
                continue
            vistos.add(res["url"])
            resultados.append(res)

    if not resultados:
        return {"ok": False, "error": "No se obtuvieron resultados de búsqueda en internet."}

    # Contexto acotado (en CPU, menos texto = mucho más rápido).
    contexto = "\n".join(
        f"- {r['titulo']} ({r['url']})\n  {r['snippet'][:200]}" for r in resultados[:10]
    )

    # 3) Sintetizar el dossier
    r2 = llm.generar_json(PROMPT_DOSSIER.format(tema=tema, contexto=contexto), temperature=0.8)
    if not r2.get("ok"):
        return {"ok": False, "error": "No se pudo redactar el dossier: " + r2.get("error", "")}
    d = r2["data"]
    m = re.search(r"ALTO|MEDIO|BAJO", (d.get("nivel_certeza") or "MEDIO").upper())
    certeza = m.group(0) if m else "MEDIO"

    # Unir fuentes del modelo con las URLs reales encontradas
    fuentes = d.get("fuentes") or []
    for r in resultados:
        if r["url"] not in fuentes:
            fuentes.append(r["url"])

    # Imágenes relacionadas (portadas, fotos, símbolos del tema investigado).
    imagenes = []
    n_imgs = getattr(config, "DETECTIVE_IMAGENES", 4)
    if n_imgs > 0:
        consulta_img = (d.get("titulo") or tema)
        imagenes = buscar_imagenes(consulta_img, n=n_imgs)

    inv = {
        "id": "INV-" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "fecha": datetime.now().isoformat(),
        "tema": tema,
        "titulo": d.get("titulo") or tema,
        "gancho": d.get("gancho", ""),
        "hechos_verificados": d.get("hechos_verificados", []),
        "hipotesis": d.get("hipotesis", []),
        "especulacion": d.get("especulacion", []),
        "conexiones": d.get("conexiones", []),
        "veredicto": d.get("veredicto", ""),
        "nivel_certeza": certeza,
        "fuentes": fuentes[:25],
        "motor": llm.nombre_motor(),
        "imagenes": imagenes,
    }
    database.insert_investigacion(inv)
    log.info(f"  Detective: nuevo dossier '{inv['titulo'][:50]}' "
             f"({len(resultados)} fuentes, {len(imagenes)} imágenes).")
    return {"ok": True, "investigacion": inv}


def investigar_auto():
    """Entrada para el planificador (investiga solo, captura errores)."""
    try:
        res = investigar()
        if not res.get("ok"):
            log.info(f"  Detective auto: {res.get('error')}")
    except Exception as e:
        log.error(f"  Detective auto error: {e}")
