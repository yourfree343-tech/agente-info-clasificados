"""
Configuración del Agente Info Clasificados.
Edita estos valores para cambiar el comportamiento sin tocar el resto del código.

Esta es la PLANTILLA (sin secretos) que se sube al repositorio. Para usarla:
  1) Copia este archivo como config.py:   copy config.example.py config.py
  2) Rellena tus claves de API en config.py (ese archivo NO se sube, está en .gitignore).
"""

import os

# --- Servidor web ---
HOST = "127.0.0.1"
PORT = 5790
OPEN_BROWSER_ON_START = True   # abre el navegador automáticamente al arrancar

# ===========================================================================
#  INTELIGENCIA ARTIFICIAL (Gemini) — resumen automático de documentos
# ===========================================================================
# 1) Entra GRATIS en: https://aistudio.google.com/apikey  (con tu cuenta Google)
# 2) Pulsa "Create API key" y copia la clave.
# 3) Pégala aquí entre las comillas:
GEMINI_API_KEY = ""    # <-- pega tu clave gratuita aquí (opcional; ver README)
# (alternativa: definir la variable de entorno GEMINI_API_KEY)
GEMINI_API_KEY = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")

# Modelo gratuito de Gemini. Si uno diera error, prueba "gemini-2.0-flash".
GEMINI_MODEL = "gemini-2.5-flash"

# ===========================================================================
#  MOTOR LLM INTERCAMBIABLE (cerebro del detective y de los resúmenes de texto)
# ===========================================================================
# "gemini"     -> usa la API gratuita de Gemini (tiene límite diario).
# "lmstudio"   -> usa tu LM Studio LOCAL (sin límites, pero lento en CPU). Requiere:
#     1) Abrir LM Studio, cargar un modelo (p. ej. Llama 3.1 8B o Qwen2.5 7B).
#     2) Pestaña "Developer/Local Server" -> Start Server (puerto 1234).
# "openrouter" -> usa la API de OpenRouter (modelo en la nube, no depende de tu CPU).
#     1) Entra en https://openrouter.ai/keys y crea una clave (algunos modelos son gratis).
#     2) Pégala abajo en OPENROUTER_API_KEY.
LLM_BACKEND = "openrouter"    # "gemini" | "lmstudio" | "openrouter"

# LM Studio (servidor local compatible con OpenAI)
LMSTUDIO_URL = "http://localhost:1234/v1"
LMSTUDIO_MODEL = "qwen/qwen3.5-9b"   # modelo cargado en LM Studio
LMSTUDIO_TIMEOUT = 1800  # CPU: un dossier 9B puede tardar >10 min; margen amplio
                         # (es solo un techo: una llamada sana devuelve en cuanto acaba)
LMSTUDIO_MAX_TOKENS = 2500   # tope de salida por llamada (evita dossiers JSON truncados)

# OpenRouter (API en la nube compatible con OpenAI; https://openrouter.ai)
# 1) Entra GRATIS en: https://openrouter.ai/keys  (con tu cuenta Google/GitHub)
# 2) Crea una clave y pégala aquí entre las comillas:
OPENROUTER_API_KEY = ""    # <-- pega tu clave de OpenRouter aquí
# (alternativa: definir la variable de entorno OPENROUTER_API_KEY)
OPENROUTER_API_KEY = OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "openai/gpt-oss-120b"   # revisa el slug/precio exacto en openrouter.ai/models
OPENROUTER_TIMEOUT = 180   # es un modelo en la nube: no depende de tu CPU, no hace falta más margen
OPENROUTER_MAX_TOKENS = 2500   # tope de salida por llamada (evita dossiers JSON truncados)
OPENROUTER_JSON_MODE = True    # pide JSON estricto (response_format) a los modelos que lo soportan
OPENROUTER_REASONING = "low"   # esfuerzo de razonamiento en modelos que "piensan" (gpt-oss):
                               # "low" deja sitio al JSON y responde antes. "" = no enviarlo.

