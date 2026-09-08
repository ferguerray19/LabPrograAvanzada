"""Tests del contrato de datos. Se ejecutan sin pytest:

    python -m bench.test_formato

El mas importante es `test_equivalencia_iso`: la optimizacion que elimina
`strftime` del bucle caliente no puede cambiar ni un byte de la salida, o
habriamos ganado velocidad rompiendo el contrato de datos que la Fase 2
consume.
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import esquema, simulador  # noqa: E402
from src.esquema import (  # noqa: E402
    FormateadorISO, formatear_referencia, parsear_t0, repartir, ticks_necesarios,
)


def _ms(*a, **k) -> int:
    return int(datetime(*a, tzinfo=timezone.utc, **k).timestamp() * 1000)


def test_equivalencia_iso() -> None:
    f = FormateadorISO()
    casos = [
        0,                                   # epoch
        _ms(2026, 8, 24),                    # inicio por defecto de la simulacion
        _ms(2026, 8, 24) - 1,                # ultimo ms del dia anterior
        _ms(2026, 8, 24) + 999,              # ms = 999
        _ms(2028, 2, 29, hour=23, minute=59, second=59),  # ano bisiesto
        _ms(2026, 12, 31, hour=23, minute=59, second=59),  # fin de ano
        _ms(2027, 1, 1),                     # cruce de ano
    ]
    # Muestra pseudoaleatoria con semilla FIJA: un test que falla solo a veces
    # no es un test.
    rng = random.Random(0)
    casos += [rng.randrange(1_700_000_000_000, 1_900_000_000_000) for _ in range(200_000)]
    for t in casos:
        assert f.formatear(t) == formatear_referencia(t), (
            t, f.formatear(t), formatear_referencia(t)
        )
    # y el caso que ejercita el cache: dos dias consecutivos alternados
    a, b = _ms(2026, 8, 24), _ms(2026, 8, 25)
    for t in (a, b, a, b, a):
        assert f.formatear(t) == formatear_referencia(t)
    print("OK  test_equivalencia_iso        (200.007 casos)")


def test_reparto_exacto() -> None:
    for total in (10_000_000, 9_999_999, 1, 7, 1_000_003):
        for n in range(1, 33):
            partes = repartir(total, n)
            assert sum(partes) == total, (total, n)
            assert len(partes) == n
            assert max(partes) - min(partes) <= 1, (total, n, partes)
    print("OK  test_reparto_exacto          (5 totales x 32 workers)")


def test_ticks_como_piso() -> None:
    puntos = simulador.contar_puntos(simulador.construir_inventario(42))
    t = ticks_necesarios(10_000_000, puntos)
    assert t * puntos >= 10_000_000
    assert (t - 1) * puntos < 10_000_000, "no es el techo minimo"
    print(f"OK  test_ticks_como_piso         ({puntos} puntos, {t} ticks, "
          f"{t * puntos:,} eventos)")


def test_t0_rechaza_ingenuo() -> None:
    for malo in ("2026-08-24T00:00:00", "ayer", "1969-01-01T00:00:00Z"):
        try:
            parsear_t0(malo)
        except ValueError:
            continue
        raise AssertionError(f"deberia haber fallado con {malo!r}")
    assert parsear_t0("2026-08-24T00:00:00Z") == _ms(2026, 8, 24)
    print("OK  test_t0_rechaza_ingenuo")


def test_reparto_workers_equilibrado() -> None:
    activos = simulador.construir_inventario(42)
    for n in (1, 2, 3, 4, 8, 16):
        cubos = simulador.asignar_workers(activos, n)
        asignados = sorted(i for c in cubos for i in c)
        assert asignados == list(range(len(activos))), "activo perdido o duplicado"
        cargas = [sum(activos[i].n_puntos for i in c) for c in cubos]
        assert max(cargas) - min(cargas) <= 2, (n, cargas)
    print("OK  test_reparto_workers_equilibrado")


def test_esquema_de_los_eventos() -> None:
    """Genera una muestra real y la valida campo a campo."""
    activos = simulador.construir_inventario(7)
    plan = esquema.PlanWorker(
        worker_id=3, indices_activos=tuple(range(len(activos))),
        t0_ms=parsear_t0("2026-08-24T00:00:00Z"), dt_ms=15_000,
        n_ticks=200, seed=7, batch_size=1000, output_dir=".", esquema="full",
    )
    sumidero = esquema.SumideroMemoria()
    n = esquema.bucle_worker(plan, activos, sumidero)
    lineas = sumidero.lineas
    assert n == len(lineas) == 200 * simulador.contar_puntos(activos)

    import json
    for linea in lineas[:5000]:
        assert linea.endswith("\n") and linea.count("\n") == 1
        esquema.validar_evento(json.loads(linea))
    print(f"OK  test_esquema_de_los_eventos  ({n:,} eventos generados)")


def test_fisica_reefer_creible() -> None:
    """La guia es explicita: un reefer con setpoint -18 no salta a +4 entre
    dos lecturas separadas por 30 s. Este test es la defensa contra el
    falso positivo perfecto."""
    rng = random.Random(1)
    r = simulador.Reefer(1, rng)
    prev = r.temp
    maximo_salto = 0.0
    extremos = []
    for k in range(60_000):
        temp = r.tick(15.0, k * 15_000)[0][3]
        maximo_salto = max(maximo_salto, abs(temp - prev))
        extremos.append(temp)
        prev = temp
    assert maximo_salto < 1.0, f"salto de {maximo_salto:.2f} C entre ticks"
    assert -20.0 < min(extremos) and max(extremos) < 0.0, (min(extremos), max(extremos))
    print(f"OK  test_fisica_reefer_creible   (salto max {maximo_salto:.3f} C/tick, "
          f"rango [{min(extremos):.2f}, {max(extremos):.2f}] C)")


def test_anomalias_ocurren() -> None:
    """Una rama muerta no sirve de nada: si `puerta_abierta` nunca se activa,
    la Fase 2 no tiene nada que detectar."""
    rng = random.Random(3)
    r = simulador.Reefer(1, rng)
    alarmas = sum(1 for k in range(200_000) if r.tick(15.0, k * 15_000)[0][4] != "OK")
    assert alarmas > 0, "el reefer nunca se sale de rango: anomalias inactivas"

    rng2 = random.Random(5)
    faja = simulador.Faja(1, rng2)
    vibs = [faja.tick(15.0, k * 15_000)[0][3] for k in range(200_000)]
    assert max(vibs) > 3.0, "la faja nunca vibra por encima del ruido"
    print(f"OK  test_anomalias_ocurren       ({alarmas} ticks no-OK en reefer, "
          f"vib max {max(vibs):.2f} mm/s)")


def test_acoplamiento_faja() -> None:
    """Vibracion y corriente deben correlacionar porque comparten causa
    (la carga), no ser tres ruidos independientes con nombres distintos."""
    import statistics
    rng = random.Random(11)
    faja = simulador.Faja(1, rng)
    vib, amp = [], []
    for k in range(20_000):
        lect = faja.tick(15.0, k * 15_000)
        vib.append(lect[0][3])
        amp.append(lect[1][3])
    r = statistics.correlation(vib, amp)
    assert r > 0.8, f"correlacion vibracion/corriente demasiado baja: {r:.3f}"
    print(f"OK  test_acoplamiento_faja       (r = {r:.3f})")


def test_equivalencia_arquitecturas() -> None:
    """Las dos arquitecturas deben producir el mismo MULTICONJUNTO de eventos.

    No el mismo archivo: en la Opcion A el orden en que los lotes de distintos
    workers llegan al escritor lo decide el planificador del sistema
    operativo, asi que el orden de lineas varia entre corridas. Lo que no
    puede variar es el contenido. Se comparan las lineas ordenadas.

    Esto verifica de paso que ambas rutas usan el mismo `bucle_worker` y el
    mismo reparto de activos: si `asignar_workers` diera distinto en cada
    arquitectura, los `worker_id` no calzarian y el test fallaria.
    """
    import shutil
    import tempfile
    from src import arquitectura_a, arquitectura_b

    n_puntos = simulador.contar_puntos(simulador.construir_inventario(42))
    n_ticks = 400  # escala chica: el test corre en segundos
    base = dict(
        workers=3, total_events=n_puntos * n_ticks, arch="shard",
        batch_size=500, seed=42, t0_ms=parsear_t0("2026-08-24T00:00:00Z"),
        dt_ms=15_000, n_ticks=n_ticks, n_puntos=n_puntos, esquema="full",
        start_method="fork", queue_maxsize=8,
    )
    tmp = Path(tempfile.mkdtemp(prefix="tpc_equiv_"))
    try:
        salidas = {}
        for arch, modulo in (("shard", arquitectura_b), ("queue", arquitectura_a)):
            destino = tmp / arch
            destino.mkdir()
            plan = esquema.PlanCorrida(**{**base, "arch": arch,
                                          "output_dir": str(destino)})
            resumen = modulo.ejecutar(plan)
            assert resumen.eventos == plan.eventos_esperados, (arch, resumen.eventos)
            lineas = []
            for f in sorted(destino.glob("*.jsonl")):
                lineas.extend(f.read_text(encoding="utf-8").splitlines())
            salidas[arch] = lineas

        assert len(salidas["shard"]) == len(salidas["queue"]), (
            f'shard emitio {len(salidas["shard"])} lineas y queue '
            f'{len(salidas["queue"])}'
        )
        a, b = sorted(salidas["shard"]), sorted(salidas["queue"])
        if a != b:
            difs = [(x, y) for x, y in zip(a, b) if x != y][:3]
            raise AssertionError(f"multiconjuntos distintos, ejemplos: {difs}")
        print(f"OK  test_equivalencia_arquitecturas ({len(a):,} eventos "
              f"identicos entre shard y queue)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            fn()
    print("\nTodos los tests pasaron.")
