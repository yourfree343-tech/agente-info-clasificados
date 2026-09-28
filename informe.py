"""
Generación de informes PDF por documento (y de los dossiers del detective).

Combina:
  - El análisis detallado del motor IA (información importante del documento).
  - Las imágenes extraídas del PDF original (si las hay).
  - Una maquetación sobria con reportlab: cabecera y pie en cada página, ficha del
    documento en tabla y tipografía IBM Plex (la misma que la web), con caída a
    Helvetica si no estuvieran las fuentes.

El informe se guarda en data/informes/<doc_id>.pdf y se devuelve su ruta.
"""

import io
import os
import logging
from datetime import datetime

import requests
import fitz  # PyMuPDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, HRFlowable, ListFlowable, ListItem,
    Table, TableStyle, KeepTogether,
)
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import config
import database
import gemini
import llm
import analisis as analisis_mod
import analizador

log = logging.getLogger(__name__)

INFORMES_DIR = os.path.join(os.path.dirname(__file__), "data", "informes")
_FUENTES_DIR = os.path.join(os.path.dirname(__file__), "static", "fonts", "ttf")

# Paleta de impresión: pizarra + ámbar (la de la web, oscurecida para papel blanco).
TINTA = colors.HexColor("#18202b")
TINTA_2 = colors.HexColor("#3c4757")
TENUE = colors.HexColor("#6b7585")
REGLA = colors.HexColor("#d9dde3")
FONDO = colors.HexColor("#f4f5f7")
AMBAR = colors.HexColor("#a66d12")
VIOLETA = colors.HexColor("#5b4bb7")
ROJO = colors.HexColor("#b3413b")
VERDE = colors.HexColor("#2f7d5b")
AZUL = colors.HexColor("#2f6aa3")


# ---------------------------------------------------------------------------
# Tipografía
# ---------------------------------------------------------------------------

def _registrar_fuentes():
    """Registra IBM Plex si está en static/fonts/ttf. Devuelve (sans, sans_bold, sans_it, mono)."""
    archivos = {
        "Plex": "IBMPlexSans-Regular.ttf",
        "Plex-Bold": "IBMPlexSans-SemiBold.ttf",
        "Plex-Italic": "IBMPlexSans-Italic.ttf",
        "PlexMono": "IBMPlexMono-Regular.ttf",
    }
    try:
        for nombre, archivo in archivos.items():
            if nombre not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(nombre, os.path.join(_FUENTES_DIR, archivo)))
        pdfmetrics.registerFontFamily("Plex", normal="Plex", bold="Plex-Bold",
                                      italic="Plex-Italic", boldItalic="Plex-Bold")
        return "Plex", "Plex-Bold", "Plex-Italic", "PlexMono"
    except Exception as e:
        log.info(f"  Fuentes IBM Plex no disponibles para el PDF ({e}); se usa Helvetica.")
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"


SANS, SANS_B, SANS_I, MONO = _registrar_fuentes()


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

def _estilos(acento=AMBAR):
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName=SANS, fontSize=10.2,
                          leading=15, textColor=TINTA)
    return {
        "kicker": ParagraphStyle("kicker", parent=base, fontName=MONO, fontSize=7.8,
                                 textColor=acento, spaceAfter=5, leading=10),
        "titulo": ParagraphStyle("titulo", parent=base, fontName=SANS_B, fontSize=19,
                                 leading=24, spaceAfter=5),
        "subtitulo": ParagraphStyle("subtitulo", parent=base, fontSize=9, leading=13,
                                    textColor=TENUE, spaceAfter=2),
        "seccion": ParagraphStyle("seccion", parent=base, fontName=MONO, fontSize=8.6,
                                  leading=11, textColor=acento, spaceBefore=15, spaceAfter=7),
        "cuerpo": ParagraphStyle("cuerpo", parent=base, alignment=TA_JUSTIFY, spaceAfter=6),
        "vineta": ParagraphStyle("vineta", parent=base, textColor=TINTA_2),
        "cita": ParagraphStyle("cita", parent=base, fontName=SANS_I, fontSize=9.8, leading=14,
                               leftIndent=10, textColor=TINTA_2, spaceAfter=6),
        "meta_k": ParagraphStyle("meta_k", parent=base, fontName=MONO, fontSize=7.4,
                                 leading=10, textColor=TENUE),
        "meta_v": ParagraphStyle("meta_v", parent=base, fontSize=9, leading=12.5),
        "fuente": ParagraphStyle("fuente", parent=base, fontSize=8.2, leading=11.5,
                                 textColor=TINTA_2),
        "pie": ParagraphStyle("pie", parent=base, fontSize=7.6, leading=10,
                              textColor=TENUE, alignment=TA_CENTER),
        "aviso": ParagraphStyle("aviso", parent=base, fontSize=8.8, leading=12.5,
                                textColor=colors.HexColor("#6b4a09")),
    }


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


