"""
Análisis cruzado entre dossiers del detective: qué entidades (siglas, nombres propios)
se repiten en varios casos, y qué años se mencionan en los hechos verificados.

Heurística simple basada en regex (sin NLP): funciona con cualquier motor LLM porque
no depende de una llamada adicional, y el filtro "aparece en 2+ dossiers" descarta la
mayoría del ruido (una palabra capitalizada suelta no suele repetirse; un nombre propio
real —CIA, MK-Ultra, Bilderberg— sí).
"""

import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

import config
import database


# ---------------------------------------------------------------------------
# Calidad de las fuentes de un dossier: de qué tipo es cada URL citada.
# ---------------------------------------------------------------------------

TIPOS_FUENTE = {
    "oficial": "Oficial",
    "archivo": "Archivo documental",
    "referencia": "Referencia",
    "prensa": "Prensa",
    "web": "Web",
    "redes": "Redes / vídeo",
}

_ARCHIVOS = {"archive.org", "theblackvault.com", "nsarchive.gwu.edu", "wilsoncenter.org",
             "documentcloud.org", "muckrock.com", "wikileaks.org", "cryptome.org"}
_REFERENCIA = {"wikipedia.org", "britannica.com", "wikidata.org", "jstor.org", "doi.org",
               "nature.com", "science.org", "sciencedirect.com", "springer.com", "arxiv.org",
               "researchgate.net", "academia.edu", "history.com", "smithsonianmag.com"}
_PRENSA = {
    "nytimes.com", "washingtonpost.com", "wsj.com", "reuters.com", "apnews.com", "bbc.com",
    "bbc.co.uk", "theguardian.com", "cnn.com", "cbsnews.com", "nbcnews.com", "abcnews.go.com",
    "npr.org", "bloomberg.com", "economist.com", "politico.com", "axios.com", "time.com",
    "newsweek.com", "theatlantic.com", "newyorker.com", "vox.com", "usatoday.com", "latimes.com",
    "foxnews.com", "aljazeera.com", "dw.com", "france24.com", "lemonde.fr", "spiegel.de",
    "elpais.com", "elmundo.es", "abc.es", "rtve.es", "lavanguardia.com", "elconfidencial.com",
    "eldiario.es", "20minutos.es", "larazon.es", "publico.es", "infobae.com", "clarin.com",
    "lanacion.com.ar", "elcomercio.pe", "eltiempo.com", "milenio.com", "excelsior.com.mx",
    "newsnationnow.com", "stripes.com", "thehill.com", "militarytimes.com", "defensenews.com",
    "wired.com", "arstechnica.com", "theverge.com", "vice.com", "rollingstone.com",
    "scientificamerican.com", "nationalgeographic.com", "nationalgeographic.es", "muyinteresante.es",
}
_REDES = {"youtube.com", "youtu.be", "reddit.com", "x.com", "twitter.com", "facebook.com",
          "tiktok.com", "instagram.com", "t.me", "rumble.com", "bitchute.com", "odysee.com",
          "quora.com", "medium.com", "substack.com", "pinterest.com"}


