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

import config
import database

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
    "UAP", "OVNI", "OVNIs", "Waco", "Branch Davidian", "Epstein", "Maxwell",
] + list(getattr(config, "DETECTIVE_CATEGORIAS", []))

_SIGLA_RE = re.compile(r"\b[A-Z]{3,6}\b")
_HIFEN_RE = re.compile(r"\b[A-Z][A-Za-z]{1,10}-[A-Z][A-Za-z]{1,10}\b")
_PROPIO_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ0-9][a-záéíóúñ0-9]*){1,2})\b")
_ANIO_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def extraer_terminos(texto):
    """Candidatos a 'entidad' de un texto: entidades conocidas del género, siglas,
       nombres compuestos con guion y secuencias de 2-3 palabras capitalizadas.
       (Deliberadamente NO acepta una sola palabra capitalizada suelta: es la fuente
       principal de ruido, porque el LLM capitaliza el inicio de cada viñeta.)"""
    if not texto:
        return []
    terminos = []
    for ent in _ENTIDADES_CONOCIDAS:
        if ent.lower() in texto.lower():
            terminos.append(ent)
    terminos += _SIGLA_RE.findall(texto)
    terminos += _HIFEN_RE.findall(texto)
    for m in _PROPIO_RE.finditer(texto):
        cand = m.group(1).strip()
        primera = cand.split()[0].lower()
        if primera in _STOPWORDS:
            continue
        terminos.append(cand)
    return terminos


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

    nodos = [{
        "id": inv["id"],
        "titulo": inv.get("titulo") or inv.get("tema") or inv["id"],
        "categoria": inv.get("categoria") or "",
        "certeza": inv.get("nivel_certeza") or "MEDIO",
        "conectado": inv["id"] in conectados,
    } for inv in invs]

    ranking = [{"termino": t, "n": n} for t, n in freq.most_common(30) if t in compartidos][:15]

    anios = Counter()
    for texto in textos.values():
        for y in _ANIO_RE.findall(texto):
            anios[y] += 1
    linea_temporal = sorted(
        ({"anio": a, "n": n} for a, n in anios.items()), key=lambda x: x["anio"]
    )

    return {"nodos": nodos, "aristas": aristas, "ranking": ranking, "linea_temporal": linea_temporal}
