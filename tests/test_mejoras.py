"""Tests de las mejoras de la v4: búsqueda sin tildes, filtros nuevos, fechas reales y
rotación de fuentes, resúmenes a coste cero desde los informes, clasificación de
fuentes, reintentos de OpenRouter, detective con base factual y tareas de fondo.

Nada de esto toca la red ni un motor LLM real (todo va con monkeypatch) ni la BD real
(cada test usa una SQLite temporal).

Ejecutar con pytest:  python -m pytest -q
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import analisis     # noqa: E402
import analizador   # noqa: E402
import database     # noqa: E402
import detective    # noqa: E402
import gemini       # noqa: E402
import llm          # noqa: E402
import tareas       # noqa: E402
import updater      # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """BD SQLite temporal y aislada (monkeypatch restaura DB_PATH al acabar)."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    return database


def _doc(i, **extra):
    base = {"id": f"D-{i}", "titulo": f"Documento de prueba número {i}", "pais": "EE. UU.",
            "categorias": ["Otras"], "organismo": ["FBI Vault"], "nivel_confianza": "ALTO",
            "fecha_documento": "2026-01-01"}
    base.update(extra)
    return base


# --------------------------------------------------------------------------- búsqueda

def test_busqueda_ignora_tildes_y_mayusculas(db):
    db.insert_document(_doc(1, titulo="Informe sobre el Área 51 y Roswell"))
    db.insert_document(_doc(2, titulo="Otro expediente sin relación"))
    assert [d["id"] for d in db.get_documents({"busqueda": "area 51"})] == ["D-1"]
    assert [d["id"] for d in db.get_documents({"busqueda": "ÁREA"})] == ["D-1"]


def test_busqueda_multipalabra_exige_todas(db):
    db.insert_document(_doc(1, titulo="La CIA y los OVNIs", resumen_ejecutivo="Programa Stargate"))
    db.insert_document(_doc(2, titulo="La CIA y Cuba"))
    assert [d["id"] for d in db.get_documents({"busqueda": "cia stargate"})] == ["D-1"]
    assert len(db.get_documents({"busqueda": "cia"})) == 2


def test_busqueda_escapa_comodines(db):
    db.insert_document(_doc(1, titulo="Informe con 100% de páginas"))
    db.insert_document(_doc(2, titulo="Informe con 100 páginas"))
    assert [d["id"] for d in db.get_documents({"busqueda": "100%"})] == ["D-1"]


# --------------------------------------------------------------------------- filtros

def test_filtro_por_fuente_y_estado_ia(db):
    db.insert_document(_doc(1, organismo=["CIA", "The Black Vault (FOIA)"]))
    db.insert_document(_doc(2, organismo=["FBI Vault"], analizado_ia="ia"))
    db.insert_document(_doc(3, organismo=["FBI Vault"], analizado_ia="sin_texto"))
    assert [d["id"] for d in db.get_documents({"fuente": "The Black Vault (FOIA)"})] == ["D-1"]
    assert [d["id"] for d in db.get_documents({"ia": "pendiente"})] == ["D-1"]
    assert [d["id"] for d in db.get_documents({"ia": "analizado"})] == ["D-2"]
    assert [d["id"] for d in db.get_documents({"ia": "sin_texto"})] == ["D-3"]


def test_filtro_fecha_acepta_fechas_solo_anio(db):
    db.insert_document(_doc(1, fecha_documento="1947"))
    db.insert_document(_doc(2, fecha_documento="1962-03-13"))
    db.insert_document(_doc(3, fecha_documento=""))
    ids = [d["id"] for d in db.get_documents({"fecha_desde": "1940-01-01", "fecha_hasta": "1949-12-31"})]
    assert ids == ["D-1"]


def test_orden_deja_sin_fecha_al_final(db):
    db.insert_document(_doc(1, fecha_documento=""))
    db.insert_document(_doc(2, fecha_documento="1962-03-13"))
    db.insert_document(_doc(3, fecha_documento="2025-03-18"))
    assert [d["id"] for d in db.get_documents(orden="fecha_desc")] == ["D-3", "D-2", "D-1"]
    assert [d["id"] for d in db.get_documents(orden="fecha_asc")] == ["D-2", "D-3", "D-1"]


def test_filtros_disponibles_con_recuentos(db):
    db.insert_document(_doc(1, categorias=["Otras", "Derechos humanos"]))
    db.insert_document(_doc(2, pais="España"))
    f = db.get_filtros_documentos()
    assert {"valor": "Otras", "n": 2} in f["categorias"]
    assert {"valor": "España", "n": 1} in f["paises"]
    assert f["fuentes"][0] == {"valor": "FBI Vault", "n": 2}


