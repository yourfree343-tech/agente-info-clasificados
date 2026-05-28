"""
Generación de informes PDF por documento.

Combina:
  - El análisis detallado de Gemini (información importante del documento).
  - Las imágenes extraídas del PDF original (si las hay).
  - Una maquetación limpia con reportlab.

El informe se guarda en data/informes/<doc_id>.pdf y se devuelve su ruta.
"""

import io
import os
import logging
from datetime import datetime

import fitz  # PyMuPDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.utils import ImageReader

import config
import database
import gemini

log = logging.getLogger(__name__)

INFORMES_DIR = os.path.join(os.path.dirname(__file__), "data", "informes")


# ---------------------------------------------------------------------------
# Extracción de imágenes del PDF original
# ---------------------------------------------------------------------------

def extraer_imagenes_pdf(pdf_bytes, max_imgs=6, min_lado=160):
    """Extrae hasta max_imgs imágenes relevantes (descarta iconos pequeños)."""
    imagenes = []
    try:
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        log.warning(f"  No se pudo abrir el PDF para extraer imágenes: {e}")
        return imagenes

    vistos = set()
    for page in pdf:
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in vistos:
                continue
            vistos.add(xref)
            try:
                base = pdf.extract_image(xref)
            except Exception:
                continue
            w, h = base.get("width", 0), base.get("height", 0)
            if w < min_lado or h < min_lado:
                continue   # probablemente un logo o icono
            imagenes.append({"bytes": base["image"], "ext": base.get("ext", "png"),
                             "w": w, "h": h})
            if len(imagenes) >= max_imgs:
                pdf.close()
                return imagenes
    pdf.close()
    return imagenes


# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------

def _estilos():
    ss = getSampleStyleSheet()
    estilos = {
        "titulo": ParagraphStyle("titulo", parent=ss["Title"], fontSize=18,
                                 textColor=colors.HexColor("#0b3d91"), spaceAfter=4),
        "subtitulo": ParagraphStyle("subtitulo", parent=ss["Normal"], fontSize=9,
                                    textColor=colors.HexColor("#555555"), spaceAfter=2),
        "seccion": ParagraphStyle("seccion", parent=ss["Heading2"], fontSize=13,
                                  textColor=colors.HexColor("#0b3d91"), spaceBefore=14, spaceAfter=6),
        "cuerpo": ParagraphStyle("cuerpo", parent=ss["Normal"], fontSize=10.5,
                                 leading=15, alignment=TA_JUSTIFY, spaceAfter=6),
        "vineta": ParagraphStyle("vineta", parent=ss["Normal"], fontSize=10.5, leading=15),
        "cita": ParagraphStyle("cita", parent=ss["Normal"], fontSize=10, leading=14,
                               leftIndent=12, textColor=colors.HexColor("#333333"),
                               borderColor=colors.HexColor("#cccccc"), italic=True, spaceAfter=6),
        "meta_k": ParagraphStyle("meta_k", parent=ss["Normal"], fontSize=8.5,
                                 textColor=colors.HexColor("#888888")),
        "meta_v": ParagraphStyle("meta_v", parent=ss["Normal"], fontSize=9.5, spaceAfter=4),
        "pie": ParagraphStyle("pie", parent=ss["Normal"], fontSize=8,
                              textColor=colors.HexColor("#999999"), alignment=TA_CENTER),
        "aviso": ParagraphStyle("aviso", parent=ss["Normal"], fontSize=9, leading=13,
                                textColor=colors.HexColor("#8a6d00"),
                                backColor=colors.HexColor("#fff7d6"), borderPadding=6, spaceAfter=8),
    }
    return estilos


def _esc(s):
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(texto, estilo):
    """Crea un Paragraph escapando el contenido (para texto plano)."""
    return Paragraph(_esc(texto), estilo)


def _p_rich(texto, estilo):
    """Crea un Paragraph SIN escapar (cuando el texto ya trae etiquetas válidas)."""
    return Paragraph(texto if texto is not None else "", estilo)


def _lista(items, estilo):
    flow = []
    for it in items or []:
        flow.append(ListItem(_p(it, estilo), leftIndent=10))
    if not flow:
        return _p("(Sin datos)", estilo)
    return ListFlowable(flow, bulletType="bullet", bulletColor=colors.HexColor("#0b3d91"),
                        start="•", leftIndent=14)