def _seccion(texto, est):
    return _p(texto.upper(), est["seccion"])


def _lista(items, estilo, color=AMBAR):
    flow = []
    for it in items or []:
        flow.append(ListItem(_p(it, estilo), leftIndent=10))
    if not flow:
        return _p("(Sin datos)", estilo)
    return ListFlowable(flow, bulletType="bullet", bulletColor=color, bulletFontName=SANS,
                        bulletFontSize=9, bulletOffsetY=-1, start="•", leftIndent=12)


def _caja(flowables, fondo, borde, padding=8):
    """Recuadro con fondo y borde fino (avisos, veredicto, voz escéptica...)."""
    t = Table([[flowables]], colWidths=["100%"])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fondo),
        ("BOX", (0, 0), (-1, -1), 0.6, borde),
        ("LEFTPADDING", (0, 0), (-1, -1), padding + 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding + 2),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]))
    return t


def _ficha(pares, est):
    """Tabla de metadatos en dos columnas (clave en mono tenue, valor en sans)."""
    filas = [[_p(k.upper(), est["meta_k"]), _p(v or "—", est["meta_v"])] for k, v in pares]
    t = Table(filas, colWidths=[38 * mm, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, REGLA),
        ("BOX", (0, 0), (-1, -1), 0.6, REGLA),
        ("BACKGROUND", (0, 0), (0, -1), FONDO),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _plantilla(etiqueta, ref, acento):
    """Callback de página: banda superior con la marca y la referencia, pie con número."""
    generado = datetime.now().strftime("%d/%m/%Y %H:%M")

    def dibujar(canvas, doc):
        canvas.saveState()
        ancho, alto = A4
        x0, x1 = doc.leftMargin, ancho - doc.rightMargin
        y = alto - 12 * mm
        canvas.setFont(MONO, 7.2)
        canvas.setFillColor(TENUE)
        canvas.drawString(x0, y, f"ARCHIVO·CLASIFICADO  —  {etiqueta}")
        canvas.drawRightString(x1, y, ref)
        canvas.setStrokeColor(acento)
        canvas.setLineWidth(0.9)
        canvas.line(x0, y - 2.6 * mm, x0 + 18 * mm, y - 2.6 * mm)
        canvas.setStrokeColor(REGLA)
        canvas.setLineWidth(0.5)
        canvas.line(x0 + 18 * mm, y - 2.6 * mm, x1, y - 2.6 * mm)
        canvas.line(x0, 12 * mm, x1, 12 * mm)
        canvas.setFont(SANS, 7.2)
        canvas.drawString(x0, 8.2 * mm, f"Generado el {generado} · Verifica siempre con la fuente original antes de citar.")
        canvas.drawRightString(x1, 8.2 * mm, f"Página {doc.page}")
        canvas.restoreState()

    return dibujar


def _documento(destino, titulo_pdf):
    return SimpleDocTemplate(
        destino, pagesize=A4,
        leftMargin=21 * mm, rightMargin=21 * mm, topMargin=24 * mm, bottomMargin=19 * mm,
        title=titulo_pdf, author="Agente Info Clasificados",
    )


# ---------------------------------------------------------------------------
# Construcción del informe
# ---------------------------------------------------------------------------

def _img_flowable(img_dict, max_ancho=150 * mm, max_alto=120 * mm):
    """Convierte bytes de imagen en un flowable Image escalado para caber en la página."""
    try:
        reader = ImageReader(io.BytesIO(img_dict["bytes"]))
        iw, ih = reader.getSize()
        if iw <= 0 or ih <= 0:
            return None
        escala = min(max_ancho / iw, max_alto / ih, 1.0)
        return Image(io.BytesIO(img_dict["bytes"]), width=iw * escala, height=ih * escala)
    except Exception as e:
        log.info(f"  Imagen descartada: {e}")
        return None


# ---------------------------------------------------------------------------
# PDF de un dossier del detective (investigación especulativa)
# ---------------------------------------------------------------------------

def _descargar_imagen(url, timeout=8):
    """Descarga una imagen por URL y devuelve sus bytes, o None si falla."""
    if not url or not url.startswith("http"):
        return None
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "").lower()
        path = url.lower().split("?")[0]
        if "image" in ct or path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
            return r.content
    except Exception:
        return None
    return None