def test_stats_por_decada_y_fuente(db):
    db.insert_document(_doc(1, fecha_documento="1947"))
    db.insert_document(_doc(2, fecha_documento="1949-06-01"))
    db.insert_document(_doc(3, fecha_documento=""))
    s = db.get_stats()
    assert s["por_decada"] == [{"decada": "1940", "n": 2}]
    assert s["num_fuentes"] == 1


def test_fila_con_json_corrupto_no_rompe_las_consultas(db):
    db.insert_document(_doc(1))
    conn = db.get_connection()
    conn.execute("UPDATE documentos SET categorias = '' WHERE id = 'D-1'")
    conn.commit()
    conn.close()
    assert db.get_stats()["total"] == 1
    assert db.get_documents({"categoria": "Otras"}) == []


# --------------------------------------------------------------------------- fechas y rotación

def test_fecha_provisional_se_corrige_pero_la_real_no_se_pisa(db):
    db.insert_document(_doc(1, fecha_documento="2026-08-20", fecha_ingreso="2026-08-20T06:00:00"))
    db.insert_document(_doc(2, fecha_documento="1962-03-13", fecha_ingreso="2026-08-20T06:00:00"))
    assert db.actualizar_fecha_provisional("D-1", "1977-08-03") is True
    assert db.actualizar_fecha_provisional("D-2", "1977-08-03") is False
    assert db.get_document("D-1")["fecha_documento"] == "1977-08-03"
    assert db.get_document("D-2")["fecha_documento"] == "1962-03-13"


def test_ids_existentes(db):
    db.insert_document(_doc(1))
    assert db.ids_existentes(["D-1", "D-9", None]) == {"D-1"}


def test_fecha_desde_url_de_nara():
    assert updater._fecha_desde_url("https://x/files/research/rfk/releases/2025/0612/a.pdf") == "2025-06-12"
    assert updater._fecha_desde_url("https://x/files/research/jfk/releases/2023/104-1.pdf") == "2023"
    assert updater._fecha_desde_url("https://x/otra/cosa.pdf") == ""


def test_titulo_desde_archivo():
    assert updater._titulo_desde_archivo("00017505_jun_68_we_learned.pdf") == "Jun 68 we learned"
    assert updater._titulo_desde_archivo("104-10130-10026.PDF") == "104-10130-10026"


def test_black_vault_agencia_y_categorias():
    assert updater._bv_agencia("https://documents3.theblackvault.com/documents/cia/F-1.pdf") == "CIA"
    assert updater._bv_agencia("https://www.aaro.mil/Portals/x.pdf") == "AARO"
    assert updater._bv_categorias("UFO Phenomena Mysteries")[0] == "Ciencia y tecnología militar"
    assert updater._bv_categorias("algo sin pistas") == ["Inteligencia y espionaje"]


def test_ingerir_rota_y_no_repite(db, monkeypatch):
    monkeypatch.setattr(updater, "_es_descargable", lambda url: True)
    docs = [updater._doc_pdf("Fuente X", f"Fuente X — doc {i}", f"https://x/{i}.pdf",
                             ["Otras"], "EE. UU.", "Alta", "PDF", fecha="2025-03-18") for i in range(7)]
    assert updater._ingerir("Fuente X", docs, max_nuevos=3) == 3
    assert updater._ingerir("Fuente X", docs, max_nuevos=3) == 3   # la tanda siguiente, no las mismas
    assert updater._ingerir("Fuente X", docs, max_nuevos=3) == 1
    assert db.count_documents() == 7


# --------------------------------------------------------------------------- analizador

_DETALLADO_BUENO = {
    "contexto": "Memorando del Estado Mayor Conjunto de 1962 que propone operaciones de falsa bandera.",
    "hechos_clave": ["Firmado por Lemnitzer", "Fecha: 13 de marzo de 1962"],
    "revelaciones": ["Propuesta de atentados simulados"],
    "implicaciones": ["Muestra hasta dónde", "llegaba la planificación"],   # lista: pasa a veces
    "nivel_confianza": "ALTO",
}


def test_resumen_desde_detallado():
    r = analizador.resumen_desde_detallado(_DETALLADO_BUENO)
    assert r["resumen_ejecutivo"].startswith("Memorando")
    assert r["puntos_clave"][0] == "Propuesta de atentados simulados"
    assert r["implicaciones"] == "Muestra hasta dónde llegaba la planificación"
    assert r["nivel_confianza"] == "ALTO"


def test_resumen_desde_detallado_vacio_o_de_relleno():
    assert analizador.resumen_desde_detallado({"hechos_clave": [], "revelaciones": []}) is None
    relleno = dict(_DETALLADO_BUENO, contexto="Es un PDF escaneado sin texto extraíble, por lo que...")
    assert analizador.resumen_desde_detallado(relleno) is None


