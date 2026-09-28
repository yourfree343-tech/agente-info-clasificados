"""
Resúmenes con IA de los documentos del archivo, en segundo plano.

Dos fuentes de resumen, de más barata a más cara:
  1. El análisis profundo que ya se hizo para el informe PDF (analisis_detallado):
     se convierte en el resumen de la tarjeta SIN otra llamada al LLM.
  2. Una llamada al motor LLM (analizar_documento) para los que no tienen ninguno.

Los documentos que no se pueden leer (PDF escaneado sin capa de texto, fuente que no
deja descargar) se marcan como "sin_texto" con un aviso honesto, en vez de dejarlos
eternamente "pendientes" o inventar un resumen a partir del título.
"""

import os
import re
import logging

import config
import database
import gemini
import llm
import tareas

log = logging.getLogger(__name__)

_tarea = tareas.TareaFondo("analisis", ultimo_resultado=None)


def estado_actual():
    return _tarea.estado()


def _es_archive_org(url):
    return "archive.org/download/" in (url or "")


def _es_error_cuota(msg):
    m = (msg or "").lower()
    return any(t in m for t in ("429", "402", "quota", "resource_exhausted", "rate limit", "saldo"))


# Frases con las que el modelo admite que NO leyó el documento. Un análisis así rellena
# "hechos" con obviedades sacadas del título ("El archivo se titula...") y no debe
# presentarse como resumen real.
_RELLENO_RE = re.compile(
    r"(sin|no contiene|carece de) (una )?(capa de )?texto (extra[ií]ble|legible|seleccionable)|"
    r"escaneado sin|no se pud(o|ieron) (extraer|acceder|leer|analizar)|"
    r"no pudo ser (analizado|le[ií]do)|falta de texto|informaci[oó]n limitada|"
    r"imposibilidad de (leer|extraer|acceder)|sin acceso al contenido|"
    r"se basa (únicamente|unicamente|solo|sólo) en (los )?metadatos|"
    r"contenido (espec[ií]fico )?(del (archivo|documento) )?no (se pudo determinar|est[aá] disponible)",
    re.IGNORECASE)


def _texto(x):
    """El modelo a veces devuelve una lista donde se pidió un párrafo (y viceversa)."""
    if isinstance(x, list):
        return " ".join(str(i).strip() for i in x if str(i).strip())
    return str(x or "").strip()


def resumen_desde_detallado(analisis):
    """Convierte el análisis profundo del informe PDF en el resumen de la tarjeta.
       Devuelve None si ese análisis está vacío o reconoce que no pudo leer el documento."""
    if not isinstance(analisis, dict):
        return None
    lista = lambda k: [_texto(h) for h in (analisis.get(k) or []) if _texto(h)]  # noqa: E731
    hechos, revel = lista("hechos_clave"), lista("revelaciones")
    if not hechos and not revel:
        return None
    contexto = _texto(analisis.get("contexto"))
    implicaciones = _texto(analisis.get("implicaciones"))
    if _RELLENO_RE.search(f"{contexto} {implicaciones}"):
        return None
    # Primero lo más revelador, luego los hechos concretos, sin repetir.
    puntos = list(dict.fromkeys(revel[:3] + hechos))[:8]
    return {
        "resumen_ejecutivo": contexto or (revel or hechos)[0],
        "puntos_clave": puntos,
        "implicaciones": implicaciones,
        "nivel_confianza": llm.norm_nivel(_texto(analisis.get("nivel_confianza"))),
    }


def _marcar_sin_texto(doc):
    # La confianza es la de la FUENTE (no baja porque no hayamos podido leer el PDF).
    database.update_analysis(doc["id"], llm.RESUMEN_SIN_TEXTO, [], "",
                             doc.get("nivel_confianza") or "MEDIO", marca=database.IA_SIN_TEXTO)


def aplicar_detallado(doc, analisis):
    """Si el documento sigue pendiente de resumen, lo rellena con su análisis profundo.
       Devuelve 'ia', 'sin_texto' o None (no se tocó: ya tenía resumen, o merece la pena
       reintentarlo con el analizador porque hay OCR de archive.org o descripción de la fuente)."""
    if not doc or (doc.get("analizado_ia") or "") != database.IA_PENDIENTE:
        return None
    r = resumen_desde_detallado(analisis)
    if r:
        database.update_analysis(doc["id"], r["resumen_ejecutivo"], r["puntos_clave"],
                                 r["implicaciones"], r["nivel_confianza"], marca="ia")
        return "ia"
    if _es_archive_org(doc.get("url_fuente")) or gemini.descripcion_fuente(doc):
        return None
    _marcar_sin_texto(doc)
    return "sin_texto"


def reclasificar_rellenos():
    """Corrige resúmenes "IA" antiguos que en realidad son relleno de un PDF ilegible
       ("El PDF no contiene texto extraíble..."): la versión anterior los daba por buenos.
       Los de archive.org vuelven a pendientes (ahora se leen con su OCR); el resto pasa a
       "sin texto legible" con un aviso honesto. Devuelve cuántos se corrigieron."""
    corregidos = 0
    for doc in database.get_documents({"ia": "analizado"}):
        if (doc.get("analizado_ia") or "") in ("", database.IA_CURADO):
            continue
        texto = f"{doc.get('resumen_ejecutivo') or ''} {doc.get('implicaciones') or ''}"
        if not _RELLENO_RE.search(texto):
            continue
        if _es_archive_org(doc.get("url_fuente")):
            # Con el texto de relleno fuera: si no, se tomaría por "descripción de la fuente".
            database.update_analysis(doc["id"], "[Pendiente de análisis con IA] Se leerá con el OCR "
                                     "gratuito de archive.org.", [], "",
                                     doc.get("nivel_confianza") or "MEDIO", marca=database.IA_PENDIENTE)
        else:
            _marcar_sin_texto(doc)
        corregidos += 1
    if corregidos:
        log.info(f"  {corregidos} resumen(es) de relleno de PDFs ilegibles reclasificados.")
    return corregidos


