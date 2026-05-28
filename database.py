import sqlite3
import json
import os
import re
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "documentos.db")

# Única fuente de verdad para el esquema. (nombre, tipo_sql)
COLUMNS = [
    ("id", "TEXT PRIMARY KEY"),
    ("titulo", "TEXT NOT NULL"),
    ("titulo_norm", "TEXT"),
    ("titulo_original", "TEXT"),
    ("fecha_documento", "TEXT"),
    ("fecha_acceso", "TEXT"),
    ("organismo", "TEXT"),
    ("tipo_documento", "TEXT"),
    ("clasificacion_original", "TEXT"),
    ("idioma_original", "TEXT"),
    ("url_fuente", "TEXT"),
    ("url_noticia", "TEXT"),
    ("estado_desclasificacion", "TEXT"),
    ("verificado", "TEXT"),            # "Oficial" | "Posible"
    ("fuente_fiabilidad", "TEXT"),     # "Alta" | "Media" | "Baja"
    ("verificacion_autenticidad", "TEXT"),
    ("pais", "TEXT"),
    ("categorias", "TEXT"),
    ("resumen_ejecutivo", "TEXT"),
    ("puntos_clave", "TEXT"),
    ("implicaciones", "TEXT"),
    ("nivel_confianza", "TEXT"),
    ("razon_confianza", "TEXT"),
    ("num_documentos", "TEXT"),
    ("fecha_ingreso", "TEXT"),
    ("analizado_ia", "TEXT"),    # "" pendiente | "curado" | "gemini" | fecha ISO del análisis
    ("analisis_detallado", "TEXT"),   # JSON con el análisis profundo para el informe PDF
    ("titulo_es_hecho", "TEXT"),      # "si" si el título ya está en español
]
COL_NAMES = [c[0] for c in COLUMNS]
JSON_FIELDS = {"organismo", "categorias", "puntos_clave"}