def pdf_investigacion_bytes(inv):
    """Construye en memoria el PDF de un dossier del detective. Devuelve un BytesIO."""
    est = _estilos(VIOLETA)
    buf = io.BytesIO()
    pdf = _documento(buf, f"Dossier — {inv.get('titulo', '')}")
    F = []

    # Cabecera
    F.append(_p("DOSSIER DEL DETECTIVE · INVESTIGACIÓN ESPECULATIVA", est["kicker"]))
    F.append(_p(inv.get("titulo") or inv.get("tema") or "Dossier", est["titulo"]))
    meta = [b for b in (
        (inv.get("fecha", "") or "").replace("T", " ").split(".")[0][:16],
        inv.get("categoria", ""),
        ("Certeza " + inv["nivel_certeza"].lower()) if inv.get("nivel_certeza") else "",
        inv.get("motor", ""),
    ) if b]
    F.append(_p(" · ".join(meta), est["subtitulo"]))
    F.append(Spacer(1, 8))

    F.append(_caja([_p("Dossier especulativo. Las hipótesis y conexiones NO son hechos probados: "
                       "se incluyen marcadas como tales. Contrasta siempre con las fuentes citadas.",
                       est["aviso"])], colors.HexColor("#fbf3e1"), colors.HexColor("#e7cf9a")))
    F.append(Spacer(1, 8))

    if inv.get("gancho"):
        F.append(_p(inv["gancho"], est["cita"]))

    relacionados = inv.get("documentos_relacionados") or []
    if relacionados:
        F.append(_seccion("Respaldo en el archivo oficial", est))
        F.append(_lista([f"{d.get('titulo', '')} — {d.get('url_fuente', '')}" for d in relacionados],
                        est["vineta"], VERDE))

    # Imágenes relacionadas (se descargan unas pocas; se omiten si fallan)
    flows_img = []
    for im in (inv.get("imagenes") or [])[:3]:
        b = _descargar_imagen(im.get("thumb") or im.get("url"))
        if b:
            fi = _img_flowable({"bytes": b}, max_ancho=110 * mm, max_alto=80 * mm)
            if fi:
                flows_img.append((fi, im.get("origen") or ""))
    if flows_img:
        F.append(_seccion("Imágenes relacionadas", est))
        for fi, origen in flows_img:
            bloque = [fi]
            if origen:
                bloque.append(_p(origen, est["subtitulo"]))
            bloque.append(Spacer(1, 8))
            F.append(KeepTogether(bloque))

    # Secciones del dossier
    F.append(_seccion("Hechos verificados", est))
    F.append(_lista(inv.get("hechos_verificados"), est["vineta"], VERDE))

    if inv.get("hipotesis"):
        F.append(_seccion("Hipótesis y conexiones", est))
        F.append(_lista(inv.get("hipotesis"), est["vineta"], AMBAR))

    if inv.get("conexiones"):
        F.append(_seccion("Patrones / símbolos", est))
        F.append(_lista(inv.get("conexiones"), est["vineta"], AZUL))

    if inv.get("especulacion"):
        F.append(_seccion("Especulación (no probado)", est))
        F.append(_caja([_lista(inv.get("especulacion"), est["vineta"], ROJO)],
                       colors.HexColor("#fbeeed"), colors.HexColor("#ebc3bf")))

    if inv.get("veredicto"):
        F.append(_seccion("Veredicto del analista", est))
        F.append(_caja([_p(inv["veredicto"], est["cuerpo"])], FONDO, REGLA))

    if inv.get("contraargumento"):
        F.append(_seccion("Voz escéptica", est))
        F.append(_caja([_p(inv["contraargumento"], est["cuerpo"])],
                       colors.HexColor("#edf3fa"), colors.HexColor("#c3d6ea")))

    fuentes = analisis_mod.detalle_fuentes(inv.get("fuentes") or [])
    if fuentes["items"]:
        F.append(_seccion("Fuentes citadas", est))
        resumen = " · ".join(f"{analisis_mod.TIPOS_FUENTE[t]}: {n}"
                             for t, n in sorted(fuentes["por_tipo"].items(), key=lambda x: -x[1]))
        F.append(_p(resumen, est["subtitulo"]))
        F.append(Spacer(1, 4))
        for f in fuentes["items"][:30]:
            F.append(_p_rich(f'<font name="{MONO}" size="7" color="#6b7585">{_esc(f["etiqueta"].upper())}</font>'
                             f'  {_esc(f["url"])}', est["fuente"]))

    pdf.build(F, onFirstPage=_plantilla("DOSSIER", inv.get("id", ""), VIOLETA),
              onLaterPages=_plantilla("DOSSIER", inv.get("id", ""), VIOLETA))
    buf.seek(0)
    return buf


