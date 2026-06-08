"""
Capa de modelo de lenguaje INTERCAMBIABLE.

Permite usar como "cerebro":
  - "gemini"   : API gratuita de Gemini (límite diario).
  - "lmstudio" : tu LM Studio local (sin límites, compatible con OpenAI).

Se elige en config.LLM_BACKEND. El resto del programa llama a generar_json()
sin saber qué motor hay detrás.
"""

import json
import logging

import requests

import config
import gemini

log = logging.getLogger(__name__)


def backend():
    return getattr(config, "LLM_BACKEND", "gemini").lower()


def disponible():
    """Indica si el motor configurado está listo para usarse."""
    if backend() == "lmstudio":
        try:
            r = requests.get(f"{config.LMSTUDIO_URL}/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
    return gemini.hay_clave()


def nombre_motor():
    if backend() == "lmstudio":
        return f"LM Studio (local) · {config.LMSTUDIO_MODEL}"
    return f"Gemini · {config.GEMINI_MODEL}"


# ---------------------------------------------------------------------------
# LM Studio (servidor local compatible con OpenAI)
# ---------------------------------------------------------------------------

def _lmstudio_json(prompt, temperature):
    """Llama a LM Studio y devuelve el JSON parseado. Da errores claros y, si el
       modelo local devuelve un JSON roto/truncado, vuelve a generarlo una vez."""
    payload = {
        "model": config.LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": "/no_think\nResponde SIEMPRE en español y EXCLUSIVAMENTE "
             "con un objeto JSON válido, sin texto adicional, sin etiquetas y sin razonamiento."},
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
# API pública
# ---------------------------------------------------------------------------

def generar_json(prompt, temperature=0.7):
    """Pide al motor configurado una respuesta JSON. Devuelve {ok, data} o {ok:False, error}."""
    try:
        if backend() == "lmstudio":
            data = _lmstudio_json(prompt, temperature)
        else:
            raw = gemini._llamar_gemini([{"text": prompt}])
            data = gemini._parse_json(raw)
        return {"ok": True, "data": data}
    except Exception as e:
        log.warning(f"  LLM ({backend()}) error: {e}")
        return {"ok": False, "error": str(e)}


import re as _re


def _norm_nivel(valor, defecto="MEDIO"):
    m = _re.search(r"\b(ALTO|MEDIO|BAJO)\b", (valor or "").upper())
    return m.group(1) if m else defecto


def _contenido_para_local(doc):
    """Para LM Studio (sin visión): devuelve (texto, tipo, url) listo para el prompt."""
    tipo, dato, url = gemini.obtener_contenido(doc)
    if tipo == "pdf":
        texto = gemini.extraer_texto_pdf(dato)
        if not texto:
            texto = ("(El PDF parece escaneado y no se pudo extraer texto. Usa los metadatos "
                     "y di claramente que el análisis se basa en información limitada.)\n"
                     + (doc.get("resumen_ejecutivo", "") or ""))
            tipo = "none"
    elif tipo == "text":
        texto = dato
    else:
        texto = ("(No se pudo acceder al contenido. Usa solo los metadatos y dilo claramente.)\n"
                 + (doc.get("resumen_ejecutivo", "") or "") + " "
                 + " ".join(doc.get("puntos_clave", []) or []))
    return texto, tipo, url


# ---------------------------------------------------------------------------
# API de alto nivel: funciona con CUALQUIER motor (Gemini o LM Studio)
# ---------------------------------------------------------------------------

def analizar_documento(doc):
    """Resumen ejecutivo de un documento. Gemini lee el PDF con visión;
       LM Studio usa el texto extraído del PDF."""
    if backend() == "gemini":
        return gemini.analizar_documento(doc)

    texto, tipo, url = _contenido_para_local(doc)
    prompt = gemini.PROMPT.format(
        titulo=doc.get("titulo", ""),
        organismo=", ".join(doc.get("organismo", []) or []),
        pais=doc.get("pais", ""),
        estado=doc.get("estado_desclasificacion", ""),
        url=url or doc.get("url_fuente", ""),
        contenido=texto,
    )
    r = generar_json(prompt, temperature=0.3)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    p = r["data"]
    return {
        "ok": True,
        "resumen_ejecutivo": (p.get("resumen_ejecutivo") or "").strip(),
        "puntos_clave": p.get("puntos_clave") or [],
        "implicaciones": (p.get("implicaciones") or "").strip(),
        "nivel_confianza": _norm_nivel(p.get("nivel_confianza"), doc.get("nivel_confianza") or "MEDIO"),
    }


def analizar_detallado(doc, tipo=None, dato=None, url=None):
    """Análisis profundo para el informe PDF, con cualquier motor.
       Si se pasa tipo/dato/url (ya descargado), se reutiliza (evita doble descarga)."""
    if backend() == "gemini":
        return gemini.analizar_detallado(doc, tipo, dato, url)

    # Modo local: reutilizar contenido si ya viene dado, si no descargar.
    if tipo is None:
        texto, tipo_real, url_real = _contenido_para_local(doc)
    else:
        url_real = url
        if tipo == "pdf":
            texto = gemini.extraer_texto_pdf(dato) or (
                "(PDF escaneado sin texto extraíble. Análisis basado en metadatos.)\n"
                + (doc.get("resumen_ejecutivo", "") or ""))
            tipo_real = tipo if texto else "none"
        elif tipo == "text":
            texto, tipo_real = dato, "text"
        else:
            texto = ("(No se pudo acceder al contenido.)\n"
                     + (doc.get("resumen_ejecutivo", "") or ""))
            tipo_real = "none"
    prompt = gemini.PROMPT_DETALLADO.format(
        titulo=doc.get("titulo", ""),
        organismo=", ".join(doc.get("organismo", []) or []),
        pais=doc.get("pais", ""),
        estado=doc.get("estado_desclasificacion", ""),
        url=url_real or doc.get("url_fuente", ""),
        contenido=texto,
    )
    r = generar_json(prompt, temperature=0.3)
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
        prompt = (
            "Traduce al ESPAÑOL natural y claro los siguientes títulos de documentos "
            "desclasificados. Mantén nombres propios, siglas y números tal cual. "
            "No traduzcas códigos ni identificadores. Devuelve EXCLUSIVAMENTE este JSON:\n"
            '{"traducciones": [{"id": "...", "titulo_es": "..."}]}\n\n'
            "TÍTULOS (formato: ID ||| título):\n" + lineas
        )
        r = generar_json(prompt, temperature=0.2)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error"), "traducciones": mapa}
        for t in r["data"].get("traducciones", []):
            if t.get("id") and t.get("titulo_es"):
                mapa[t["id"]] = t["titulo_es"].strip()
    return {"ok": True, "traducciones": mapa}