INITIAL_DOCUMENTS = [
    {
        "id": "DOC-2026-001",
        "titulo": "Primera Publicación de Archivos UAP del Pentágono — Programa PURSUE",
        "titulo_original": "Department of War: PURSUE First Release — Unidentified Anomalous Phenomena Files",
        "fecha_documento": "2026-05-08",
        "fecha_acceso": "2026-05-27",
        "organismo": ["U.S. Department of War", "AARO", "ODNI", "NASA", "FBI", "Department of Energy"],
        "tipo_documento": "Colección de archivos gubernamentales (vídeos, fotografías, informes)",
        "clasificacion_original": "Top Secret / Secret (variable por documento)",
        "idioma_original": "Inglés",
        "url_fuente": "https://www.war.gov/ufo/",
        "url_noticia": "https://www.stripes.com/theaters/us/2026-05-08/pentagon-ufo-files-release-21612115.html",
        "estado_desclasificacion": "DESCLASIFICADO OFICIALMENTE",
        "verificado": "Oficial",
        "fuente_fiabilidad": "Alta",
        "verificacion_autenticidad": "Publicado en war.gov por el Departamento de Guerra de EE. UU. Confirmado por el Secretario Hegseth y la Directora de Inteligencia Gabbard.",
        "pais": "EE. UU.",
        "categorias": ["Seguridad y defensa", "Inteligencia y espionaje", "Ciencia y tecnología militar"],
        "resumen_ejecutivo": "El 8 de mayo de 2026, el Departamento de Guerra de EE. UU. publicó el primer lote de 162 archivos clasificados sobre Fenómenos Anómalos No Identificados (UAP), abarcando vídeos militares de tres mandos regionales, fotografías históricas y documentos de agencias federales. El programa PURSUE fue impulsado por la administración Trump como compromiso de máxima transparencia. Los archivos corresponden a casos sin resolución definitiva.",
        "puntos_clave": [
            "162 documentos en la primera entrega, disponibles en war.gov/ufo.",
            "Incluye vídeos de U.S. Indo-Pacific Command, U.S. Central Command y U.S. European Command.",
            "Fotografías de la misión Apollo 12 de 1969 incluidas.",
            "Agencias: Departamento de Guerra, Casa Blanca, ODNI, NASA, FBI y DOE.",
            "El Secretario Hegseth: los archivos 'han alimentado justificadamente la especulación'.",
            "La Directora Gabbard: inicio de una revisión comprehensiva continua.",
            "Todos los casos son 'sin resolución' — sin determinaciones definitivas.",
            "Publicación rodante: continuará de forma periódica."
        ],
        "implicaciones": "Cambio histórico en la política de transparencia de EE. UU. sobre UAP, rompiendo décadas de silencio institucional. La implicación de múltiples agencias sugiere estudio multidisciplinar clasificado. La falta de resoluciones refuerza la incertidumbre científica.",
        "nivel_confianza": "ALTO",
        "razon_confianza": "Fuente primaria oficial (war.gov), declaraciones públicas de altos funcionarios, cobertura mediática verificada.",
        "num_documentos": "162 archivos"
    },
    {
        "id": "DOC-2026-002",
        "titulo": "Segunda Publicación de Archivos UAP del Pentágono — Programa PURSUE",
        "titulo_original": "Department of War: PURSUE Second Release — Unidentified Anomalous Phenomena Files",
        "fecha_documento": "2026-05-22",
        "fecha_acceso": "2026-05-27",
        "organismo": ["U.S. Department of War", "AARO", "NASA"],
        "tipo_documento": "Vídeos clasificados (51), documentos PDF (6), grabaciones de audio (7)",
        "clasificacion_original": "Clasificado (nivel variable)",
        "idioma_original": "Inglés",
        "url_fuente": "https://www.war.gov/News/Releases/Release/Article/4499305/department-of-war-publishes-second-release-of-unidentified-anomalous-phenomena/",
        "url_noticia": "https://www.newsnationnow.com/space/ufo/pentagon-second-batch-ufo-files-declassification/",
        "estado_desclasificacion": "DESCLASIFICADO OFICIALMENTE",
        "verificado": "Oficial",
        "fuente_fiabilidad": "Alta",
        "verificacion_autenticidad": "Comunicado oficial del Departamento de Guerra en war.gov. Corroborado por CBS News, EarthSky y NewsNation.",
        "pais": "EE. UU.",
        "categorias": ["Seguridad y defensa", "Inteligencia y espionaje", "Ciencia y tecnología militar"],
        "resumen_ejecutivo": "El 22 de mayo de 2026, el Departamento de Guerra publicó el segundo lote PURSUE con 64 archivos (51 vídeos, 6 PDFs, 7 audios). Incluye el vídeo del derribo de un UAP sobre el lago Hurón, documentos vinculados a la instalación nuclear PANTEX, inteligencia soviética sobre UAP, y el testimonio inédito de un oficial de inteligencia en activo sobre investigaciones realizadas en 2025.",
        "puntos_clave": [
            "64 archivos: 51 vídeos, 6 PDFs y 7 grabaciones de audio.",
            "Vídeo del derribo de un UAP sobre el lago Hurón.",
            "Imágenes de alta definición de UAP con formas no vistas previamente.",
            "Encuentros en el área del U.S. Central Command (2018–2023), incluido el Golfo Pérsico.",
            "Informe sobre actividades de inteligencia soviética vinculadas a UAP.",
            "Archivos del DOE sobre UAP en PANTEX [instalación clave de armas nucleares].",
            "Testimonio de un oficial de inteligencia en activo — primera vez en la historia.",
            "Más de 40 vídeos respondían a solicitudes directas del Congreso de EE. UU."
        ],
        "implicaciones": "La presencia de informes vinculados a instalaciones nucleares (PANTEX) eleva el nivel de preocupación sobre seguridad nacional. El testimonio de un oficial en activo es un hito sin precedentes. La participación del Congreso como solicitante indica supervisión legislativa activa.",
        "nivel_confianza": "ALTO",
        "razon_confianza": "Comunicado oficial del Departamento de Guerra, corroborado por CBS News, EarthSky, NewsNation e Interesting Engineering.",
        "num_documentos": "64 archivos"
    },
    {
        "id": "DOC-2026-003",
        "titulo": "Documentos Secretos del 23-F: Archivos del Intento de Golpe de Estado de 1981",
        "titulo_original": "Documentos clasificados del 23 de febrero de 1981 — Desclasificación oficial por el Gobierno de España",
        "fecha_documento": "2026-02-25",
        "fecha_acceso": "2026-05-27",
        "organismo": ["Gobierno de España — Consejo de Ministros", "Ministerio de Defensa", "Ministerio del Interior", "Ministerio de Asuntos Exteriores"],
        "tipo_documento": "Informes secretos, transcripciones telefónicas, expedientes de inteligencia, registros judiciales, comunicaciones diplomáticas",
        "clasificacion_original": "SECRETO (nivel máximo español vigente en 1981)",
        "idioma_original": "Español",
        "url_fuente": "https://www.lamoncloa.gob.es",
        "url_noticia": "https://www.infobae.com/espana/2026/02/25/desclasificados-los-documentos-secretos-del-23f-las-claves-de-los-150-bloques-de-archivos-publicados-por-el-gobierno-sobre-el-intento-de-golpe-de-estado/",
        "estado_desclasificacion": "DESCLASIFICADO OFICIALMENTE",
        "verificado": "Oficial",
        "fuente_fiabilidad": "Alta",
        "verificacion_autenticidad": "Anuncio oficial del Consejo de Ministros de España publicado en La Moncloa. Cobertura verificada por Infobae y medios españoles de referencia.",
        "pais": "España",
        "categorias": ["Seguridad y defensa", "Inteligencia y espionaje", "Política exterior y diplomacia", "Corrupción y gobernanza"],
        "resumen_ejecutivo": "El 25 de febrero de 2026, en el 45.º aniversario del 23-F, el Gobierno de España desclasificó 153 unidades documentales de los ministerios de Defensa, Interior y Exteriores, poniendo fin a 45 años de secreto oficial. Los documentos revelan que seis miembros del antiguo CNI participaron activamente en el golpe e intentaron encubrir su implicación.",
        "puntos_clave": [
            "153 unidades documentales de tres ministerios: Defensa, Interior y Exteriores.",
            "Seis miembros del antiguo CNI participaron activamente en el golpe.",
            "Transcripciones de conversaciones telefónicas de los protagonistas del 23-F.",
            "Informes de la Guardia Civil y registros policiales del 23 de febrero de 1981.",
            "Comunicaciones diplomáticas internacionales de la noche del golpe.",
            "Documentos sobre la respuesta constitucional del Rey Juan Carlos I.",
            "Acciones del Capitán General Milans del Bosch en Valencia documentadas.",
            "Primer acceso público tras más de 45 años de secreto oficial."
        ],
        "implicaciones": "La implicación de seis miembros del CNI en el golpe tiene consecuencias históricas y potencialmente jurídicas. Los documentos pueden reescribir la historiografía oficial de la Transición española y plantear interrogantes sobre la supervisión civil de los servicios de inteligencia.",
        "nivel_confianza": "ALTO",
        "razon_confianza": "Anuncio oficial del Consejo de Ministros de España. Portal gubernamental verificado. Cobertura amplia en medios de referencia españoles e internacionales.",
        "num_documentos": "153 unidades documentales"
    },
    {
        "id": "DOC-2026-004",
        "titulo": "Lista de Publicaciones Q2 FY2026 del Centro Nacional de Desclasificación (NDC)",
        "titulo_original": "NDC FY2026 Q2 Release List — National Declassification Center, National Archives",
        "fecha_documento": "2026-04-23",
        "fecha_acceso": "2026-05-27",
        "organismo": ["National Declassification Center (NDC)", "National Archives and Records Administration (NARA)"],
        "tipo_documento": "Lista de publicaciones: expedientes textuales, imágenes en movimiento, negativos fotográficos",
        "clasificacion_original": "Top Secret / Secret / Confidential (variable por expediente)",
        "idioma_original": "Inglés",
        "url_fuente": "https://www.archives.gov/declassification/ndc/release-lists",
        "url_noticia": "https://www.archives.gov/declassification/ndc/release-lists",
        "estado_desclasificacion": "DESCLASIFICADO OFICIALMENTE",
        "verificado": "Oficial",
        "fuente_fiabilidad": "Alta",
        "verificacion_autenticidad": "Publicado directamente por NARA/NDC en archives.gov, con lista en PDF y Excel descargables.",
        "pais": "EE. UU.",
        "categorias": ["Seguridad y defensa", "Inteligencia y espionaje", "Política exterior y diplomacia"],
        "resumen_ejecutivo": "El 23 de abril de 2026, el NDC publicó 58 nuevas entradas procesadas entre enero y marzo de 2026, incluyendo la correspondencia central antes Top Secret de la Misión de EE. UU. ante la ONU, registros de programas de misiles balísticos, expedientes POW/MIA e investigación sobre el asedio Branch Davidian (Waco, Texas).",
        "puntos_clave": [
            "58 entradas nuevas del período enero–marzo 2026.",
            "Tipos: documentos textuales, imágenes en movimiento y negativos fotográficos.",
            "Correspondencia Top Secret de la Misión de EE. UU. ante la ONU.",
            "Registros de juegos de guerra (war games files).",
            "Registros del programa de misiles balísticos.",
            "Expedientes de inteligencia POW/MIA (prisioneros y desaparecidos en combate).",
            "Materiales sobre el asedio al complejo Branch Davidian (Waco, Texas).",
            "Disponibles en PDF y Excel en archives.gov."
        ],
        "implicaciones": "Los archivos ONU pueden revelar posiciones diplomáticas privadas de la Guerra Fría. Los expedientes POW/MIA son sensibles para familias de veteranos. Los materiales sobre Waco son relevantes para debates sobre uso de la fuerza federal.",
        "nivel_confianza": "ALTO",
        "razon_confianza": "Publicación directa en archives.gov (portal oficial NARA) con documentos descargables en PDF y Excel.",
        "num_documentos": "58 entradas"
    },
    {
        "id": "DOC-2025-001",
        "titulo": "Registros del Asesinato de JFK: Publicación 2025 — 80.000+ Páginas Sin Redacciones",
        "titulo_original": "JFK Assassination Records — 2025 Documents Release, National Archives",
        "fecha_documento": "2025-03-18",
        "fecha_acceso": "2026-05-27",
        "organismo": ["National Archives and Records Administration (NARA)", "Office of the Director of National Intelligence (ODNI)"],
        "tipo_documento": "Registros de la Comisión Warren, expedientes FBI/CIA, fotografías, grabaciones de audio, artefactos",
        "clasificacion_original": "Top Secret / Secret / Confidential (variable por expediente)",
        "idioma_original": "Inglés",
        "url_fuente": "https://www.archives.gov/research/jfk/release-2025",
        "url_noticia": "https://www.archives.gov/news/articles/jfk-records-release",
        "estado_desclasificacion": "DESCLASIFICADO OFICIALMENTE",
        "verificado": "Oficial",
        "fuente_fiabilidad": "Alta",
        "verificacion_autenticidad": "Publicado por NARA en archives.gov/research/jfk/release-2025. Respaldado por el Decreto Ejecutivo 14176 (23 enero 2025). Confirmado por ODNI y múltiples medios de referencia.",
        "pais": "EE. UU.",
        "categorias": ["Inteligencia y espionaje", "Seguridad y defensa", "Política exterior y diplomacia"],
        "resumen_ejecutivo": "El 18 de marzo de 2025, en cumplimiento del Decreto Ejecutivo 14176, se publicaron más de 80.000 páginas sin ninguna redacción relacionadas con los asesinatos de JFK, RFK y MLK — una de las mayores publicaciones individuales de registros clasificados en la historia de EE. UU. La revisión preliminar no halló revelaciones significativas nuevas sobre los magnicidios.",
        "puntos_clave": [
            "Decreto Ejecutivo 14176 (23 enero 2025): ordena desclasificación JFK, RFK y MLK.",
            "18 de marzo de 2025: publicación de 80.000+ páginas sin redacciones.",
            "Una de las mayores publicaciones individuales de registros clasificados en la historia de EE. UU.",
            "La Directora Gabbard confirmó la ausencia total de redacciones.",
            "Colección completa: más de 6 millones de páginas en proceso de digitalización.",
            "Publicados en NARA College Park y en digitalización progresiva en archives.gov.",
            "Revisión preliminar (CBS News): no aparecieron nuevas revelaciones significativas.",
            "Incluye por primera vez registros sobre asesinatos de RFK y MLK junto a JFK."
        ],
        "implicaciones": "Hito de transparencia sin precedentes, aunque la ausencia de revelaciones sugiere que lo más sensible ya fue publicado antes o destruido. La extensión a RFK y MLK abre investigación sobre patrones sistémicos de los años 60 en EE. UU.",
        "nivel_confianza": "ALTO",
        "razon_confianza": "Múltiples fuentes primarias: NARA, White House fact sheet, ODNI, cobertura de CNN, CBS News y otros medios de referencia.",
        "num_documentos": "80.000+ páginas"
    },
    {
        "id": "DOC-2025-002",
        "titulo": "Archivos Epstein: 3,5 Millones de Páginas del DOJ — Ley de Transparencia Epstein",
        "titulo_original": "DOJ Epstein Files Disclosure — Epstein Files Transparency Act Compliance, December 2025",
        "fecha_documento": "2025-12-19",
        "fecha_acceso": "2026-05-27",
        "organismo": ["U.S. Department of Justice (DOJ)", "FBI", "Office of Inspector General (OIG)"],
        "tipo_documento": "Expedientes judiciales, vídeos (2.000+), imágenes (180.000+), documentos de investigación FBI, registros OIG",
        "clasificacion_original": "Confidencial / Sensible (protección judicial, no clasificación de seguridad nacional)",
        "idioma_original": "Inglés",
        "url_fuente": "https://www.justice.gov/epstein/doj-disclosures",
        "url_noticia": "https://www.justice.gov/opa/pr/department-justice-publishes-35-million-responsive-pages-compliance-epstein-files",
        "estado_desclasificacion": "PUBLICADO POR MANDATO LEGAL (Epstein Files Transparency Act) — No es desclasificación de seguridad nacional",
        "verificado": "Oficial",
        "fuente_fiabilidad": "Alta",
        "verificacion_autenticidad": "Publicado por el DOJ en justice.gov/epstein. Comunicado oficial de la Oficina de Asuntos Públicos del DOJ. Cobertura verificada por CBS News, ABC News, Axios.",
        "pais": "EE. UU.",
        "categorias": ["Corrupción y gobernanza", "Derechos humanos", "Inteligencia y espionaje"],
        "resumen_ejecutivo": "El 19 de diciembre de 2025, el DOJ publicó ~3,5 millones de páginas en cumplimiento de la Ley de Transparencia Epstein, incluyendo 2.000+ vídeos y 180.000+ imágenes. La publicación fue criticada bipartidistamente por redacciones masivas (+500 páginas íntegramente ennegrecidas), desaparición de 16 archivos y defectos técnicos en redacciones digitales que permitieron recuperar contenido oculto.",
        "puntos_clave": [
            "~3.500.000 páginas totales publicadas (plazo: 19 diciembre 2025).",
            "2.000+ vídeos y 180.000+ imágenes incluidas.",
            "Cinco fuentes: casos Florida/NY Epstein, caso Maxwell, muerte en prisión, ex mayordomo, FBI e OIG.",
            "Más de 500 páginas íntegramente redactadas — criticado bipartidistamente.",
            "16 archivos desaparecieron de la web sin explicación horas tras su publicación.",
            "Defectos técnicos en redacciones digitales permitieron recuperar contenido oculto.",
            "Detalles sobre el pasaporte austriaco falso de Epstein bajo seudónimo.",
            "Información operativa sobre la planificación del arresto de 2019.",
            "ADVERTENCIA: Datos personales sensibles de víctimas omitidos en este resumen."
        ],
        "implicaciones": "Las redacciones masivas y la desaparición de archivos generan dudas sobre el cumplimiento real de la ley. Los defectos técnicos en las redacciones son una falla de seguridad operativa. La escala de 3,5M páginas puede estar sirviendo para enterrar información relevante en el volumen.",
        "nivel_confianza": "MEDIO",
        "razon_confianza": "Fuente primaria oficial (DOJ), pero irregularidades documentadas (archivos eliminados, redacciones defectuosas, críticas bipartidistas) reducen la confianza en la integridad del lote.",
        "num_documentos": "~3.500.000 páginas"
    }
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def normalize_title(titulo):
    """Normaliza un título para deduplicar: minúsculas, sin acentos triviales, espacios colapsados."""
    if not titulo:
        return ""
    t = titulo.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    c = conn.cursor()
    cols_sql = ",\n            ".join(f"{name} {tipo}" for name, tipo in COLUMNS)
    c.execute(f"CREATE TABLE IF NOT EXISTS documentos (\n            {cols_sql}\n        )")
    c.execute("""
        CREATE TABLE IF NOT EXISTS actualizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            fuente TEXT,
            docs_encontrados INTEGER DEFAULT 0,
            docs_nuevos INTEGER DEFAULT 0,
            estado TEXT,
            detalle TEXT
        )
    """)
    # Tabla SEPARADA para las investigaciones del detective (no se mezcla con los documentos)
    c.execute("""
        CREATE TABLE IF NOT EXISTS investigaciones (
            id TEXT PRIMARY KEY,
            fecha TEXT,
            tema TEXT,
            titulo TEXT,
            gancho TEXT,
            hechos_verificados TEXT,
            hipotesis TEXT,
            especulacion TEXT,
            conexiones TEXT,
            veredicto TEXT,
            nivel_certeza TEXT,
            fuentes TEXT,
            motor TEXT,
            imagenes TEXT
        )
    """)
    # Migración: añadir 'imagenes' si la tabla ya existía sin esa columna
    c.execute("PRAGMA table_info(investigaciones)")
    cols_inv = {r["name"] for r in c.fetchall()}
    if "imagenes" not in cols_inv:
        c.execute("ALTER TABLE investigaciones ADD COLUMN imagenes TEXT")
    conn.commit()
    _migrate(conn)
    conn.close()


def _migrate(conn):
    """Añade columnas que falten en una BD antigua, sin perder datos."""
    c = conn.cursor()
    c.execute("PRAGMA table_info(documentos)")
    existing = {row["name"] for row in c.fetchall()}
    for name, tipo in COLUMNS:
        if name not in existing:
            # No se puede añadir PRIMARY KEY vía ALTER; los campos nuevos nunca lo son.
            tipo_simple = tipo.replace("PRIMARY KEY", "").replace("NOT NULL", "").strip()
            c.execute(f"ALTER TABLE documentos ADD COLUMN {name} {tipo_simple}")
    conn.commit()


def _doc_to_row(doc):
    """Convierte un dict de documento en una tupla de valores en el orden de COLUMNS."""
    ahora = datetime.now().isoformat()
    valores = []
    for name in COL_NAMES:
        if name == "titulo_norm":
            valores.append(normalize_title(doc.get("titulo", "")))
        elif name == "fecha_ingreso":
            valores.append(doc.get("fecha_ingreso") or ahora)
        elif name == "fecha_acceso":
            valores.append(doc.get("fecha_acceso") or ahora[:10])
        elif name in JSON_FIELDS:
            valores.append(json.dumps(doc.get(name, []), ensure_ascii=False))
        else:
            valores.append(doc.get(name, ""))
    return tuple(valores)


def _row_to_doc(row):
    d = dict(row)
    for field in JSON_FIELDS:
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except Exception:
            d[field] = []
    return d


def _insert(conn, doc):
    placeholders = ",".join("?" for _ in COL_NAMES)
    cols = ",".join(COL_NAMES)
    conn.execute(f"INSERT INTO documentos ({cols}) VALUES ({placeholders})", _doc_to_row(doc))


def seed_initial_data():
    conn = get_connection()
    c = conn.cursor()
    for doc in INITIAL_DOCUMENTS:
        c.execute("SELECT id FROM documentos WHERE id = ?", (doc["id"],))
        if not c.fetchone():
            _insert(conn, {**doc, "analizado_ia": "curado", "titulo_es_hecho": "si"})
        else:
            # Los documentos semilla ya tienen un resumen experto y título en español.
            c.execute(
                "UPDATE documentos SET analizado_ia = 'curado', titulo_es_hecho = 'si' "
                "WHERE id = ? AND (analizado_ia IS NULL OR analizado_ia = '')",
                (doc["id"],)
            )
    conn.commit()
    conn.close()


def get_documents(filters=None):
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT * FROM documentos WHERE 1=1"
    params = []

    if filters:
        if filters.get("categoria"):
            query += " AND categorias LIKE ?"
            params.append(f"%{filters['categoria']}%")
        if filters.get("pais"):
            query += " AND pais = ?"
            params.append(filters["pais"])
        if filters.get("confianza"):
            query += " AND nivel_confianza = ?"
            params.append(filters["confianza"])
        if filters.get("verificado"):
            query += " AND verificado = ?"
            params.append(filters["verificado"])
        if filters.get("busqueda"):
            term = f"%{filters['busqueda']}%"
            query += " AND (titulo LIKE ? OR resumen_ejecutivo LIKE ? OR implicaciones LIKE ?)"
            params.extend([term, term, term])
        if filters.get("fecha_desde"):
            query += " AND fecha_documento >= ?"
            params.append(filters["fecha_desde"])
        if filters.get("fecha_hasta"):
            query += " AND fecha_documento <= ?"
            params.append(filters["fecha_hasta"])

    query += " ORDER BY fecha_documento DESC, fecha_ingreso DESC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return [_row_to_doc(r) for r in rows]


def get_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as total FROM documentos")
    total = c.fetchone()["total"]
    c.execute("SELECT nivel_confianza, COUNT(*) as n FROM documentos GROUP BY nivel_confianza")
    por_confianza = {r["nivel_confianza"]: r["n"] for r in c.fetchall()}
    c.execute("SELECT verificado, COUNT(*) as n FROM documentos GROUP BY verificado")
    por_verificacion = {r["verificado"] or "Sin marcar": r["n"] for r in c.fetchall()}
    c.execute("SELECT pais, COUNT(*) as n FROM documentos GROUP BY pais ORDER BY n DESC")
    por_pais = [{"pais": r["pais"], "n": r["n"]} for r in c.fetchall()]
    hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) as n FROM documentos WHERE substr(fecha_ingreso,1,10) = ?", (hoy,))
    nuevos_hoy = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) as n FROM documentos WHERE analizado_ia = 'gemini'")
    analizados_ia = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) as n FROM documentos WHERE analizado_ia IS NULL OR analizado_ia = ''")
    pendientes_ia = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) as n FROM documentos WHERE titulo_es_hecho IS NULL OR titulo_es_hecho = ''")
    pendientes_titulos = c.fetchone()["n"]
    c.execute("SELECT categorias FROM documentos")
    cats = {}
    for row in c.fetchall():
        try:
            for cat in json.loads(row["categorias"] or "[]"):
                cats[cat] = cats.get(cat, 0) + 1
        except Exception:
            pass
    conn.close()
    return {
        "total": total,
        "por_confianza": por_confianza,
        "por_verificacion": por_verificacion,
        "por_pais": por_pais,
        "nuevos_hoy": nuevos_hoy,
        "analizados_ia": analizados_ia,
        "pendientes_ia": pendientes_ia,
        "titulos_pendientes": pendientes_titulos,
        "por_categoria": sorted(cats.items(), key=lambda x: -x[1])
    }