def construir_pdf(doc, analisis, imagenes):
    os.makedirs(INFORMES_DIR, exist_ok=True)
    ruta = os.path.join(INFORMES_DIR, f"{doc['id']}.pdf")
    est = _estilos(AMBAR)
    pdf = _documento(ruta, f"Informe - {doc.get('titulo', '')}")
    F = []  # flowables

    # Cabecera
    F.append(_p("INFORME DE DOCUMENTO DESCLASIFICADO", est["kicker"]))
    F.append(_p(analisis.get("titulo_informe") or doc.get("titulo", "Informe"), est["titulo"]))
    if analisis.get("titulo_informe") and analisis["titulo_informe"] != doc.get("titulo"):
        F.append(_p(doc.get("titulo", ""), est["subtitulo"]))
    F.append(Spacer(1, 10))

    # Ficha de metadatos
    F.append(_ficha([
        ("Organismo(s)", ", ".join(doc.get("organismo", []) or [])),
        ("País", doc.get("pais", "")),
        ("Fecha", doc.get("fecha_documento", "")),
        ("Estado", doc.get("estado_desclasificacion", "")),
        ("Verificación", f"{doc.get('verificado', '—')} · fiabilidad de la fuente {(doc.get('fuente_fiabilidad') or '—').lower()}"),
        ("Confianza", analisis.get("nivel_confianza", "")),
        ("Fuente", doc.get("url_fuente", "")),
    ], est))

    if analisis.get("_tipo_fuente") == "none":
        F.append(Spacer(1, 8))
        F.append(_caja([_p("No se pudo acceder al contenido completo del documento original. "
                           "Este informe se basa en información limitada (metadatos y fuentes secundarias).",
                           est["aviso"])], colors.HexColor("#fbf3e1"), colors.HexColor("#e7cf9a")))
    elif analisis.get("_tipo_fuente") == "imagenes":
        F.append(Spacer(1, 8))
        F.append(_caja([_p("Documento escaneado: el análisis se hizo leyendo las primeras páginas "
                           "como imágenes, no el documento completo.", est["aviso"])],
                       colors.HexColor("#fbf3e1"), colors.HexColor("#e7cf9a")))

    if analisis.get("contexto"):
        F.append(_seccion("Contexto", est))
        F.append(_p(analizador._texto(analisis["contexto"]), est["cuerpo"]))

    F.append(_seccion("Hechos clave", est))
    F.append(_lista(analisis.get("hechos_clave"), est["vineta"]))

    if analisis.get("revelaciones"):
        F.append(_seccion("Lo más importante / revelaciones", est))
        F.append(_lista(analisis.get("revelaciones"), est["vineta"]))

    if analisis.get("datos_concretos"):
        F.append(_seccion("Datos concretos · personas, fechas, lugares, expedientes", est))
        F.append(_lista(analisis.get("datos_concretos"), est["vineta"], TENUE))

    citas = analisis.get("citas_textuales") or []
    if citas:
        F.append(_seccion("Citas textuales", est))
        for c in citas:
            if isinstance(c, dict):
                txt = _esc(c.get("cita", ""))
                ub = _esc(c.get("ubicacion", ""))
                F.append(_p_rich(f'«{txt}»' + (f' <font size=8 color="#6b7585">[{ub}]</font>' if ub else ""), est["cita"]))
            else:
                F.append(_p(f"«{c}»", est["cita"]))

    if analisis.get("implicaciones"):
        F.append(_seccion("Implicaciones", est))
        F.append(_caja([_p(analizador._texto(analisis["implicaciones"]), est["cuerpo"])], FONDO, REGLA))

    # Imágenes del documento original
    flows_img = [fi for fi in (_img_flowable(im) for im in (imagenes or [])) if fi]
    if flows_img:
        F.append(_seccion("Imágenes del documento original", est))
        for i, fi in enumerate(flows_img, 1):
            F.append(KeepTogether([fi, _p(f"Imagen {i} extraída del documento original.", est["subtitulo"]),
                                   Spacer(1, 8)]))

    F.append(Spacer(1, 12))
    F.append(_p(f"Análisis automático con {llm.nombre_motor()}. Resumen generado por IA: "
                f"verifica siempre con la fuente oficial antes de citar.", est["pie"]))

    plantilla = _plantilla("INFORME", doc["id"], AMBAR)
    pdf.build(F, onFirstPage=plantilla, onLaterPages=plantilla)
    return ruta


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def generar_informe(doc_id, forzar=False):
    """Genera (o reutiliza) el informe PDF de un documento. Devuelve dict con ok + ruta."""
    doc = database.get_document(doc_id)
    if not doc:
        return {"ok": False, "error": "Documento no encontrado."}

    ruta = os.path.join(INFORMES_DIR, f"{doc_id}.pdf")
    if os.path.exists(ruta) and not forzar:
        return {"ok": True, "ruta": ruta, "cacheado": True}

    if not llm.disponible():
        return {"ok": False, "error": llm.mensaje_no_disponible()}

    # 1) Descargar el contenido una sola vez
    tipo, dato, url = gemini.obtener_contenido(doc)

    # 2) Análisis detallado con el motor IA activo (Gemini visión o LM Studio texto)
    analisis = llm.analizar_detallado(doc, tipo, dato, url)
    if not analisis.get("ok"):
        return {"ok": False, "error": analisis.get("error", "Fallo en el análisis.")}
    database.save_analisis_detallado(doc_id, analisis)
    # El mismo análisis sirve de resumen de la tarjeta si aún no tenía (sin otra llamada).
    try:
        analizador.aplicar_detallado(doc, analisis)
    except Exception as e:
        log.info(f"  No se pudo rellenar el resumen de {doc_id} desde el informe: {e}")

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