def test_rellenar_desde_detallados(db):
    db.insert_document(_doc(1))
    db.insert_document(_doc(2, url_fuente="https://vault.fbi.gov/x"))
    db.insert_document(_doc(3, url_fuente="https://archive.org/download/Item/a.pdf"))
    db.save_analisis_detallado("D-1", _DETALLADO_BUENO)
    db.save_analisis_detallado("D-2", {"hechos_clave": [], "revelaciones": []})
    db.save_analisis_detallado("D-3", {"hechos_clave": [], "revelaciones": []})
    hechos = analizador.rellenar_desde_detallados()
    assert hechos == {"ia": 1, "sin_texto": 1}
    assert db.get_document("D-1")["analizado_ia"] == "ia"
    assert db.get_document("D-2")["analizado_ia"] == "sin_texto"
    assert db.get_document("D-2")["nivel_confianza"] == "ALTO"   # no rebaja la de la fuente
    assert db.get_document("D-3")["analizado_ia"] == ""          # archive.org: se reintenta con OCR


def test_reclasificar_rellenos(db):
    db.insert_document(_doc(1, analizado_ia="gemini",
                            resumen_ejecutivo="El PDF no contiene texto extraíble, así que..."))
    db.insert_document(_doc(2, analizado_ia="gemini", resumen_ejecutivo="Un resumen de verdad.",
                            implicaciones="Implicaciones reales."))
    assert analizador.reclasificar_rellenos() == 1
    assert db.get_document("D-1")["analizado_ia"] == "sin_texto"
    assert db.get_document("D-2")["analizado_ia"] == "gemini"


def test_analizar_documento_sin_texto_no_gasta_llamada(monkeypatch):
    monkeypatch.setattr(llm, "backend", lambda: "openrouter")
    monkeypatch.setattr(gemini, "obtener_contenido", lambda doc: ("none", None, doc["url_fuente"]))

    def no_llamar(*a, **k):
        raise AssertionError("no debería llamar al LLM sin contenido que leer")

    monkeypatch.setattr(llm, "generar_json", no_llamar)
    r = llm.analizar_documento({"id": "X", "url_fuente": "https://x/y.pdf", "nivel_confianza": "ALTO",
                                "resumen_ejecutivo": "[Pendiente de análisis con IA] ..."})
    assert r["ok"] and r["sin_texto"] and r["nivel_confianza"] == "ALTO"


def test_pdf_escaneado_usa_ocr_de_archive_org(monkeypatch):
    monkeypatch.setattr(gemini, "extraer_texto_pdf", lambda b: "")
    monkeypatch.setattr(gemini, "texto_ocr_archive_org", lambda url: "texto OCR " * 30)
    texto, tipo, url, imgs = llm._contenido_para_local(
        {"url_fuente": "https://archive.org/download/I/a.pdf"}, "pdf", b"%PDF", "https://archive.org/download/I/a.pdf")
    assert tipo == "pdf" and texto.startswith("texto OCR") and imgs == []


# --------------------------------------------------------------------------- OpenRouter

class _Resp:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._data, self.headers, self.text = status, data, headers or {}, str(data)

    def json(self):
        return self._data