# Lectura de PDFs ESCANEADOS (sin capa de texto) con un modelo con visión. Desactivado por
# defecto porque cuesta dinero (poco): cada documento envía sus primeras páginas como
# imágenes. Con "google/gemini-2.5-flash-lite" (~0,10 $ por millón de tokens) leer 4
# páginas cuesta del orden de una décima de céntimo por documento. "" = desactivado.
# (Los escaneados de archive.org no lo necesitan: se lee gratis su OCR.)
OPENROUTER_VISION_MODEL = ""   # p. ej. "google/gemini-2.5-flash-lite"
OPENROUTER_VISION_PAGINAS = 4  # páginas que se envían por documento escaneado

# Resumir automáticamente con IA los documentos pendientes, en segundo plano y de poco
# en poco (solo funciona si el motor de arriba está disponible). Antes de gastar una
# llamada, se aprovecha el análisis del informe PDF si ya existe (coste cero).
AUTO_ANALYZE_NEW = True
ANALISIS_INTERVAL_MIN = 15   # cada cuántos minutos se resume el siguiente lote
# Cuántos documentos analizar como máximo en cada lote (respeta el límite gratuito).
ANALYZE_BATCH = 5

# --- Generación automática de informes PDF ---
# Genera en segundo plano el informe PDF de TODOS los documentos. Cuando se agota
# la cuota gratuita de Gemini, se pausa y reanuda solo en el siguiente ciclo.
AUTO_INFORMES_ENABLED = True
INFORMES_INTERVAL_MIN = 12   # cada cuántos minutos intenta generar más informes
INFORMES_BATCH = 3           # cuántos informes genera como máximo por ciclo

# --- Detective conspiranoico (investigación autónoma en internet) ---
# Usa el motor LLM_BACKEND de arriba + búsqueda web propia (DuckDuckGo).
DETECTIVE_ENABLED = True
DETECTIVE_AUTO = True            # True = investiga solo en segundo plano
DETECTIVE_INTERVAL_MIN = 60      # cada cuánto investiga solo (en CPU el 9B tarda ~15-20 min)
DETECTIVE_MAX_BUSQUEDAS = 5
DETECTIVE_RESULTADOS_POR_BUSQUEDA = 5
DETECTIVE_IMAGENES = 4           # imágenes a recopilar por dossier (portadas, fotos, etc.)
DETECTIVE_WIKIPEDIA = True       # base factual: introducción de Wikipedia (es, o en si no hay)
DETECTIVE_NOTICIAS = 4           # noticias recientes sobre el tema (0 = no buscar noticias)

# Banco de temas "semilla" que el detective usa como inspiración (rota y no repite).
# Puedes añadir, quitar o editar los que quieras.
DETECTIVE_TEMAS_SEMILLA = [
    "Portadas de la revista The Economist (The World Ahead) y supuestas predicciones",
    "Illuminati y simbolismo en la industria musical y de Hollywood",
    "Masonería y los símbolos en el billete de un dólar y en Washington D.C.",
    "Grupo Bilderberg y sus reuniones secretas",
    "El Club Bohemian Grove y sus rituales",
    "Project Stargate y los experimentos de visión remota de la CIA",
    "MK-Ultra y el control mental de la CIA",
    "Área 51 y la ingeniería inversa de tecnología no humana",
    "Roswell 1947 y el encubrimiento del incidente OVNI",
    "OVNIs/UAP y las audiencias del Congreso de EE. UU. (2023-2026)",
    "Operación Mockingbird y la infiltración de la CIA en los medios",
    "COINTELPRO y la vigilancia del FBI a activistas",
    "Operación Northwoods y las operaciones de falsa bandera",
    "Operación Paperclip y los científicos nazis en EE. UU.",
    "El asesinato de JFK y las teorías sobre la CIA",
    "Denver International Airport y sus murales apocalípticos",
    "HAARP y el supuesto control del clima",
    "Las élites tecnológicas y los búnkeres de supervivencia",
    "El Vaticano, los archivos secretos y las sociedades religiosas",
    "Chemtrails y la teoría de la fumigación aérea",
]

