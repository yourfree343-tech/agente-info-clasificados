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
import time
import random
import logging
import threading
from datetime import datetime
from urllib.parse import urlparse

import config
import database
import llm

log = logging.getLogger(__name__)


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


def _limpia(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

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
    """Elige un tema del banco semilla, prefiriendo los que aún no se han usado.
       Sustituye a la antigua llamada al LLM para 'elegir tema' (lenta y frágil en CPU)."""
    semillas = getattr(config, "DETECTIVE_TEMAS_SEMILLA", []) or ["una conspiración famosa"]
    ya = {(t or "").strip().lower() for t in database.get_temas_investigados(40)}
    frescas = [s for s in semillas if s.strip().lower() not in ya]
    tema = random.choice(frescas or semillas)
    return tema, _busquedas_desde_tema(tema)


# ---------------------------------------------------------------------------
# Investigación
# ---------------------------------------------------------------------------

def investigar(tema=None):
    if not llm.disponible():
        return {"ok": False, "error": f"El motor LLM ({llm.backend()}) no está disponible. "
                f"Si usas LM Studio, abre la app, carga un modelo y arranca el servidor local."}

    # 1) Elegir tema y consultas. Antes esto gastaba una llamada extra al LLM
    #    (lenta en CPU y un punto de fallo más); ahora se deriva del banco de
    #    temas semilla, que ya da variedad y evita repetir lo ya investigado.
    if tema:
        busquedas = _busquedas_desde_tema(tema)
    else:
        tema, busquedas = _elegir_tema_local()

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
    categorias = getattr(config, "DETECTIVE_CATEGORIAS", ["Otras"])
    prompt_dossier = PROMPT_DOSSIER.format(
        tema=tema, contexto=contexto, categorias=" | ".join(categorias))
    r2 = llm.generar_json(prompt_dossier, temperature=0.8)
    if not r2.get("ok"):
        return {"ok": False, "error": "No se pudo redactar el dossier: " + r2.get("error", "")}
    d = r2["data"]
    certeza = llm.norm_nivel(d.get("nivel_certeza"), "MEDIO")
    # Validar categoría contra la lista permitida
    categoria = (d.get("categoria") or "").strip()
    if categoria not in categorias:
        categoria = next((c for c in categorias if c.lower() in categoria.lower()), "Otras")

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
        "categoria": categoria,
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

_lock = threading.Lock()
_estado = {
    "en_curso": False,
    "tema": None,
    "desde": None,
    "ultimo_fin": None,
    "ultimo_titulo": None,
    "ultimo_error": None,
}


def estado_actual():
    """Copia del estado de la investigación en segundo plano (para la API/UI)."""
    return dict(_estado)


def _run(tema):
    try:
        res = investigar(tema)
        if res.get("ok"):
            _estado["ultimo_titulo"] = res["investigacion"].get("titulo")
            _estado["ultimo_error"] = None
        else:
            _estado["ultimo_error"] = res.get("error")
            log.info(f"  Detective: {res.get('error')}")
    except Exception as e:
        _estado["ultimo_error"] = str(e)
        log.error(f"  Detective error: {e}")
    finally:
        _estado["en_curso"] = False
        _estado["ultimo_fin"] = datetime.now().isoformat()
        _lock.release()


def lanzar(tema=None):
    """Inicia una investigación en segundo plano si no hay otra en curso.
       Devuelve (iniciada: bool, mensaje: str). NO bloquea."""
    if not _lock.acquire(blocking=False):
        return False, "Ya hay una investigación en curso; espera a que termine."
    _estado.update(en_curso=True, tema=tema, desde=datetime.now().isoformat(),
                   ultimo_error=None)
    threading.Thread(target=_run, args=(tema,), daemon=True).start()
    return True, (f"Investigando: {tema}" if tema else "Investigación iniciada.")


def investigar_auto():
    """Entrada para el planificador: lanza una investigación si no hay otra activa."""
    iniciada, msg = lanzar(None)
    if not iniciada:
        log.info(f"  Detective auto: {msg}")
