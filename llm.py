"""
Capa de modelo de lenguaje INTERCAMBIABLE.

Permite usar como "cerebro":
  - "gemini"     : API gratuita de Gemini (límite diario).
  - "lmstudio"   : tu LM Studio local (sin límites, compatible con OpenAI).
  - "openrouter" : API de OpenRouter (modelo en la nube, compatible con OpenAI).

Se elige en config.LLM_BACKEND. El resto del programa llama a generar_json()
sin saber qué motor hay detrás.
"""

import re
import time
import base64
import logging

import requests

import config
import gemini

log = logging.getLogger(__name__)

SISTEMA_JSON = ("Responde SIEMPRE en español y EXCLUSIVAMENTE con un objeto JSON válido, "
                "sin texto adicional, sin etiquetas y sin razonamiento.")


def backend():
    return getattr(config, "LLM_BACKEND", "gemini").lower()


def es_local():
    """True si el motor corre en esta máquina (lento en CPU): la interfaz avisa de la espera."""
    return backend() == "lmstudio"


def disponible():
    """Indica si el motor configurado está listo para usarse."""
    if backend() == "lmstudio":
        try:
            r = requests.get(f"{config.LMSTUDIO_URL}/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
    if backend() == "openrouter":
        return bool(getattr(config, "OPENROUTER_API_KEY", ""))
    return gemini.hay_clave()


def mensaje_no_disponible():
    """Qué hacer para activar el motor configurado (texto para la interfaz)."""
    b = backend()
    if b == "lmstudio":
        return ("El motor LM Studio no responde. Abre LM Studio, carga un modelo y arranca "
                "el servidor local (pestaña Developer → Start Server).")
    if b == "openrouter":
        return "Falta la clave de OpenRouter: pon OPENROUTER_API_KEY en config.py."
    return "Falta la clave de Gemini: pon GEMINI_API_KEY en config.py."


def nombre_motor():
    if backend() == "lmstudio":
        return f"LM Studio (local) · {config.LMSTUDIO_MODEL}"
    if backend() == "openrouter":
        return f"OpenRouter · {config.OPENROUTER_MODEL}"
    return f"Gemini · {config.GEMINI_MODEL}"


def vision_disponible():
    """Hay un modelo con visión configurado para leer PDFs escaneados (solo OpenRouter;
       Gemini ya lee los PDF de forma nativa)."""
    return (backend() == "openrouter" and bool(getattr(config, "OPENROUTER_API_KEY", ""))
            and bool(getattr(config, "OPENROUTER_VISION_MODEL", "")))


# ---------------------------------------------------------------------------
# LM Studio (servidor local compatible con OpenAI)
# ---------------------------------------------------------------------------

def _lmstudio_json(prompt, temperature):
    """Llama a LM Studio y devuelve el JSON parseado. Da errores claros y, si el
       modelo local devuelve un JSON roto/truncado, vuelve a generarlo una vez."""
    payload = {
        "model": config.LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": "/no_think\n" + SISTEMA_JSON},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        # Margen suficiente para que el dossier no se trunque a mitad del JSON.
        "max_tokens": getattr(config, "LMSTUDIO_MAX_TOKENS", 2500),
        "stream": False,
        # Desactiva el "pensamiento" de Qwen3 (mucho más rápido en CPU y salida limpia).
        "chat_template_kwargs": {"enable_thinking": False},
    }
    # Hasta 2 intentos: el modelo local a veces emite JSON incompleto o con ruido.
    for intento in range(2):
        try:
            r = requests.post(f"{config.LMSTUDIO_URL}/chat/completions",
                              json=payload, timeout=config.LMSTUDIO_TIMEOUT)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"No se pudo conectar con LM Studio en {config.LMSTUDIO_URL}. "
                               f"¿Está arrancado el servidor local y cargado el modelo? ({e})")
        except requests.exceptions.Timeout:
            raise RuntimeError(f"LM Studio no respondió en {config.LMSTUDIO_TIMEOUT}s. "
                               f"El modelo es muy lento en CPU; sube LMSTUDIO_TIMEOUT en config.py "
                               f"o usa un modelo más pequeño/GPU.")
        if r.status_code != 200:
            raise RuntimeError(f"LM Studio HTTP {r.status_code}: {r.text[:200]}")
        contenido = r.json()["choices"][0]["message"]["content"]
        try:
            return gemini._parse_json(contenido)
        except Exception:
            if intento == 0:
                log.info("  LM Studio devolvió un JSON no válido; regenerando una vez...")
                continue
            raise RuntimeError(f"LM Studio no devolvió un JSON parseable: {(contenido or '')[:200]}")


