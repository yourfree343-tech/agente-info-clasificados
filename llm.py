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
    payload = {
        "model": config.LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": "/no_think\nResponde SIEMPRE en español y EXCLUSIVAMENTE "
             "con un objeto JSON válido, sin texto adicional, sin etiquetas y sin razonamiento."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "stream": False,
        # Desactiva el "pensamiento" de Qwen3 (mucho más rápido en CPU y salida limpia).
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = requests.post(f"{config.LMSTUDIO_URL}/chat/completions",
                      json=payload, timeout=config.LMSTUDIO_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"LM Studio HTTP {r.status_code}: {r.text[:200]}")
    contenido = r.json()["choices"][0]["message"]["content"]
    return gemini._parse_json(contenido)


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