def rellenar_desde_detallados():
    """Pasa a resumen todos los análisis profundos ya guardados (coste cero)."""
    hechos = {"ia": 0, "sin_texto": 0}
    for doc_id, analisis in database.get_pendientes_con_detallado():
        estado = aplicar_detallado(database.get_document(doc_id), analisis)
        if estado:
            hechos[estado] += 1
    if hechos["ia"] or hechos["sin_texto"]:
        log.info(f"  Resúmenes rellenados desde informes ya generados: {hechos['ia']} "
                 f"(+{hechos['sin_texto']} marcados sin texto legible).")
    return hechos


def _invalidar_informe_vacio(doc_id):
    """Si el informe PDF de este documento se generó cuando aún no se podía leer (análisis
       vacío) y ahora sí hay contenido, se borra ese PDF derivado para que el generador
       automático lo rehaga con el contenido real."""
    import informe  # import local: informe importa este módulo
    det = database.get_analisis_detallado(doc_id)
    if det is not None and resumen_desde_detallado(det) is None:
        try:
            os.remove(os.path.join(informe.INFORMES_DIR, f"{doc_id}.pdf"))
            log.info(f"  Informe vacío de {doc_id} invalidado; se regenerará con el contenido real.")
        except FileNotFoundError:
            pass


def analizar_uno(doc):
    """Analiza un documento con el motor LLM y guarda el resultado. Devuelve el dict de llm."""
    res = llm.analizar_documento(doc)
    if not res.get("ok"):
        return res
    marca = database.IA_SIN_TEXTO if res.get("sin_texto") else "ia"
    database.update_analysis(doc["id"], res["resumen_ejecutivo"], res["puntos_clave"],
                             res["implicaciones"], res["nivel_confianza"], marca=marca)
    if marca == "ia":
        _invalidar_informe_vacio(doc["id"])
    return res


def _analizar(limite, incluir_sin_texto):
    _tarea.actualizar(fase="aprovechando informes ya generados")
    rellenados = rellenar_desde_detallados()

    docs = database.get_pending_analysis(limit=limite, incluir_sin_texto=incluir_sin_texto)
    total = len(docs)
    analizados, sin_texto, errores = 0, 0, []
    for i, doc in enumerate(docs):
        _tarea.actualizar(fase="resumiendo con IA", progreso=[i, total])
        res = analizar_uno(doc)
        if res.get("ok"):
            if res.get("sin_texto"):
                sin_texto += 1
            else:
                analizados += 1
        else:
            errores.append({"id": doc["id"], "error": res.get("error")})
            if _es_error_cuota(res.get("error")):
                log.info("  Análisis IA: cuota/saldo agotado; se reanudará en el próximo ciclo.")
                break
    _tarea.actualizar(progreso=[total, total])

    resultado = {
        "rellenados": rellenados["ia"],
        "analizados": analizados,
        "sin_texto": sin_texto + rellenados["sin_texto"],
        "errores": errores[:5],
        "restantes": database.count_pending_analysis(),
    }
    _tarea.actualizar(ultimo_resultado=resultado,
                      ultimo_error=errores[0]["error"] if errores and not analizados else None)
    # Al registro de vigilancia solo si pasó algo (el ciclo automático corre cada pocos minutos).
    if analizados or errores or rellenados["ia"]:
        detalle = f"{rellenados['ia']} desde informes" if rellenados["ia"] else ""
        if errores:
            detalle = (detalle + " · " if detalle else "") + f"{len(errores)} con error"
        database.log_update(f"IA análisis ({llm.backend()})", total + rellenados["ia"],
                            analizados + rellenados["ia"], "OK" if not errores else "PARCIAL",
                            detalle)
    log.info(f"  Análisis IA: {analizados} resumido(s), {sin_texto} sin texto, "
             f"{len(errores)} error(es), {resultado['restantes']} pendiente(s).")
    return resultado


def lanzar(limite=None, incluir_sin_texto=False):
    """Inicia un lote de análisis en segundo plano. Devuelve (iniciada, mensaje)."""
    if not llm.disponible():
        return False, llm.mensaje_no_disponible()
    limite = limite or getattr(config, "ANALYZE_BATCH", 5)
    iniciada, msg = _tarea.lanzar(_analizar, limite, incluir_sin_texto,
                                  ocupado="Ya hay un análisis en curso; espera a que termine.")
    return iniciada, (msg or "Análisis iniciado.")


def analizar_auto():
    """Entrada para el planificador: analiza el siguiente lote si hay pendientes."""
    if not llm.disponible():
        return
    if database.count_pending_analysis() == 0:
        return
    iniciada, msg = lanzar()
    if not iniciada:
        log.info(f"  Análisis auto: {msg}")