# ---------------------------------------------------------------------------
# OpenRouter (API en la nube compatible con OpenAI)
# ---------------------------------------------------------------------------

# Errores transitorios en los que merece la pena esperar y reintentar.
_OR_TRANSITORIOS = {408, 429, 500, 502, 503, 504}


def _openrouter_post(payload):
    """POST a OpenRouter con reintentos y espera creciente ante errores transitorios
       (límite de ritmo, proveedor saturado). Respeta Retry-After si viene."""
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        # Cabeceras de atribución que recomienda OpenRouter (opcionales, no envían datos personales).
        "HTTP-Referer": f"http://localhost:{getattr(config, 'PORT', 5790)}",
        "X-Title": "Agente Info Clasificados",
    }
    esperas = (4, 12, 30)
    for intento in range(len(esperas) + 1):
        try:
            r = requests.post(f"{config.OPENROUTER_URL}/chat/completions",
                              headers=headers, json=payload, timeout=config.OPENROUTER_TIMEOUT)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"No se pudo conectar con OpenRouter. ¿Hay conexión a internet? ({e})")
        except requests.exceptions.Timeout:
            if intento < len(esperas):
                log.info(f"  OpenRouter tardó más de {config.OPENROUTER_TIMEOUT}s; reintento...")
                continue
            raise RuntimeError(f"OpenRouter no respondió en {config.OPENROUTER_TIMEOUT}s.")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            raise RuntimeError("OpenRouter rechazó la clave de API (401). Revisa OPENROUTER_API_KEY en config.py.")
        if r.status_code == 402:
            raise RuntimeError("OpenRouter: la cuenta no tiene saldo para este modelo (402). "
                               "Recarga créditos o usa un modelo gratuito (terminado en ':free').")
        if r.status_code in _OR_TRANSITORIOS and intento < len(esperas):
            espera = esperas[intento]
            ra = r.headers.get("Retry-After", "")
            if ra.isdigit():
                espera = min(int(ra), 60)
            log.info(f"  OpenRouter HTTP {r.status_code}; reintento en {espera}s...")
            time.sleep(espera)
            continue
        if r.status_code == 429:
            raise RuntimeError("OpenRouter: límite de peticiones alcanzado (429). Prueba de nuevo en unos minutos.")
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError("OpenRouter no respondió tras varios reintentos.")