def _dominio(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _en(host, conjunto):
    """host pertenece a alguno de los dominios (o subdominios suyos) del conjunto."""
    return any(host == d or host.endswith("." + d) for d in conjunto)


def clasificar_fuente(url):
    """{'url', 'dominio', 'tipo', 'etiqueta'} para una URL citada en un dossier."""
    host = _dominio(url)
    partes = host.split(".")
    if (host.endswith((".gov", ".mil", ".int", ".europa.eu")) or "gov" in partes[:-1]
            or "gob" in partes or "gouv" in partes or "mil" in partes[:-1]
            or host in {"un.org", "boe.es", "congreso.es", "senado.es"}):
        tipo = "oficial"
    elif _en(host, _ARCHIVOS):
        tipo = "archivo"
    elif _en(host, _REFERENCIA):
        tipo = "referencia"
    elif _en(host, _PRENSA):
        tipo = "prensa"
    elif _en(host, _REDES):
        tipo = "redes"
    else:
        tipo = "web"
    return {"url": url, "dominio": host or url, "tipo": tipo, "etiqueta": TIPOS_FUENTE[tipo]}


def detalle_fuentes(urls):
    """Clasifica una lista de URLs y resume cuántas hay de cada tipo."""
    detalle = [clasificar_fuente(u) for u in (urls or []) if isinstance(u, str) and u.startswith("http")]
    return {"items": detalle, "por_tipo": dict(Counter(d["tipo"] for d in detalle))}

# Palabras que suelen abrir una frase/viñeta y arruinarían el heurístico de "palabra en
# mayúscula = nombre propio" (el LLM capitaliza el inicio de cada hecho/hipótesis).
_STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "y", "en", "un", "una", "unos", "unas",
    "con", "por", "para", "su", "sus", "al", "lo", "que", "es", "son", "fue", "era",
    "como", "the", "of", "and", "a", "an", "esta", "este", "estos", "estas", "hay",
    "más", "pero", "sin", "sobre", "entre", "desde", "hasta", "todo", "toda", "existen",
    "existe", "según", "estos", "estas", "además", "aunque", "documentos", "documento",
    "coincidencia", "publicación", "informe", "informes", "durante", "mientras",
    "algunos", "algunas", "varios", "varias", "otros", "otras", "cada", "también",
    "así", "solo", "sólo", "muchos", "muchas", "podría", "podrían", "esto", "eso",
}

# Entidades "de cabecera" del género — siempre se reconocen si aparecen, sin depender
# de en qué posición de la frase caigan (evita que el heurístico genérico las pierda).
_ENTIDADES_CONOCIDAS = [
    "CIA", "FBI", "NSA", "NASA", "KGB", "ONU", "OTAN", "MI6", "ODNI", "AARO",
    "MK-Ultra", "MKUltra", "Área 51", "Roswell", "HAARP", "Stargate",
    "Northwoods", "Paperclip", "COINTELPRO", "Mockingbird", "Bilderberg", "Illuminati",
    "Bohemian Grove", "Denver International Airport", "The Economist", "World Ahead",
    "Vaticano", "Pentágono", "Casa Blanca", "Congreso", "JFK", "RFK", "MLK",
    "UAP", "OVNI", "Waco", "Branch Davidian", "Epstein", "Maxwell",
] + [c for c in getattr(config, "DETECTIVE_CATEGORIAS", []) if c.lower() not in ("otras", "otros")]

# Variantes de la misma entidad: se cuentan juntas (si no, "OVNI" y "OVNIs" salen como
# dos patrones distintos en el ranking).
_ALIAS = {
    "ovnis": "OVNI", "ufo": "OVNI", "ufos": "OVNI", "uaps": "UAP",
    "mkultra": "MK-Ultra", "mk-ultra": "MK-Ultra", "mk ultra": "MK-Ultra",
    "area 51": "Área 51", "pentagono": "Pentágono", "pentagon": "Pentágono",
    "illuminatis": "Illuminati", "the world ahead": "World Ahead",
}

_SIGLA_RE = re.compile(r"\b[A-Z]{3,6}\b")
_HIFEN_RE = re.compile(r"\b[A-Z][A-Za-z]{1,10}-[A-Z][A-Za-z]{1,10}\b")
_PROPIO_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ0-9][a-záéíóúñ0-9]*){1,2})\b")
_ANIO_RE = re.compile(r"\b(19\d{2}|20[0-4]\d)\b")
_ANIO_FINAL_RE = re.compile(r"\s+(?:19|20)\d{2}$")


def _canonico(t):
    t = _ANIO_FINAL_RE.sub("", t.strip())   # "World Ahead 2026" -> "World Ahead"
    return _ALIAS.get(t.lower(), t)


