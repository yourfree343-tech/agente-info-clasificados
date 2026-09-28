import os
import json
import atexit
import logging
from datetime import datetime, timedelta

from flask import Flask, render_template, jsonify, request, Response, send_file, abort
from apscheduler.schedulers.background import BackgroundScheduler

import config
import database
import updater
import informe
import llm
import detective
import analisis
import analizador

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)
# Fuerza al navegador a revalidar los archivos estáticos (CSS/JS): así un cambio
# de estilo se ve enseguida sin tener que vaciar la caché a mano.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.json.ensure_ascii = False   # JSON legible (tildes tal cual) en la API y la exportación


@app.after_request
def _cabeceras_seguridad(resp):
    # Es una app local, pero no cuesta nada: sin sniffing de tipos, sin incrustarla en
    # iframes ajenos y sin enviar Referer a terceros (además, muchas webs bloquean sus
    # imágenes si llega un Referer de otro sitio: sin él cargan más miniaturas).
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.route("/")
def index():
    return render_template("index.html", pagina="documentos")


@app.route("/investigaciones")
def investigaciones_page():
    return render_template("investigaciones.html", pagina="investigaciones")


@app.route("/conexiones")
def conexiones_page():
    return render_template("conexiones.html", pagina="conexiones")


@app.route("/api/documentos")
def api_documentos():
    filters = {
        "categoria": request.args.get("categoria"),
        "pais": request.args.get("pais"),
        "confianza": request.args.get("confianza"),
        "verificado": request.args.get("verificado"),
        "busqueda": request.args.get("busqueda"),
        "fecha_desde": request.args.get("fecha_desde"),
        "fecha_hasta": request.args.get("fecha_hasta"),
        "fuente": request.args.get("fuente"),
        "ia": request.args.get("ia"),
        "id": request.args.get("id"),
    }
    filters = {k: v for k, v in filters.items() if v}
    orden = request.args.get("orden")

    # Paginación en el propio SQL: si no se pide página, se devuelve todo (compatibilidad
    # con /api/exportar y otros usos que quieren el listado completo).
    page = request.args.get("page", type=int)
    page_size = request.args.get("page_size", type=int) or 10
    if page:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        docs = database.get_documents(filters, limit=page_size, offset=(page - 1) * page_size,
                                      orden=orden)
        for d in docs:
            # Para ofrecer "Descargar informe" directo si ya existe (sin volver a generarlo).
            d["tiene_informe"] = informe.tiene_informe(d["id"])
            d.pop("analisis_detallado", None)   # pesado y la tarjeta no lo usa
        return jsonify({
            "items": docs,
            "total": database.count_documents(filters),
            "page": page,
            "page_size": page_size,
        })

    docs = database.get_documents(filters, orden=orden)
    return jsonify(docs)


@app.route("/api/filtros")
def api_filtros():
    return jsonify(database.get_filtros_documentos())


@app.route("/api/stats")
def api_stats():
    stats = database.get_stats()
    stats["informes"] = stats["total"] - len(informe.listar_pendientes())
    return jsonify(stats)


@app.route("/api/actualizaciones")
def api_actualizaciones():
    return jsonify(database.get_last_updates(20))


@app.route("/api/actualizar", methods=["POST"])
def api_actualizar():
    # Arranca la actualización EN SEGUNDO PLANO y responde al instante: el scraping
    # de varias fuentes + IA puede tardar minutos. La página consulta
    # /api/actualizar/estado para saber cuándo termina (mismo patrón que el detective).
    iniciada, msg = updater.lanzar()
    if not iniciada:
        return jsonify({"ok": False, "error": msg, "en_curso": True}), 409
    return jsonify({"ok": True, "iniciada": True, "mensaje": msg})


@app.route("/api/actualizar/estado")
def api_actualizar_estado():
    return jsonify(updater.estado_actual())


@app.route("/api/ia/estado")
def api_ia_estado():
    return jsonify({
        "configurada": llm.disponible(),
        "modelo": llm.nombre_motor(),
        "mensaje": None if llm.disponible() else llm.mensaje_no_disponible(),
        "vision": llm.vision_disponible(),
        "pendientes": database.count_pending_analysis(),
        "titulos_pendientes": database.count_titulos_pendientes(),
        "informes_pendientes": len(informe.listar_pendientes()),
        "analisis": analizador.estado_actual(),
    })