def test_openrouter_reintenta_ante_429(monkeypatch):
    import config
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "clave-de-prueba", raising=False)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    respuestas = [_Resp(429, {}, {"Retry-After": "1"}),
                  _Resp(200, {"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]})]
    enviados = []

    def post(url, headers=None, json=None, timeout=None):
        enviados.append(json)
        return respuestas.pop(0)

    monkeypatch.setattr(llm.requests, "post", post)
    assert llm._openrouter_json("prompt", 0.3) == {"a": 1}
    assert len(enviados) == 2
    assert enviados[0]["response_format"] == {"type": "json_object"}


def test_openrouter_sin_saldo_da_error_claro(monkeypatch):
    import config
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "clave-de-prueba", raising=False)
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Resp(402, {"error": "no credits"}))
    with pytest.raises(RuntimeError, match="saldo"):
        llm._openrouter_json("prompt", 0.3)


# --------------------------------------------------------------------------- análisis de dossiers

def test_clasificar_fuente():
    tipo = lambda u: analisis.clasificar_fuente(u)["tipo"]  # noqa: E731
    assert tipo("https://www.archives.gov/research/jfk") == "oficial"
    assert tipo("https://www.lamoncloa.gob.es/x") == "oficial"
    assert tipo("https://www.gov.uk/x") == "oficial"
    assert tipo("https://es.wikipedia.org/wiki/X") == "referencia"
    assert tipo("https://documents3.theblackvault.com/x.pdf") == "archivo"
    assert tipo("https://www.nytimes.com/x") == "prensa"
    assert tipo("https://www.youtube.com/watch?v=1") == "redes"
    assert tipo("https://blog-conspiranoico.net/x") == "web"
    assert analisis.clasificar_fuente("https://www.nytimes.com/x")["dominio"] == "nytimes.com"


def test_extraer_terminos_unifica_variantes():
    t = analisis.extraer_terminos("Los OVNIs y el programa MKUltra. The World Ahead 2026 lo anticipaba.")
    assert "OVNI" in t and "OVNIs" not in t
    assert "MK-Ultra" in t
    assert "World Ahead" in t and "World Ahead 2026" not in t
    assert "Otras" not in analisis.extraer_terminos("Otras cosas")


def test_linea_temporal_cuenta_dossiers_y_excluye_futuro(db):
    db.insert_investigacion({"id": "INV-1", "tema": "t", "titulo": "Roswell 1947",
                             "hechos_verificados": ["En 1947, y otra vez 1947, y 1947"]})
    db.insert_investigacion({"id": "INV-2", "tema": "t", "titulo": "Predicción",
                             "hipotesis": ["En 2049 todo cambiará; en 1947 empezó"]})
    lt = {x["anio"]: x["n"] for x in analisis.calcular_conexiones()["linea_temporal"]}
    assert lt["1947"] == 2          # dos dossiers, no cinco menciones
    assert "2049" not in lt         # los años futuros son predicciones, no hechos


# --------------------------------------------------------------------------- detective

def test_detective_filtra_fuentes_inventadas(db, monkeypatch):
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(detective, "buscar_wikipedia", lambda tema, n=2: [
        {"titulo": "Wikipedia: Proyecto MKUltra", "url": "https://es.wikipedia.org/wiki/MKUltra", "snippet": "x" * 100}])
    monkeypatch.setattr(detective, "buscar_noticias", lambda q, n=4: [])
    monkeypatch.setattr(detective, "buscar_web", lambda q, n=5: [
        {"titulo": "Web", "url": "https://ejemplo.com/mk", "snippet": "algo"}])
    monkeypatch.setattr(detective, "buscar_imagenes", lambda q, n=4: [])
    db.insert_document(_doc(1, titulo="Proyecto MKUltra (CIA) — audiencia del Senado"))
    visto = {}

    def generar(prompt, temperature=0.7, imagenes=None):
        visto["prompt"] = prompt
        return {"ok": True, "data": {
            "titulo": "El legado de MKUltra", "categoria": "Control mental", "gancho": "g",
            "hechos_verificados": "un solo hecho en texto",   # a veces no devuelve lista
            "hipotesis": [], "especulacion": [], "conexiones": [], "veredicto": "v",
            "nivel_certeza": "medio", "fuentes": ["https://inventada.example/fake", "https://ejemplo.com/mk"]}}

    monkeypatch.setattr(llm, "generar_json", generar)
    res = detective.investigar("MKUltra y el control mental de la CIA")
    assert res["ok"]
    inv = res["investigacion"]
    assert "https://inventada.example/fake" not in inv["fuentes"]
    assert inv["fuentes"][0] == "https://ejemplo.com/mk"                # citada y real, primero
    assert "https://es.wikipedia.org/wiki/MKUltra" in inv["fuentes"]
    assert inv["hechos_verificados"] == ["un solo hecho en texto"]
    assert inv["documentos_relacionados"][0]["id"] == "D-1"
    assert "DOCUMENTOS OFICIALES DEL ARCHIVO" in visto["prompt"]         # el modelo los ve


# --------------------------------------------------------------------------- tareas de fondo

def test_tarea_fondo_no_se_solapa_y_registra_errores():
    t = tareas.TareaFondo("prueba", extra=None)
    import threading
    liberar = threading.Event()

    def lenta():
        t.actualizar(fase="trabajando")
        liberar.wait(2)

    assert t.lanzar(lenta)[0] is True
    assert t.lanzar(lenta) == (False, "Ya hay una tarea en curso; espera a que termine.")
    assert t.estado()["en_curso"] is True
    liberar.set()
    for _ in range(50):
        if not t.estado()["en_curso"]:
            break
        time.sleep(0.02)
    assert t.estado()["en_curso"] is False

    def rota():
        raise ValueError("fallo de prueba")

    assert t.lanzar(rota)[0] is True
    for _ in range(50):
        if not t.estado()["en_curso"]:
            break
        time.sleep(0.02)
    assert t.estado()["ultimo_error"] == "fallo de prueba"
