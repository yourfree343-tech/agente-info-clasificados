"""Tests de integración de las rutas Flask con el test client.

No cubren nada que dependa de un motor LLM real ni de red: se centran en
que las rutas respondan con el código y la forma de JSON esperados, y en
la paginación/filtrado servidos por database.py.

Ejecutar con pytest:  python -m pytest -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import database  # noqa: E402
import app as app_module  # noqa: E402


@pytest.fixture()
def client():
    """App Flask con una BD SQLite temporal y aislada, y con 12 documentos
       de prueba repartidos en dos categorías/países para poder probar filtros
       y paginación."""
    original_db = database.DB_PATH
    tmp = tempfile.mkdtemp()
    database.DB_PATH = os.path.join(tmp, "test.db")
    database.init_db()

    for i in range(12):
        database.insert_document({
            "id": f"T-{i:02d}",
            "titulo": f"Documento de prueba número {i}",
            "pais": "España" if i % 2 == 0 else "EE. UU.",
            "categorias": ["Otras"] if i % 3 == 0 else ["Seguridad y defensa"],
            "nivel_confianza": "ALTO",
            "verificado": "Oficial",
            "fecha_documento": f"2026-01-{i+1:02d}",
        })

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c

    database.DB_PATH = original_db


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_documentos_sin_paginar_devuelve_lista(client):
    r = client.get("/api/documentos")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) == 12


def test_documentos_paginado_devuelve_envelope(client):
    r = client.get("/api/documentos?page=1&page_size=5")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 12
    assert len(data["items"]) == 5
    assert data["page"] == 1


def test_documentos_paginado_segunda_pagina(client):
    r = client.get("/api/documentos?page=3&page_size=5")
    data = r.get_json()
    assert len(data["items"]) == 2   # 12 docs: 5 + 5 + 2


def test_documentos_filtro_categoria_exacto(client):
    # 12 docs, i % 3 == 0 -> i in {0,3,6,9} -> 4 documentos en "Otras"
    r = client.get("/api/documentos?categoria=Otras")
    data = r.get_json()
    assert len(data) == 4


def test_documentos_filtro_pais(client):
    r = client.get("/api/documentos?pais=España")
    data = r.get_json()
    assert all(d["pais"] == "España" for d in data)
    assert len(data) == 6


def test_documento_no_encontrado(client):
    r = client.get("/api/ia/analizar/NOPE", data=None)
    r = client.post("/api/ia/analizar/NOPE")
    assert r.status_code == 404


def test_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.get_json()["total"] == 12


def test_investigaciones_vacio(client):
    r = client.get("/api/investigaciones")
    assert r.status_code == 200
    assert r.get_json() == []


def test_investigaciones_paginado_vacio(client):
    r = client.get("/api/investigaciones?page=1")
    data = r.get_json()
    assert data["total"] == 0
    assert data["items"] == []


def test_investigacion_pdf_404(client):
    r = client.get("/api/investigacion/NOPE/pdf")
    assert r.status_code == 404


def test_investigacion_borrar_404(client):
    r = client.delete("/api/investigacion/NOPE")
    assert r.status_code == 404


def test_investigacion_borrar_ok(client):
    database.insert_investigacion({"id": "INV-T1", "tema": "tema de prueba", "titulo": "Caso de prueba"})
    assert client.get("/api/investigaciones").get_json() != []
    r = client.delete("/api/investigacion/INV-T1")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert client.get("/api/investigaciones").get_json() == []


def test_contraargumento_dossier_no_encontrado(client):
    r = client.post("/api/investigacion/NOPE/contraargumento")
    assert r.status_code == 400


def test_conexiones_endpoint(client):
    r = client.get("/api/conexiones")
    assert r.status_code == 200
    data = r.get_json()
    assert {"nodos", "aristas", "ranking", "linea_temporal"} <= set(data.keys())


def test_temas_cola_ciclo_completo(client):
    assert client.get("/api/temas").get_json() == []

    r = client.post("/api/temas", json={"tema": "Bohemian Grove 2026"})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    r = client.post("/api/temas", json={"tema": ""})
    assert r.status_code == 400   # tema vacío rechazado

    cola = client.get("/api/temas").get_json()
    assert len(cola) == 1
    assert cola[0]["tema"] == "Bohemian Grove 2026"

    tema_id = cola[0]["id"]
    r = client.delete(f"/api/temas/{tema_id}")
    assert r.status_code == 200
    assert client.get("/api/temas").get_json() == []

    r = client.delete(f"/api/temas/{tema_id}")
    assert r.status_code == 404   # ya borrado


def test_informe_descargar_404(client):
    r = client.get("/api/informe/NOPE")
    assert r.status_code == 404


def test_exportar_json(client):
    r = client.get("/api/exportar")
    assert r.status_code == 200
    assert r.mimetype == "application/json"


# --- v4: páginas, cabeceras, filtros nuevos y análisis en segundo plano ---

def test_paginas_renderizan_con_la_plantilla_base(client):
    for ruta, texto in (("/", "Archivos Clasificados"), ("/investigaciones", "Dossiers del Detective"),
                        ("/conexiones", "Conexiones entre casos")):
        r = client.get(ruta)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert texto in html
        assert "/static/js/common.js" in html          # utilidades compartidas
        assert 'aria-current="page"' in html           # pestaña activa marcada


def test_cabeceras_de_seguridad(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_api_filtros(client):
    data = client.get("/api/filtros").get_json()
    assert {"valor": "España", "n": 6} in data["paises"]
    assert {c["valor"] for c in data["categorias"]} == {"Otras", "Seguridad y defensa"}


def test_documentos_paginado_incluye_tiene_informe_y_filtra_por_id(client):
    data = client.get("/api/documentos?page=1&id=T-03").get_json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "T-03"
    assert data["items"][0]["tiene_informe"] is False
    assert "analisis_detallado" not in data["items"][0]


def test_documentos_orden_ascendente(client):
    data = client.get("/api/documentos?page=1&page_size=3&orden=fecha_asc").get_json()
    assert [d["id"] for d in data["items"]] == ["T-00", "T-01", "T-02"]


def test_analizar_pendientes_sin_motor_da_400(client, monkeypatch):
    import llm
    monkeypatch.setattr(llm, "disponible", lambda: False)
    r = client.post("/api/ia/analizar_pendientes")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_investigaciones_incluyen_calidad_de_fuentes(client):
    database.insert_investigacion({"id": "INV-F", "tema": "t", "titulo": "Caso",
                                   "fuentes": ["https://www.archives.gov/x", "https://blog.example/y"]})
    data = client.get("/api/investigaciones?page=1").get_json()
    fd = data["items"][0]["fuentes_detalle"]
    assert fd["por_tipo"] == {"oficial": 1, "web": 1}


def test_estado_detective_expone_fase(client):
    data = client.get("/api/detective/estado").get_json()
    assert {"fase", "desde", "motor_local", "ultimo_id"} <= set(data)
