"""
Configuración del Agente Info Clasificados.
Edita estos valores para cambiar el comportamiento sin tocar el resto del código.
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
# "gemini"   -> usa la API gratuita de Gemini (tiene límite diario).
# "lmstudio" -> usa tu LM Studio LOCAL (sin límites). Requiere:
#     1) Abrir LM Studio, cargar un modelo (p. ej. Llama 3.1 8B o Qwen2.5 7B).
#     2) Pestaña "Developer/Local Server" -> Start Server (puerto 1234).
LLM_BACKEND = "lmstudio"    # "gemini" o "lmstudio" (tu modelo local sin límites)

# LM Studio (servidor local compatible con OpenAI)
LMSTUDIO_URL = "http://localhost:1234/v1"
LMSTUDIO_MODEL = "qwen/qwen3.5-9b"   # modelo cargado en LM Studio
LMSTUDIO_TIMEOUT = 600   # CPU: los modelos grandes tardan; damos margen amplio

# Analizar automáticamente los documentos nuevos al hacer la búsqueda diaria
# (solo funciona si hay una clave configurada arriba).
AUTO_ANALYZE_NEW = True
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

# --- Actualización automática diaria ---
AUTO_UPDATE_ENABLED = True
UPDATE_HOUR = 6          # hora (0-23) a la que se busca cada día
UPDATE_MINUTE = 0
TIMEZONE = "Europe/Madrid"

# --- Red ---
HTTP_TIMEOUT = 20        # segundos de espera por petición
USER_AGENT = "AgentInfoClasificados/2.0 (investigacion-publica)"

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
#   (nombre, url, [categorías], país, fiabilidad, max_pdfs)
# fiabilidad: "Alta" (organismo oficial) | "Media" (repositorio/medio verificado)
PDF_PAGES = [
    ("Registros del Asesinato de JFK (NARA, 2025)",
     "https://www.archives.gov/research/jfk/release-2025",
     ["Inteligencia y espionaje", "Seguridad y defensa"],
     "EE. UU.", "Alta", 15),
]

# NARA NDC — listas de publicación trimestrales (PDF/Excel).
SCRAPE_NARA_NDC = True
NARA_NDC_URL = "https://www.archives.gov/declassification/ndc/release-lists"

# FBI Vault — archivos desclasificados del FBI (RSS de novedades; cada item es un PDF).
FBI_VAULT_ENABLED = True
FBI_VAULT_RSS = "https://vault.fbi.gov/recently-added/RSS"
FBI_VAULT_MAX = 20

# archive.org — colecciones de documentos desclasificados (UFOs, MK-Ultra y otros
# clásicos "conspiranoicos"). Identificadores verificados con PDFs descargables.
#   (nombre, identificador_archive_org, [categorías], país, fiabilidad, max_pdfs)
ARCHIVE_ORG_ITEMS = [
    ("Proyecto MKUltra (CIA)",
     "ProjectMkultraTheCiasProgramOfResearchInBehavioralModification",
     ["Inteligencia y espionaje", "Derechos humanos"], "EE. UU.", "Media", 5),

    ("Proyecto Libro Azul — Casos OVNI (años 40)",
     "ProjectBlueBook_1940s_case_files",
     ["Ciencia y tecnología militar", "Otras"], "EE. UU.", "Media", 12),

    ("Proyecto Libro Azul (FBI) — OVNIs",
     "ProjectBlueBookFBI",
     ["Inteligencia y espionaje", "Otras"], "EE. UU.", "Media", 3),

    ("Programa Stargate — Visión remota (CIA)",
     "CIA-RDP96-00788R001700210016-5",
     ["Inteligencia y espionaje", "Ciencia y tecnología militar"], "EE. UU.", "Media", 3),

    ("Operación Northwoods",
     "OperationNorthwoods_201612",
     ["Seguridad y defensa", "Política exterior y diplomacia"], "EE. UU.", "Media", 2),

    ("Operación Paperclip",
     "operation-paperclip",
     ["Seguridad y defensa", "Ciencia y tecnología militar"], "EE. UU.", "Media", 1),
]

# --- Filtros de calidad para el ingestor ---
MIN_TITULO_LEN = 15      # descarta títulos demasiado cortos (enlaces de menú)
MAX_RESUMEN_LEN = 800    # trunca resúmenes largos
# Palabras que delatan enlaces de navegación (no documentos):
BLOCKLIST_TITULOS = [
    "home", "inicio", "contact", "contacto", "about", "sobre nosotros",
    "privacy", "privacidad", "sitemap", "mapa del sitio", "login",
    "search", "buscar", "menu", "menú", "subscribe", "suscr",
    "facebook", "twitter", "instagram", "youtube", "linkedin",
    "siguiente", "anterior", "next", "previous", "cookies",
]