def get_last_updates(limit=20):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM actualizaciones ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def log_update(fuente, docs_encontrados, docs_nuevos, estado, detalle=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO actualizaciones (timestamp, fuente, docs_encontrados, docs_nuevos, estado, detalle)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), fuente, docs_encontrados, docs_nuevos, estado, detalle))
    conn.commit()
    conn.close()


def get_document(doc_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM documentos WHERE id = ?", (doc_id,))
    row = c.fetchone()
    conn.close()
    return _row_to_doc(row) if row else None


def get_pending_analysis(limit=5):
    """Documentos aún no analizados por la IA (excluye los 'curado')."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM documentos WHERE analizado_ia IS NULL OR analizado_ia = '' "
        "ORDER BY fecha_ingreso DESC LIMIT ?", (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [_row_to_doc(r) for r in rows]


def update_analysis(doc_id, resumen, puntos_clave, implicaciones, nivel_confianza, marca="gemini"):
    conn = get_connection()
    conn.execute(
        "UPDATE documentos SET resumen_ejecutivo = ?, puntos_clave = ?, "
        "implicaciones = ?, nivel_confianza = ?, analizado_ia = ? WHERE id = ?",
        (resumen, json.dumps(puntos_clave, ensure_ascii=False),
         implicaciones, nivel_confianza, marca, doc_id)
    )
    conn.commit()
    conn.close()


def save_analisis_detallado(doc_id, analisis_dict):
    conn = get_connection()
    conn.execute(
        "UPDATE documentos SET analisis_detallado = ? WHERE id = ?",
        (json.dumps(analisis_dict, ensure_ascii=False), doc_id)
    )
    conn.commit()
    conn.close()


def get_analisis_detallado(doc_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT analisis_detallado FROM documentos WHERE id = ?", (doc_id,))
    row = c.fetchone()
    conn.close()
    if not row or not row["analisis_detallado"]:
        return None
    try:
        return json.loads(row["analisis_detallado"])
    except Exception:
        return None


def count_pending_analysis():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as n FROM documentos WHERE analizado_ia IS NULL OR analizado_ia = ''")
    n = c.fetchone()["n"]
    conn.close()
    return n


def get_titulos_pendientes(limit=200):
    """Documentos cuyo título aún no está en español."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, titulo FROM documentos WHERE titulo_es_hecho IS NULL OR titulo_es_hecho = '' "
        "ORDER BY fecha_ingreso DESC LIMIT ?", (limit,)
    )
    rows = [{"id": r["id"], "titulo": r["titulo"]} for r in c.fetchall()]
    conn.close()
    return rows