def tiene_informe(doc_id):
    return os.path.exists(os.path.join(INFORMES_DIR, f"{doc_id}.pdf"))


def listar_pendientes():
    """IDs de documentos que aún no tienen su informe PDF generado."""
    return [doc_id for doc_id in database.get_all_document_ids() if not tiene_informe(doc_id)]


def _es_error_cuota(msg):
    m = (msg or "").lower()
    return any(t in m for t in ("429", "402", "quota", "resource_exhausted", "exhausted", "rate limit"))


def generar_informes_pendientes(max_por_ciclo=None):
    """Genera los informes que falten, hasta max_por_ciclo. Si se agota la cuota
       del motor IA (Gemini), se detiene y se reanudará en el siguiente ciclo."""
    if not llm.disponible():
        return {"ok": False, "error": llm.mensaje_no_disponible(), "generados": 0}

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
            log.info("  Informes auto: cuota del motor IA agotada; se reanudará luego.")
            break
        # otros errores: se omiten y se reintentarán en el próximo ciclo

    restantes = len(listar_pendientes())
    estado = "CUOTA" if parado_cuota else "OK"
    detalle = "pausado por cuota; reanuda en el próximo ciclo" if parado_cuota else ""
    # Al registro de vigilancia solo si hubo novedades (corre cada pocos minutos).
    if generados or parado_cuota:
        try:
            database.log_update("Informes PDF (auto)", len(pendientes), generados, estado, detalle)
        except Exception:
            pass
    log.info(f"  Informes auto: {generados} generado(s), {restantes} pendiente(s).")
    return {"ok": True, "generados": generados, "restantes": restantes, "parado_cuota": parado_cuota}