# ---------------------------------------------------------------------------
# Construcción del informe
# ---------------------------------------------------------------------------

def _img_flowable(img_dict, max_ancho=150 * mm):
    """Convierte bytes de imagen en un flowable Image escalado al ancho de página."""
    try:
        bio = io.BytesIO(img_dict["bytes"])
        reader = ImageReader(bio)
        iw, ih = reader.getSize()
        if iw <= 0 or ih <= 0:
            return None
        escala = min(max_ancho / iw, 1.0)
        return Image(io.BytesIO(img_dict["bytes"]), width=iw * escala, height=ih * escala)
    except Exception as e:
        log.info(f"  Imagen descartada: {e}")
        return None


def construir_pdf(doc, analisis, imagenes):
    os.makedirs(INFORMES_DIR, exist_ok=True)
    ruta = os.path.join(INFORMES_DIR, f"{doc['id']}.pdf")
    est = _estilos()

    pdf = SimpleDocTemplate(
        ruta, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"Informe - {doc.get('titulo','')}", author="Agente Info Clasificados",
    )
    F = []  # flowables

    # Cabecera
    F.append(_p(analisis.get("titulo_informe") or doc.get("titulo", "Informe"), est["titulo"]))
    F.append(_p(doc.get("titulo", ""), est["subtitulo"]))
    F.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#0b3d91"),
                        spaceBefore=4, spaceAfter=10))

    # Ficha de metadatos
    F.append(_p("FICHA DEL DOCUMENTO", est["seccion"]))
    meta = [
        ("Organismo(s)", ", ".join(doc.get("organismo", []) or []) or "—"),
        ("País", doc.get("pais", "—")),
        ("Fecha del documento", doc.get("fecha_documento", "—")),
        ("Estado", doc.get("estado_desclasificacion", "—")),
        ("Verificación", f"{doc.get('verificado','—')} (fiabilidad: {doc.get('fuente_fiabilidad','—')})"),
        ("Nivel de confianza", analisis.get("nivel_confianza", "—")),
        ("Fuente", doc.get("url_fuente", "—")),
    ]
    for k, v in meta:
        F.append(_p_rich(f"<b>{_esc(k)}:</b> {_esc(v)}", est["meta_v"]))

    if analisis.get("_tipo_fuente") == "none":
        F.append(Spacer(1, 6))
        F.append(_p("⚠ No se pudo acceder al contenido completo del documento original. "
                    "Este informe se basa en información limitada (metadatos y fuentes secundarias).",
                    est["aviso"]))

    # Contexto
    if analisis.get("contexto"):
        F.append(_p("CONTEXTO", est["seccion"]))
        F.append(_p(analisis["contexto"], est["cuerpo"]))

    # Hechos clave
    F.append(_p("HECHOS CLAVE", est["seccion"]))
    F.append(_lista(analisis.get("hechos_clave"), est["vineta"]))

    # Revelaciones
    if analisis.get("revelaciones"):
        F.append(_p("LO MÁS IMPORTANTE / REVELACIONES", est["seccion"]))
        F.append(_lista(analisis.get("revelaciones"), est["vineta"]))

    # Datos concretos
    if analisis.get("datos_concretos"):
        F.append(_p("DATOS CONCRETOS (personas, fechas, lugares, expedientes)", est["seccion"]))
        F.append(_lista(analisis.get("datos_concretos"), est["vineta"]))

    # Citas textuales
    citas = analisis.get("citas_textuales") or []
    if citas:
        F.append(_p("CITAS TEXTUALES", est["seccion"]))
        for c in citas:
            if isinstance(c, dict):
                txt = _esc(c.get("cita", ""))
                ub = _esc(c.get("ubicacion", ""))
                F.append(_p_rich(f'«{txt}»' + (f' <font size=8 color="#888888">[{ub}]</font>' if ub else ""), est["cita"]))
            else:
                F.append(_p(f"«{c}»", est["cita"]))

    # Implicaciones
    if analisis.get("implicaciones"):
        F.append(_p("IMPLICACIONES", est["seccion"]))
        F.append(_p(analisis["implicaciones"], est["cuerpo"]))

    # Imágenes del documento original
    flows_img = [fi for fi in (_img_flowable(im) for im in (imagenes or [])) if fi]
    if flows_img:
        F.append(_p("IMÁGENES DEL DOCUMENTO ORIGINAL", est["seccion"]))
        for i, fi in enumerate(flows_img, 1):
            F.append(fi)
            F.append(_p(f"Imagen {i} extraída del documento original.", est["subtitulo"]))
            F.append(Spacer(1, 8))

    # Pie
    F.append(Spacer(1, 14))
    F.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cccccc"), spaceAfter=6))
    F.append(_p(f"Informe generado por Agente Info Clasificados · Análisis con IA (Gemini) · "
                f"{datetime.now().strftime('%d/%m/%Y %H:%M')} · Documento ID: {doc['id']}", est["pie"]))
    F.append(_p("Resumen automático: verifica siempre con la fuente oficial antes de citar.", est["pie"]))

    pdf.build(F)
    return ruta


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def generar_informe(doc_id, forzar=False):
    """Genera (o reutiliza) el informe PDF de un documento. Devuelve dict con ok + ruta."""
    doc = database.get_document(doc_id)
    if not doc:
        return {"ok": False, "error": "Documento no encontrado."}

    if not gemini.hay_clave():
        return {"ok": False, "error": "No hay clave de Gemini configurada en config.py."}

    ruta = os.path.join(INFORMES_DIR, f"{doc_id}.pdf")
    if os.path.exists(ruta) and not forzar:
        return {"ok": True, "ruta": ruta, "cacheado": True}

    # 1) Descargar el contenido una sola vez
    tipo, dato, url = gemini.obtener_contenido(doc)

    # 2) Análisis detallado con Gemini
    analisis = gemini.analizar_detallado(doc, tipo, dato, url)
    if not analisis.get("ok"):
        return {"ok": False, "error": analisis.get("error", "Fallo en el análisis.")}
    database.save_analisis_detallado(doc_id, analisis)

    # 3) Extraer imágenes si la fuente es un PDF
    imagenes = extraer_imagenes_pdf(dato) if tipo == "pdf" else []

    # 4) Construir el PDF
    try:
        ruta = construir_pdf(doc, analisis, imagenes)
    except Exception as e:
        log.error(f"  Error construyendo el PDF de {doc_id}: {e}")
        return {"ok": False, "error": f"Error al construir el PDF: {e}"}

    return {"ok": True, "ruta": ruta, "imagenes": len(imagenes), "cacheado": False}