@app.route("/api/ia/traducir_titulos", methods=["POST"])
def api_ia_traducir_titulos():
    if not llm.disponible():
        return jsonify({"ok": False, "error": llm.mensaje_no_disponible()}), 400
    pendientes = database.get_titulos_pendientes()
    if not pendientes:
        return jsonify({"ok": True, "traducidos": 0, "restantes": 0})
    res = llm.traducir_titulos(pendientes)
    for doc_id, titulo_es in res.get("traducciones", {}).items():
        database.set_titulo(doc_id, titulo_es)
    return jsonify({
        "ok": res.get("ok", True),
        "traducidos": len(res.get("traducciones", {})),
        "restantes": database.count_titulos_pendientes(),
        "error": res.get("error"),
    })


@app.route("/api/ia/analizar/<doc_id>", methods=["POST"])
def api_ia_analizar(doc_id):
    doc = database.get_document(doc_id)
    if not doc:
        return jsonify({"ok": False, "error": "Documento no encontrado."}), 404
    if not llm.disponible():
        return jsonify({"ok": False, "error": llm.mensaje_no_disponible()}), 400
    res = analizador.analizar_uno(doc)
    if not res.get("ok"):
        return jsonify(res), 400
    doc = database.get_document(doc_id)
    doc.pop("analisis_detallado", None)
    return jsonify({"ok": True, "sin_texto": res.get("sin_texto", False), "doc": doc})


@app.route("/api/ia/analizar_pendientes", methods=["POST"])
def api_ia_analizar_pendientes():
    # En segundo plano: un lote puede tardar minutos y dejaría la petición colgada.
    # La página consulta /api/ia/estado (campo "analisis") para ver el progreso.
    iniciada, msg = analizador.lanzar(incluir_sin_texto=request.args.get("reintentar") == "1")
    if not iniciada:
        en_curso = analizador.estado_actual()["en_curso"]
        return jsonify({"ok": False, "error": msg, "en_curso": en_curso}), 409 if en_curso else 400
    return jsonify({"ok": True, "iniciada": True, "mensaje": msg})


@app.route("/api/informe/<doc_id>/generar", methods=["POST"])
def api_informe_generar(doc_id):
    forzar = request.args.get("forzar") == "1"
    res = informe.generar_informe(doc_id, forzar=forzar)
    if not res.get("ok"):
        return jsonify(res), 400
    return jsonify({
        "ok": True,
        "cacheado": res.get("cacheado", False),
        "imagenes": res.get("imagenes", 0),
        "url_descarga": f"/api/informe/{doc_id}",
    })


@app.route("/api/informe/<doc_id>")
def api_informe_descargar(doc_id):
    ruta = os.path.join(informe.INFORMES_DIR, f"{doc_id}.pdf")
    if not os.path.exists(ruta):
        abort(404, description="El informe aún no se ha generado.")
    nombre = f"informe_{doc_id}.pdf"
    return send_file(ruta, mimetype="application/pdf", as_attachment=True, download_name=nombre)


@app.route("/api/investigaciones")
def api_investigaciones():
    filters = {
        "certeza": request.args.get("certeza"),
        "categoria": request.args.get("categoria"),
        "busqueda": request.args.get("busqueda"),
        "id": request.args.get("id"),
    }
    filters = {k: v for k, v in filters.items() if v}

    page = request.args.get("page", type=int)
    page_size = request.args.get("page_size", type=int) or 8
    if page:
        page = max(1, page)
        page_size = max(1, min(page_size, 50))
        invs = database.get_investigaciones(filters, limit=page_size, offset=(page - 1) * page_size)
        for inv in invs:
            inv["fuentes_detalle"] = analisis.detalle_fuentes(inv.get("fuentes"))
        return jsonify({
            "items": invs,
            "total": database.count_investigaciones(filters),
            "page": page,
            "page_size": page_size,
            "categorias": database.get_categorias_investigaciones(),
        })
    return jsonify(database.get_investigaciones(filters))


