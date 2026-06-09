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
import gemini
import informe
import llm
import detective

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)
# Fuerza al navegador a revalidar los archivos estáticos (CSS/JS): así un cambio
# de estilo se ve enseguida sin tener que vaciar la caché a mano.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/investigaciones")
def investigaciones_page():
    return render_template("investigaciones.html")


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
    }
    docs = database.get_documents({k: v for k, v in filters.items() if v})
    return jsonify(docs)


@app.route("/api/stats")
def api_stats():
    return jsonify(database.get_stats())


@app.route("/api/actualizaciones")
def api_actualizaciones():
    return jsonify(database.get_last_updates(20))


@app.route("/api/actualizar", methods=["POST"])
def api_actualizar():
    try:
        nuevos = updater.run_update()
        return jsonify({"ok": True, "nuevos": nuevos, "timestamp": datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ia/estado")
def api_ia_estado():
    return jsonify({
        "configurada": llm.disponible(),
        "modelo": llm.nombre_motor(),
        "pendientes": database.count_pending_analysis(),
        "titulos_pendientes": database.count_titulos_pendientes(),
        "informes_pendientes": len(informe.listar_pendientes()),
    })


@app.route("/api/ia/traducir_titulos", methods=["POST"])
def api_ia_traducir_titulos():
    if not llm.disponible():
        return jsonify({"ok": False, "error": f"El motor IA ({llm.backend()}) no está disponible."}), 400
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
    res = llm.analizar_documento(doc)
    if not res.get("ok"):
        return jsonify(res), 400
    database.update_analysis(
        doc_id, res["resumen_ejecutivo"], res["puntos_clave"],
        res["implicaciones"], res["nivel_confianza"]
    )
    return jsonify({"ok": True, "doc": database.get_document(doc_id)})


@app.route("/api/ia/analizar_pendientes", methods=["POST"])
def api_ia_analizar_pendientes():
    if not llm.disponible():
        return jsonify({"ok": False, "error": f"El motor IA ({llm.backend()}) no está disponible."}), 400
    docs = database.get_pending_analysis(limit=config.ANALYZE_BATCH)
    analizados, errores = 0, []
    for doc in docs:
        res = llm.analizar_documento(doc)
        if res.get("ok"):
            database.update_analysis(
                doc["id"], res["resumen_ejecutivo"], res["puntos_clave"],
                res["implicaciones"], res["nivel_confianza"]
            )
            analizados += 1
        else:
            errores.append({"id": doc["id"], "error": res.get("error")})
    return jsonify({
        "ok": True,
        "analizados": analizados,
        "errores": errores,
        "restantes": database.count_pending_analysis(),
    })


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
    doc = database.get_document(doc_id)
    nombre = f"informe_{doc_id}.pdf"
    return send_file(ruta, mimetype="application/pdf", as_attachment=True, download_name=nombre)


@app.route("/api/investigaciones")
def api_investigaciones():
    return jsonify(database.get_investigaciones())


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
    return jsonify({
        "habilitado": getattr(config, "DETECTIVE_ENABLED", False),
        "auto": getattr(config, "DETECTIVE_AUTO", False),
        "interval_min": getattr(config, "DETECTIVE_INTERVAL_MIN", None),
        "motor": llm.nombre_motor(),
        "motor_disponible": llm.disponible(),
        "total": database.count_investigaciones(),
    })


@app.route("/api/investigar", methods=["POST"])
def api_investigar():
    if not getattr(config, "DETECTIVE_ENABLED", False):
        return jsonify({"ok": False, "error": "El detective está desactivado en config.py."}), 400
    tema = (request.args.get("tema") or "").strip() or None
    res = detective.investigar(tema)
    if not res.get("ok"):
        return jsonify(res), 400
    return jsonify(res)


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

    jobs = (config.AUTO_UPDATE_ENABLED
            or getattr(config, "AUTO_INFORMES_ENABLED", False)
            or (getattr(config, "DETECTIVE_ENABLED", False) and getattr(config, "DETECTIVE_AUTO", False)))
    if not jobs:
        return None

    scheduler = BackgroundScheduler(timezone=config.TIMEZONE)

    if config.AUTO_UPDATE_ENABLED:
        scheduler.add_job(
            updater.run_update, "cron",
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
              f"(se pausan si se agota la cuota de Gemini)")
    print("=" * 60 + "\n")
    app.run(host=config.HOST, debug=False, port=config.PORT, use_reloader=False)