# ---------------------------------------------------------------------------
# Generación automática de TODOS los informes (en segundo plano, respeta cuota)
# ---------------------------------------------------------------------------

def listar_pendientes():
    """IDs de documentos que aún no tienen su informe PDF generado."""
    pend = []
    for d in database.get_documents():
        if not os.path.exists(os.path.join(INFORMES_DIR, f"{d['id']}.pdf")):
            pend.append(d["id"])
    return pend


def _es_error_cuota(msg):
    m = (msg or "").lower()
    return any(t in m for t in ("429", "quota", "resource_exhausted", "exhausted", "rate limit"))


def generar_informes_pendientes(max_por_ciclo=None):
    """Genera los informes que falten, hasta max_por_ciclo. Si se agota la cuota
       de Gemini, se detiene y se reanudará en el siguiente ciclo."""
    if not gemini.hay_clave():
        return {"ok": False, "error": "Sin clave de Gemini.", "generados": 0}

    if max_por_ciclo is None:
        max_por_ciclo = getattr(config, "INFORMES_BATCH", 3)

    pendientes = listar_pendientes()
    if not pendientes:
        return {"ok": True, "generados": 0, "restantes": 0, "parado_cuota": False}

    generados, parado_cuota = 0, False
    for doc_id in pendientes[:max_por_ciclo]:
        res = generar_informe(doc_id)
        if res.get("ok"):
            generados += 1
        elif _es_error_cuota(res.get("error")):
            parado_cuota = True
            log.info("  Informes auto: cuota de Gemini agotada; se reanudará luego.")
            break
        # otros errores: se omiten y se reintentarán en el próximo ciclo

    restantes = len(listar_pendientes())
    estado = "CUOTA" if parado_cuota else "OK"
    detalle = "pausado por cuota; reanuda en el próximo ciclo" if parado_cuota else ""
    try:
        database.log_update("Informes PDF (auto)", len(pendientes), generados, estado, detalle)
    except Exception:
        pass
    log.info(f"  Informes auto: {generados} generado(s), {restantes} pendiente(s).")
    return {"ok": True, "generados": generados, "restantes": restantes, "parado_cuota": parado_cuota}