@app.route("/api/investigacion/<inv_id>", methods=["DELETE"])
def api_investigacion_borrar(inv_id):
    borrado = database.delete_investigacion(inv_id)
    if not borrado:
        return jsonify({"ok": False, "error": "Dossier no encontrado."}), 404
    return jsonify({"ok": True})


@app.route("/api/investigacion/<inv_id>/contraargumento", methods=["POST"])
def api_investigacion_contraargumento(inv_id):
    res = detective.generar_contraargumento(inv_id)
    if not res.get("ok"):
        return jsonify(res), 400
    return jsonify(res)


@app.route("/api/conexiones")
def api_conexiones():
    return jsonify(analisis.calcular_conexiones())


@app.route("/api/temas")
def api_temas_listar():
    return jsonify(database.get_cola_temas())


@app.route("/api/temas", methods=["POST"])
def api_temas_encolar():
    data = request.get_json(silent=True) or {}
    tema = (data.get("tema") or "").strip()[:300]
    if not tema:
        return jsonify({"ok": False, "error": "Falta el tema."}), 400
    database.encolar_tema(tema)
    return jsonify({"ok": True})


@app.route("/api/temas/<int:tema_id>", methods=["DELETE"])
def api_temas_borrar(tema_id):
    borrado = database.eliminar_tema_cola(tema_id)
    if not borrado:
        return jsonify({"ok": False, "error": "No encontrado."}), 404
    return jsonify({"ok": True})


@app.route("/api/investigacion/<inv_id>/pdf")
def api_investigacion_pdf(inv_id):
    inv = database.get_investigacion(inv_id)
    if not inv:
        abort(404, description="Dossier no encontrado.")
    try:
        buf = informe.pdf_investigacion_bytes(inv)
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo generar el PDF: {e}"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"dossier_{inv_id}.pdf")


@app.route("/api/detective/estado")
def api_detective_estado():
    est = detective.estado_actual()
    return jsonify({
        "habilitado": getattr(config, "DETECTIVE_ENABLED", False),
        "auto": getattr(config, "DETECTIVE_AUTO", False),
        "interval_min": getattr(config, "DETECTIVE_INTERVAL_MIN", None),
        "motor": llm.nombre_motor(),
        "motor_disponible": llm.disponible(),
        "motor_local": llm.es_local(),
        "total": database.count_investigaciones(),
        "en_curso": est["en_curso"],
        "tema": est.get("tema"),
        "fase": est.get("fase"),
        "desde": est.get("desde"),
        "ultimo_fin": est.get("ultimo_fin"),
        "ultimo_titulo": est["ultimo_titulo"],
        "ultimo_id": est.get("ultimo_id"),
        "ultimo_error": est["ultimo_error"],
    })


@app.route("/api/investigar", methods=["POST"])
def api_investigar():
    # Arranca la investigación EN SEGUNDO PLANO y responde al instante: el modelo
    # local tarda minutos y dejar la petición HTTP abierta colgaría el navegador.
    # La página consulta /api/detective/estado para saber cuándo termina.
    if not getattr(config, "DETECTIVE_ENABLED", False):
        return jsonify({"ok": False, "error": "El detective está desactivado en config.py."}), 400
    if not llm.disponible():
        return jsonify({"ok": False, "error": llm.mensaje_no_disponible()}), 400
    tema = (request.args.get("tema") or "").strip()[:300] or None
    iniciada, msg = detective.lanzar(tema)
    if not iniciada:
        return jsonify({"ok": False, "error": msg, "en_curso": True}), 409
    return jsonify({"ok": True, "iniciada": True, "mensaje": msg})


