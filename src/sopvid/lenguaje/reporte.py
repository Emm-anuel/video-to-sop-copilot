"""Porcentaje de cumplimiento y semáforo del reporte de validación (RF-19, SOP V1.0 §5.6).

`porcentaje` puntúa cada paso del SOP según su estado tras `emparejar`: Cumple vale 1; Parcial,
0.5; un Cumple o un Parcial con la marca de fuera de orden, 0.5 una sola vez (la marca no se
suma a la penalización del Parcial). Falta y zona_gris ("sin revisar") valen 0. Los Sobra no
restan, tampoco los marcados como intro o cierre del operador (ADR-016). `semaforo` traduce el
porcentaje a verde, amarillo o rojo con los cortes de la configuración (RNF-14).
"""

from sopvid.contrato import ResultadoEmparejamiento, Semaforo
from sopvid.plataforma.config import Settings, get_settings


def porcentaje(resultado: ResultadoEmparejamiento) -> float:
    """(Cumple + 0.5 × (Parcial + Fuera de orden)) / pasos del SOP × 100, sin redondear.

    Los pasos del SOP se cuentan desde la clasificación: un resultado por paso, con `indice_sop`
    de 0 a n-1 sin repetir. Si no es así (incluido un SOP sin pasos), `ValueError`. Se calcula
    `100 * puntos / n` en ese orden: los puntos son múltiplos de 0.5, así que un 90 o un 70
    exactos salen exactos en flotante y el semáforo no cambia de color por redondeo.
    """
    pasos_sop = [p for p in resultado.clasificacion.pasos if p.indice_sop is not None]
    n = len(pasos_sop)
    if n == 0:
        raise ValueError("la clasificación no tiene pasos del SOP")
    indices = sorted(p.indice_sop for p in pasos_sop if p.indice_sop is not None)
    if indices != list(range(n)):
        raise ValueError(
            f"los indice_sop de la clasificación deben ser 0..{n - 1} sin repetir "
            f"(llegaron {indices})"
        )
    puntos = 0.0
    for p in pasos_sop:
        if p.estado == "Cumple":
            puntos += 0.5 if p.fuera_de_orden else 1.0
        elif p.estado == "Parcial":
            puntos += 0.5
    return 100 * puntos / n


def semaforo(pct: float, settings: Settings | None = None) -> Semaforo:
    """Verde si `pct` ≥ SEMAFORO_VERDE; amarillo si ≥ SEMAFORO_AMARILLO; rojo si no.

    `pct` es el porcentaje sin redondear que devuelve `porcentaje`, nunca el valor guardado en
    `reportes.cumplimiento` (Numeric(5,2)): con 89.996 el semáforo es amarillo aunque la columna
    guarde 90.00. Sin `settings`, usa `get_settings()`.
    """
    settings = settings or get_settings()
    if pct >= settings.semaforo_verde:
        return "verde"
    if pct >= settings.semaforo_amarillo:
        return "amarillo"
    return "rojo"