def _openrouter_json(prompt, temperature, imagenes=None):
    """Llama a OpenRouter y devuelve el JSON parseado. Mismo contrato que _lmstudio_json:
       errores claros y una regeneración si el modelo devuelve JSON roto/truncado.
       Con `imagenes` (JPEG en bytes) usa el modelo de visión configurado."""
    if not getattr(config, "OPENROUTER_API_KEY", ""):
        raise RuntimeError("No hay clave de OpenRouter configurada en config.py (OPENROUTER_API_KEY).")
    modelo = config.OPENROUTER_MODEL
    contenido_usuario = prompt
    if imagenes:
        modelo = getattr(config, "OPENROUTER_VISION_MODEL", "") or modelo
        contenido_usuario = [{"type": "text", "text": prompt}] + [
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")}}
            for b in imagenes
        ]
    max_tokens = getattr(config, "OPENROUTER_MAX_TOKENS", 2500)
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": SISTEMA_JSON},
            {"role": "user", "content": contenido_usuario},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if getattr(config, "OPENROUTER_JSON_MODE", True):
        # Pide JSON estricto a los proveedores que lo soportan (el resto lo ignora).
        payload["response_format"] = {"type": "json_object"}
    esfuerzo = getattr(config, "OPENROUTER_REASONING", "low")
    if esfuerzo:
        # En modelos que "razonan" (gpt-oss), el razonamiento gasta del mismo max_tokens:
        # con esfuerzo bajo queda sitio para el JSON y responde antes.
        payload["reasoning"] = {"effort": esfuerzo, "exclude": True}

    for intento in range(2):
        data = _openrouter_post(payload)
        try:
            eleccion = data["choices"][0]
            contenido = eleccion["message"].get("content") or ""
            fin = eleccion.get("finish_reason")
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"Respuesta inesperada de OpenRouter: {str(data)[:200]}")
        try:
            return gemini._parse_json(contenido)
        except Exception:
            if intento == 0:
                if fin == "length":
                    # Se quedó sin tokens a mitad: una vez más con margen doble.
                    payload["max_tokens"] = max_tokens * 2
                log.info("  OpenRouter devolvió un JSON no válido; regenerando una vez...")
                continue
            raise RuntimeError(f"OpenRouter no devolvió un JSON parseable: {(contenido or '')[:200]}")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def generar_json(prompt, temperature=0.7, imagenes=None):
    """Pide al motor configurado una respuesta JSON. Devuelve {ok, data} o {ok:False, error}.
       `imagenes` solo se usa con OpenRouter + OPENROUTER_VISION_MODEL."""
    try:
        if backend() == "lmstudio":
            data = _lmstudio_json(prompt, temperature)
        elif backend() == "openrouter":
            data = _openrouter_json(prompt, temperature, imagenes if vision_disponible() else None)
        else:
            raw = gemini._llamar_gemini([{"text": prompt}], temperature=temperature)
            data = gemini._parse_json(raw)
        if not isinstance(data, dict):
            raise RuntimeError("El motor devolvió JSON, pero no un objeto.")
        return {"ok": True, "data": data}
    except Exception as e:
        log.warning(f"  LLM ({backend()}) error: {e}")
        return {"ok": False, "error": str(e)}


def _norm_nivel(valor, defecto="MEDIO"):
    m = re.search(r"\b(ALTO|MEDIO|BAJO)\b", (valor or "").upper())
    return m.group(1) if m else defecto


# Alias público: lo usan otros módulos (p. ej. detective.py) para no repetir el regex.
norm_nivel = _norm_nivel

AVISO_SIN_CONTENIDO = ("(No se pudo acceder al contenido del documento. Usa solo los metadatos "
                       "y deja claro que el análisis se basa en información limitada.)\n")

RESUMEN_SIN_TEXTO = ("No se ha podido leer el contenido de este documento: es un PDF escaneado sin "
                     "capa de texto o la fuente no permitió descargarlo. Ábrelo desde su enlace "
                     "original para consultarlo.")


def _contenido_para_local(doc, tipo=None, dato=None, url=None):
    """Para motores sin lectura nativa de PDF (LM Studio, OpenRouter).
       Devuelve (texto, tipo_real, url, imagenes). tipo_real es 'pdf', 'text',
       'imagenes' (escaneado que se enviará a un modelo de visión) o 'none'."""
    if tipo is None:
        tipo, dato, url = gemini.obtener_contenido(doc)
    imagenes = []
    texto = ""
    if tipo == "pdf":
        texto = gemini.extraer_texto_pdf(dato)
        if not texto:
            # PDF escaneado: primero el OCR gratuito de archive.org; si no, visión (opcional).
            texto = gemini.texto_ocr_archive_org(url or doc.get("url_fuente"))
        if not texto and vision_disponible():
            imagenes = gemini.paginas_como_imagenes(
                dato, n=getattr(config, "OPENROUTER_VISION_PAGINAS", 4))
            if imagenes:
                texto = ("(Documento escaneado: se adjuntan como imágenes sus primeras páginas. "
                         "Léelas con atención y basa el análisis en lo que se ve en ellas.)")
                tipo = "imagenes"
        if not texto:
            tipo = "none"
    elif tipo == "text":
        texto = dato
    if tipo == "none":
        texto = AVISO_SIN_CONTENIDO + gemini.descripcion_fuente(doc)
    return texto, tipo, url, imagenes