# Categorías para clasificar cada dossier del detective.
DETECTIVE_CATEGORIAS = [
    "OVNIs / UAP", "Sociedades secretas", "Control mental", "Operaciones encubiertas",
    "Símbolos y élites", "Vigilancia masiva", "Falsa bandera", "Encubrimientos", "Otras",
]

# --- Actualización automática diaria ---
AUTO_UPDATE_ENABLED = True
UPDATE_HOUR = 6          # hora (0-23) a la que se busca cada día
UPDATE_MINUTE = 0
TIMEZONE = "Europe/Madrid"

# --- Red ---
HTTP_TIMEOUT = 20        # segundos de espera por petición

# Tamaño máximo de un documento para ingerirlo (los enormes no se pueden analizar).
MAX_DOC_BYTES = 35 * 1024 * 1024
# Tamaño máximo seguro para enviar un PDF a Gemini "en línea". Si lo supera,
# se recorta a las primeras páginas antes de analizarlo.
INLINE_PDF_SAFE_BYTES = 14 * 1024 * 1024
TRIM_PDF_PAGINAS = 25    # páginas a conservar al recortar un PDF grande

# ===========================================================================
#  FUENTES DE DOCUMENTOS
#  Todas deben entregar PDFs descargables. El ingestor descarta automáticamente
#  cualquier elemento que no se pueda descargar (ver _es_descargable en updater.py).
# ===========================================================================

# Páginas oficiales que listan PDFs de documentos desclasificados.
#   (nombre, url, [categorías], país, fiabilidad, max_nuevos[, {extra}])
# fiabilidad: "Alta" (organismo oficial) | "Media" (repositorio/medio verificado)
# max_nuevos: documentos NUEVOS que se incorporan por actualización. Las colecciones
#   grandes (miles de PDFs) van entrando por tandas, así cada día llega material distinto.
# extra (opcional): {"fecha": "AAAA-MM-DD"} si la página no la codifica en sus enlaces,
#   {"filtro": "regex"} para quedarse solo con los PDF cuyo enlace/texto case.
PDF_PAGES = [
    ("Registros del Asesinato de JFK (NARA, 2025)",
     "https://www.archives.gov/research/jfk/release-2025",
     ["Inteligencia y espionaje", "Seguridad y defensa"],
     "EE. UU.", "Alta", 5),

    ("Registros del Asesinato de JFK (NARA, 2023)",
     "https://www.archives.gov/research/jfk/release-2023",
     ["Inteligencia y espionaje", "Seguridad y defensa"],
     "EE. UU.", "Alta", 3),

    ("Registros del Asesinato de RFK (NARA, 2025)",
     "https://www.archives.gov/research/rfk",
     ["Inteligencia y espionaje", "Seguridad y defensa"],
     "EE. UU.", "Alta", 4),

    ("Registros del Asesinato de MLK (NARA, 2025)",
     "https://www.archives.gov/research/mlk",
     ["Inteligencia y espionaje", "Derechos humanos"],
     "EE. UU.", "Alta", 4),

    ("Papeles del Pentágono (NARA)",
     "https://www.archives.gov/research/pentagon-papers",
     ["Seguridad y defensa", "Política exterior y diplomacia"],
     "EE. UU.", "Alta", 4, {"fecha": "2011-06-13"}),

    ("Estudio independiente UAP (NASA, 2023)",
     "https://science.nasa.gov/uap/",
     ["Ciencia y tecnología militar", "Otras"],
     "EE. UU.", "Alta", 1, {"filtro": "final-report", "fecha": "2023-09-14"}),
]

# NARA NDC — listas de publicación trimestrales (PDF/Excel).
SCRAPE_NARA_NDC = True
NARA_NDC_URL = "https://www.archives.gov/declassification/ndc/release-lists"