def count_titulos_pendientes():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as n FROM documentos WHERE titulo_es_hecho IS NULL OR titulo_es_hecho = ''")
    n = c.fetchone()["n"]
    conn.close()
    return n


def set_titulo(doc_id, nuevo_titulo):
    """Actualiza el título (en español) y lo marca como traducido. El título original
       ya está guardado en titulo_original."""
    conn = get_connection()
    conn.execute(
        "UPDATE documentos SET titulo = ?, titulo_norm = ?, titulo_es_hecho = 'si' WHERE id = ?",
        (nuevo_titulo, normalize_title(nuevo_titulo), doc_id)
    )
    conn.commit()
    conn.close()


_INV_JSON = ("hechos_verificados", "hipotesis", "especulacion", "conexiones", "fuentes", "imagenes")


def insert_investigacion(inv):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO investigaciones
        (id, fecha, tema, titulo, gancho, hechos_verificados, hipotesis,
         especulacion, conexiones, veredicto, nivel_certeza, fuentes, motor, imagenes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        inv["id"], inv.get("fecha", ""), inv.get("tema", ""), inv.get("titulo", ""),
        inv.get("gancho", ""),
        json.dumps(inv.get("hechos_verificados", []), ensure_ascii=False),
        json.dumps(inv.get("hipotesis", []), ensure_ascii=False),
        json.dumps(inv.get("especulacion", []), ensure_ascii=False),
        json.dumps(inv.get("conexiones", []), ensure_ascii=False),
        inv.get("veredicto", ""), inv.get("nivel_certeza", ""),
        json.dumps(inv.get("fuentes", []), ensure_ascii=False),
        inv.get("motor", ""),
        json.dumps(inv.get("imagenes", []), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def get_investigaciones():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM investigaciones ORDER BY fecha DESC")
    rows = c.fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for f in _INV_JSON:
            try:
                d[f] = json.loads(d.get(f) or "[]")
            except Exception:
                d[f] = []
        result.append(d)
    return result


def count_investigaciones():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as n FROM investigaciones")
    n = c.fetchone()["n"]
    conn.close()
    return n


def insert_document(doc):
    """Inserta si no existe ya (por id o por título normalizado). Devuelve True si se insertó."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM documentos WHERE id = ?", (doc["id"],))
    if c.fetchone():
        conn.close()
        return False
    norm = normalize_title(doc.get("titulo", ""))
    if norm:
        c.execute("SELECT 1 FROM documentos WHERE titulo_norm = ?", (norm,))
        if c.fetchone():
            conn.close()
            return False
    _insert(conn, doc)
    conn.commit()
    conn.close()
    return True
