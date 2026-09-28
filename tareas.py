"""
Tareas en segundo plano con un único cerrojo por tarea.

El detective, la actualización de fuentes y el análisis con IA tardan minutos; si se
ejecutaran dentro de la petición HTTP, el navegador se quedaría colgado. Cada tarea:
  - corre en un hilo aparte (lanzar() devuelve al instante),
  - nunca se solapa consigo misma (el botón y el planificador comparten cerrojo),
  - expone un estado que la interfaz consulta: en curso, desde cuándo, fase actual,
    progreso, último error... (estado()).
"""

import logging
import threading
from datetime import datetime

log = logging.getLogger(__name__)


class TareaFondo:
    def __init__(self, nombre, **estado_extra):
        self.nombre = nombre
        self._lock = threading.Lock()
        self._estado = {
            "en_curso": False,
            "desde": None,
            "ultimo_fin": None,
            "ultimo_error": None,
            "fase": None,        # texto corto: "buscando en internet", "FBI Vault"...
            "progreso": None,    # [hechos, total] cuando se conoce
            **estado_extra,
        }

    def estado(self):
        """Copia del estado (para la API/UI)."""
        return dict(self._estado)

    def actualizar(self, **cambios):
        """Lo llama la propia tarea para informar de su fase, progreso o resultado."""
        self._estado.update(cambios)

    def ocupada(self):
        return self._lock.locked()

    def lanzar(self, funcion, *args, ocupado="Ya hay una tarea en curso; espera a que termine.",
               al_iniciar=None, **kwargs):
        """Arranca funcion(*args, **kwargs) en un hilo si no hay otra en curso.
           Devuelve (iniciada, mensaje). NO bloquea."""
        if not self._lock.acquire(blocking=False):
            return False, ocupado
        self._estado.update(en_curso=True, desde=datetime.now().isoformat(),
                            ultimo_error=None, fase=None, progreso=None, **(al_iniciar or {}))
        threading.Thread(target=self._run, args=(funcion, args, kwargs),
                         daemon=True, name=f"tarea-{self.nombre}").start()
        return True, ""

    def _run(self, funcion, args, kwargs):
        try:
            funcion(*args, **kwargs)
        except Exception as e:
            self._estado["ultimo_error"] = str(e)
            log.exception(f"  Tarea '{self.nombre}' falló: {e}")
        finally:
            self._estado.update(en_curso=False, ultimo_fin=datetime.now().isoformat(), fase=None)
            self._lock.release()