# FBI Vault — archivos desclasificados del FBI (RSS de novedades; cada item es un PDF).
FBI_VAULT_ENABLED = True
FBI_VAULT_RSS = "https://vault.fbi.gov/recently-added/RSS"
FBI_VAULT_MAX = 20

# The Black Vault — documentos obtenidos vía FOIA (CIA, NSA, Navy, AARO...). Es un archivo
# privado de referencia: los PDF son respuestas oficiales de las agencias, pero alojados
# por un tercero, así que entran con fiabilidad "Media".
BLACK_VAULT_ENABLED = True
BLACK_VAULT_RSS = "https://www.theblackvault.com/documentarchive/feed/"
BLACK_VAULT_MAX = 8                 # documentos nuevos por actualización
BLACK_VAULT_PDFS_POR_ENTRADA = 2    # una entrada puede enlazar cientos de PDF: solo los primeros

# archive.org — colecciones de documentos desclasificados (UFOs, MK-Ultra y otros
# clásicos "conspiranoicos"). Identificadores verificados con PDFs descargables.
#   (nombre, identificador_archive_org, [categorías], país, fiabilidad, max_nuevos[, {extra}])
# extra: {"fecha": "..."} con la fecha histórica del material (archive.org no la da fiable).
# Los PDF escaneados de archive.org se leen con su OCR gratuito (_djvu.txt).
ARCHIVE_ORG_ITEMS = [
    ("Proyecto MKUltra (CIA)",
     "ProjectMkultraTheCiasProgramOfResearchInBehavioralModification",
     ["Inteligencia y espionaje", "Derechos humanos"], "EE. UU.", "Media", 5,
     {"fecha": "1977-08-03"}),   # audiencia conjunta del Senado

    ("Proyecto Libro Azul — Casos OVNI (años 40)",
     "ProjectBlueBook_1940s_case_files",
     ["Ciencia y tecnología militar", "Otras"], "EE. UU.", "Media", 4,
     {"fecha": "1947"}),

    ("Proyecto Libro Azul (FBI) — OVNIs",
     "ProjectBlueBookFBI",
     ["Inteligencia y espionaje", "Otras"], "EE. UU.", "Media", 3,
     {"fecha": "1947"}),

    ("Programa Stargate — Visión remota (CIA)",
     "CIA-RDP96-00788R001700210016-5",
     ["Inteligencia y espionaje", "Ciencia y tecnología militar"], "EE. UU.", "Media", 3,
     {"fecha": "1983"}),         # análisis del "Gateway Process"

    ("Operación Northwoods",
     "OperationNorthwoods_201612",
     ["Seguridad y defensa", "Política exterior y diplomacia"], "EE. UU.", "Media", 2,
     {"fecha": "1962-03-13"}),

    ("Operación Paperclip",
     "operation-paperclip",
     ["Seguridad y defensa", "Ciencia y tecnología militar"], "EE. UU.", "Media", 1,
     {"fecha": "1945"}),

    ("Colección OVNI completa de la CIA",
     "CIAUFO",
     ["Inteligencia y espionaje", "Ciencia y tecnología militar", "Otras"], "EE. UU.", "Media", 5),

    ("Comité Church — Abusos de CIA/FBI/NSA",
     "ChurchCommittee",
     ["Inteligencia y espionaje", "Corrupción y gobernanza", "Derechos humanos"], "EE. UU.", "Media", 4,
     {"fecha": "1976"}),         # informes finales del Comité

    ("COINTELPRO — FBI contra Martin Luther King",
     "FBI-Neutralize-King",
     ["Inteligencia y espionaje", "Derechos humanos", "Corrupción y gobernanza"], "EE. UU.", "Media", 3),

    ("Informe Roswell (USAF) — Caso Cerrado",
     "roswellreportcas0000mcan",
     ["Ciencia y tecnología militar", "Otras"], "EE. UU.", "Media", 2,
     {"fecha": "1997"}),
]