@app.route("/api/health")
def api_health():
    stats = database.get_stats()
    return jsonify({
        "ok": True,
        "documentos": stats["total"],
        "auto_update": config.AUTO_UPDATE_ENABLED,
        "hora_actualizacion": f"{config.UPDATE_HOUR:02d}:{config.UPDATE_MINUTE:02d}",
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/exportar")
def api_exportar():
    docs = database.get_documents()
    json_str = json.dumps(docs, ensure_ascii=False, indent=2)
    return Response(
        json_str,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=documentos_clasificados.json"}
    )


def create_app():
    database.init_db()
    database.seed_initial_data()
    # Coste cero: los documentos que ya tienen informe PDF reciben su resumen de ahí.
    try:
        analizador.reclasificar_rellenos()
        analizador.rellenar_desde_detallados()
    except Exception as e:
        logging.warning(f"No se pudieron rellenar resúmenes desde los informes: {e}")

    auto_analisis = getattr(config, "AUTO_ANALYZE_NEW", False)
    jobs = (config.AUTO_UPDATE_ENABLED
            or getattr(config, "AUTO_INFORMES_ENABLED", False)
            or auto_analisis
            or (getattr(config, "DETECTIVE_ENABLED", False) and getattr(config, "DETECTIVE_AUTO", False)))
    if not jobs:
        return None

    scheduler = BackgroundScheduler(timezone=config.TIMEZONE)

    if config.AUTO_UPDATE_ENABLED:
        scheduler.add_job(
            updater.actualizar_auto, "cron",
            hour=config.UPDATE_HOUR, minute=config.UPDATE_MINUTE,
            id="actualizacion_diaria"
        )

    # Worker de informes PDF automáticos: genera de pocos en pocos y reanuda solo.
    if getattr(config, "AUTO_INFORMES_ENABLED", False):
        scheduler.add_job(
            informe.generar_informes_pendientes, "interval",
            minutes=config.INFORMES_INTERVAL_MIN, id="auto_informes",
            next_run_time=datetime.now() + timedelta(minutes=2),
            max_instances=1, coalesce=True,
        )

    # Resúmenes con IA de lo que quede pendiente, de poco en poco.
    if auto_analisis:
        scheduler.add_job(
            analizador.analizar_auto, "interval",
            minutes=getattr(config, "ANALISIS_INTERVAL_MIN", 15), id="auto_analisis",
            next_run_time=datetime.now() + timedelta(minutes=1),
            max_instances=1, coalesce=True,
        )

    # Detective autónomo (si está activado el modo automático).
    if getattr(config, "DETECTIVE_ENABLED", False) and getattr(config, "DETECTIVE_AUTO", False):
        scheduler.add_job(
            detective.investigar_auto, "interval",
            minutes=config.DETECTIVE_INTERVAL_MIN, id="detective_auto",
            next_run_time=datetime.now() + timedelta(minutes=3),
            max_instances=1, coalesce=True,
        )

    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler


def _abrir_navegador():
    import threading, webbrowser, time
    def _abrir():
        time.sleep(2.0)
        try:
            webbrowser.open(f"http://localhost:{config.PORT}")
        except Exception:
            pass
    threading.Thread(target=_abrir, daemon=True).start()


if __name__ == "__main__":
    create_app()
    if getattr(config, "OPEN_BROWSER_ON_START", True):
        _abrir_navegador()
    print("\n" + "=" * 60)
    print("  AGENTE INFO CLASIFICADOS")
    print(f"  Panel disponible en: http://localhost:{config.PORT}")
    if config.AUTO_UPDATE_ENABLED:
        print(f"  Actualización automática: cada día a las "
              f"{config.UPDATE_HOUR:02d}:{config.UPDATE_MINUTE:02d} ({config.TIMEZONE})")
    else:
        print("  Actualización automática: DESACTIVADA")
    if getattr(config, "AUTO_INFORMES_ENABLED", False):
        print(f"  Informes PDF automáticos: cada {config.INFORMES_INTERVAL_MIN} min "
              f"(se pausan si se agota la cuota del motor IA)")
    print(f"  Motor IA: {llm.nombre_motor()}" + ("" if llm.disponible() else "  (NO disponible)"))
    print("=" * 60 + "\n")
    # threaded=True: sin esto, Werkzeug atiende una petición a la vez y cualquier
    # operación larga (actualizar fuentes, generar un informe con IA) congela TODA
    # la app para cualquier otra pestaña/petición hasta que termina.
    app.run(host=config.HOST, debug=False, port=config.PORT, use_reloader=False, threaded=True)
