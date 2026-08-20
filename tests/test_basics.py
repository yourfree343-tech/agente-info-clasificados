"""Tests básicos del Agente Info Clasificados.

Cubren los puntos más frágiles del proyecto:
  - gemini._parse_json: extraer JSON de respuestas sucias de modelos locales.
  - detective._busquedas_desde_tema: elección de búsquedas sin LLM.
  - database: normalización de títulos, deduplicado y filtros.

Ejecutar con pytest:        python -m pytest -q
o directamente sin pytest:   python tests/test_basics.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gemini      # noqa: E402
import detective   # noqa: E402
import database    # noqa: E402
import analisis    # noqa: E402


# --- gemini._parse_json: el punto más frágil con modelos locales (Qwen) ---

def test_parse_json_plano():
    assert gemini._parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_con_vallas_de_codigo():
    assert gemini._parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_con_razonamiento_think():
    assert gemini._parse_json('<think>pienso en voz alta...</think>\n{"a": 1}') == {"a": 1}


def test_parse_json_con_texto_alrededor():
    assert gemini._parse_json('Aquí tienes: {"a": 1, "b": [2, 3]} fin') == {"a": 1, "b": [2, 3]}


# --- detective: elección de búsquedas sin LLM ---

def test_busquedas_desde_tema_sin_duplicados():
    qs = detective._busquedas_desde_tema("Roswell 1947 y el encubrimiento OVNI")
    assert qs[0] == "Roswell 1947 y el encubrimiento OVNI"   # el tema completo va primero
    assert qs[1].startswith("Roswell 1947")                  # foco corto (antes del 'y')
    assert len(qs) == len({q.lower() for q in qs})           # sin duplicados
    assert all(q.strip() for q in qs)


# --- database: normalización y deduplicado ---

def test_normalize_title():
    assert database.normalize_title("  Hola   MUNDO ") == "hola mundo"


def _con_db_temporal(cuerpo):
    """Ejecuta cuerpo() con una BD SQLite temporal y aislada."""
    original = database.DB_PATH
    tmp = tempfile.mkdtemp()
    database.DB_PATH = os.path.join(tmp, "test.db")
    try:
        database.init_db()
        cuerpo()
    finally:
        database.DB_PATH = original


def test_dedup_documento():
    def cuerpo():
        doc = {"id": "X-1", "titulo": "Documento de prueba bien largo"}
        assert database.insert_document(doc) is True
        assert database.insert_document(doc) is False  # mismo id -> no se duplica
        # mismo título normalizado, distinto id -> tampoco se duplica
        assert database.insert_document(
            {"id": "X-2", "titulo": "documento DE   prueba bien LARGO"}) is False
    _con_db_temporal(cuerpo)


def test_get_documents_filtra_por_pais():
    def cuerpo():
        database.insert_document({"id": "A", "titulo": "Documento uno de España", "pais": "España"})
        database.insert_document({"id": "B", "titulo": "Documento dos de EEUU", "pais": "EE. UU."})
        res = database.get_documents({"pais": "España"})
        assert len(res) == 1 and res[0]["id"] == "A"
    _con_db_temporal(cuerpo)


# --- cola de temas: el detective la consume antes que el banco semilla ---

def test_cola_de_temas_fifo():
    def cuerpo():
        assert database.pop_tema_cola() is None   # vacía al empezar
        database.encolar_tema("Primero")
        database.encolar_tema("Segundo")
        assert [t["tema"] for t in database.get_cola_temas()] == ["Primero", "Segundo"]
        assert database.pop_tema_cola() == "Primero"   # FIFO
        assert [t["tema"] for t in database.get_cola_temas()] == ["Segundo"]
    _con_db_temporal(cuerpo)


def test_elegir_tema_local_prioriza_la_cola():
    def cuerpo():
        database.encolar_tema("Tema encolado por el usuario")
        tema, busquedas = detective._elegir_tema_local()
        assert tema == "Tema encolado por el usuario"
        assert busquedas  # se derivan búsquedas igual que con un tema del banco semilla
    _con_db_temporal(cuerpo)


def test_eliminar_tema_cola():
    def cuerpo():
        database.encolar_tema("Un tema")
        tema_id = database.get_cola_temas()[0]["id"]
        assert database.eliminar_tema_cola(tema_id) is True
        assert database.eliminar_tema_cola(tema_id) is False   # ya no existe
    _con_db_temporal(cuerpo)


# --- analisis.py: extracción de entidades y grafo de conexiones ---

def test_extraer_terminos_reconoce_entidades_conocidas():
    terminos = analisis.extraer_terminos("La CIA y el MK-Ultra siguen investigándose en Área 51.")
    assert "CIA" in terminos
    assert "MK-Ultra" in terminos
    assert "Área 51" in terminos


def test_extraer_terminos_descarta_inicio_de_frase_generico():
    # "Existen" y "Documentos" son inicios de viñeta genéricos, no entidades.
    terminos = analisis.extraer_terminos("Existen documentos que lo confirman. Documentos oficiales.")
    assert "Existen" not in terminos
    assert "Documentos" not in terminos


def test_calcular_conexiones_conecta_dossiers_con_entidad_compartida():
    def cuerpo():
        database.insert_investigacion({
            "id": "INV-A", "tema": "t1", "titulo": "El caso de la CIA y Roswell",
            "hipotesis": ["La CIA ocultó pruebas en Roswell"],
        })
        database.insert_investigacion({
            "id": "INV-B", "tema": "t2", "titulo": "Roswell: nuevas pistas",
            "hipotesis": ["Roswell sigue sin explicación oficial"],
        })
        database.insert_investigacion({
            "id": "INV-C", "tema": "t3", "titulo": "Un caso sin relación",
            "hipotesis": ["Nada que ver con los otros dos"],
        })
        r = analisis.calcular_conexiones()
        assert len(r["nodos"]) == 3
        pares = {frozenset((a["a"], a["b"])) for a in r["aristas"]}
        assert frozenset(("INV-A", "INV-B")) in pares
        assert frozenset(("INV-A", "INV-C")) not in pares
    _con_db_temporal(cuerpo)


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            fallos += 1
            print(f"ERROR {fn.__name__}: {e!r}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} OK")
    sys.exit(1 if fallos else 0)