# ---------------------------------------------------------------------------
# API de alto nivel: funciona con CUALQUIER motor (Gemini o LM Studio)
# ---------------------------------------------------------------------------

def _datos_prompt(doc, url, texto):
    return dict(
        titulo=doc.get("titulo", ""),
        organismo=", ".join(doc.get("organismo", []) or []),
        pais=doc.get("pais", ""),
        estado=doc.get("estado_desclasificacion", ""),
        url=url or doc.get("url_fuente", ""),
        contenido=texto,
    )


def analizar_documento(doc):
    """Resumen ejecutivo de un documento. Gemini lee el PDF con visión;
       LM Studio/OpenRouter usan el texto extraído (u OCR / visión si es escaneado).
       Si no hay nada que leer ni descripción de la fuente, no gasta una llamada al
       LLM: devuelve sin_texto=True con un aviso honesto en vez de un resumen inventado."""
    if backend() == "gemini":
        return gemini.analizar_documento(doc)

    texto, tipo, url, imagenes = _contenido_para_local(doc)
    if tipo == "none" and not gemini.descripcion_fuente(doc):
        return {
            "ok": True, "sin_texto": True,
            "resumen_ejecutivo": RESUMEN_SIN_TEXTO,
            "puntos_clave": [], "implicaciones": "",
            # La confianza es la de la fuente: no leer el PDF no la rebaja.
            "nivel_confianza": _norm_nivel(doc.get("nivel_confianza"), "MEDIO"),
        }
    prompt = gemini.PROMPT.format(**_datos_prompt(doc, url, texto))
    r = generar_json(prompt, temperature=0.3, imagenes=imagenes)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    p = r["data"]
    return {
        "ok": True,
        "sin_texto": False,
        "resumen_ejecutivo": (p.get("resumen_ejecutivo") or "").strip(),
        "puntos_clave": [str(x) for x in (p.get("puntos_clave") or []) if x],
        "implicaciones": (p.get("implicaciones") or "").strip(),
        "nivel_confianza": _norm_nivel(p.get("nivel_confianza"), doc.get("nivel_confianza") or "MEDIO"),
    }


def analizar_detallado(doc, tipo=None, dato=None, url=None):
    """Análisis profundo para el informe PDF, con cualquier motor.
       Si se pasa tipo/dato/url (ya descargado), se reutiliza (evita doble descarga)."""
    if backend() == "gemini":
        return gemini.analizar_detallado(doc, tipo, dato, url)

    texto, tipo_real, url_real, imagenes = _contenido_para_local(doc, tipo, dato, url)
    prompt = gemini.PROMPT_DETALLADO.format(**_datos_prompt(doc, url_real, texto))
    r = generar_json(prompt, temperature=0.3, imagenes=imagenes)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    p = r["data"]
    p["nivel_confianza"] = _norm_nivel(p.get("nivel_confianza"))
    p["ok"] = True
    p["_tipo_fuente"] = tipo_real
    return p


def traducir_titulos(items, lote=20):
    """Traduce títulos al español con cualquier motor."""
    if backend() == "gemini":
        return gemini.traducir_titulos(items, lote)

    if not items:
        return {"ok": True, "traducciones": {}}
    mapa = {}
    for i in range(0, len(items), lote):
        trozo = items[i:i + lote]
        lineas = "\n".join(f'{it["id"]} ||| {it["titulo"]}' for it in trozo)
        prompt = gemini.PROMPT_TRADUCIR + lineas
        r = generar_json(prompt, temperature=0.2)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error"), "traducciones": mapa}
        for t in r["data"].get("traducciones", []):
            if t.get("id") and t.get("titulo_es"):
                mapa[t["id"]] = t["titulo_es"].strip()
    return {"ok": True, "traducciones": mapa}