def extraer_terminos(texto):
    """Candidatos a 'entidad' de un texto: entidades conocidas del género, siglas,
       nombres compuestos con guion y secuencias de 2-3 palabras capitalizadas.
       (Deliberadamente NO acepta una sola palabra capitalizada suelta: es la fuente
       principal de ruido, porque el LLM capitaliza el inicio de cada viñeta.)"""
    if not texto:
        return []
    terminos = []
    bajo = texto.lower()
    for ent in _ENTIDADES_CONOCIDAS:
        if ent.lower() in bajo:
            terminos.append(ent)
    for alias, ent in _ALIAS.items():
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", bajo):
            terminos.append(ent)
    terminos += _SIGLA_RE.findall(texto)
    terminos += _HIFEN_RE.findall(texto)
    for m in _PROPIO_RE.finditer(texto):
        cand = m.group(1).strip()
        primera = cand.split()[0].lower()
        if primera in _STOPWORDS:
            continue
        terminos.append(cand)
    return [c for c in (_canonico(t) for t in terminos) if len(c) >= 3]


def _texto_dossier(inv):
    return " ".join([
        inv.get("titulo") or "", inv.get("tema") or "", inv.get("gancho") or "",
        " ".join(inv.get("hechos_verificados") or []),
        " ".join(inv.get("hipotesis") or []),
        " ".join(inv.get("conexiones") or []),
    ])


def calcular_conexiones():
    """Analiza todos los dossiers y devuelve nodos, aristas (entidades compartidas),
       ranking de entidades recurrentes y una línea temporal por años mencionados."""
    invs = database.get_investigaciones()
    textos = {inv["id"]: _texto_dossier(inv) for inv in invs}
    terminos_por_dossier = {iid: set(extraer_terminos(t)) for iid, t in textos.items()}

    freq = Counter()
    for terms in terminos_por_dossier.values():
        freq.update(terms)
    compartidos = {t for t, n in freq.items() if n >= 2}
    # Para el GRAFO solo cuentan las conexiones "específicas": un término que aparece en
    # casi todos los casos (CIA, OVNI...) no dice nada interesante sobre un par concreto
    # y convertiría el grafo en una maraña. Esos temas de fondo ya van en el ranking.
    max_dossiers = len(ids := list(terminos_por_dossier.keys())) or 1
    tope_especifico = max(3, round(max_dossiers * 0.3))
    especificos = {t for t in compartidos if freq[t] <= tope_especifico}

    aristas = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            comunes = (terminos_por_dossier[ids[i]] & terminos_por_dossier[ids[j]]) & especificos
            if comunes:
                aristas.append({"a": ids[i], "b": ids[j], "terminos": sorted(comunes)[:5], "peso": len(comunes)})
    aristas.sort(key=lambda e: -e["peso"])
    aristas = aristas[:80]
    conectados = {n for a in aristas for n in (a["a"], a["b"])}

    grado = Counter()
    for a in aristas:
        grado[a["a"]] += 1
        grado[a["b"]] += 1

    nodos = [{
        "id": inv["id"],
        "titulo": inv.get("titulo") or inv.get("tema") or inv["id"],
        "categoria": inv.get("categoria") or "",
        "certeza": inv.get("nivel_certeza") or "MEDIO",
        "fecha": (inv.get("fecha") or "")[:10],
        "conectado": inv["id"] in conectados,
        "grado": grado[inv["id"]],
        # Entidades recurrentes que menciona: permite resaltar en el tablero los casos
        # que comparten un patrón al pulsarlo en el ranking.
        "terminos": sorted(terminos_por_dossier[inv["id"]] & compartidos),
    } for inv in invs]

    ranking = [{"termino": t, "n": n} for t, n in freq.most_common(30) if t in compartidos][:15]

    # Línea temporal: cuántos DOSSIERS mencionan cada año (no cuántas veces: un solo caso
    # que repite "2026" diez veces no debe pesar como diez). Los años futuros son
    # predicciones ("The World Ahead 2030"), no hechos: fuera.
    actual = datetime.now().year
    anios = Counter()
    for texto in textos.values():
        anios.update({y for y in _ANIO_RE.findall(texto) if int(y) <= actual})
    linea_temporal = sorted(
        ({"anio": a, "n": n} for a, n in anios.items()), key=lambda x: x["anio"]
    )

    return {"nodos": nodos, "aristas": aristas, "ranking": ranking, "linea_temporal": linea_temporal,
            "anio_actual": actual}
