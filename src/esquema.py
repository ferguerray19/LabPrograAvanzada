"""Contrato de datos del simulador TPC Sitio 3.

Aquí vive todo lo que NO depende de la arquitectura de escritura elegida:
los contratos (dataclasses), el formateo de timestamps, el reparto de carga,
la abstracción de sumidero y el bucle de generación compartido.

Ninguna función de este módulo consulta el reloj del sistema ni conoce
`multiprocessing`. Esa separación es lo que hace testeable el simulador sin
lanzar procesos ni escribir en disco.
"""

from __future__ import annotations

import json
import queue as _queue
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

# ---------------------------------------------------------------------------
# Constantes del contrato de datos
# ---------------------------------------------------------------------------

#: Campos obligatorios, en el orden y con los nombres literales de la guía.
CAMPOS_MINIMOS = ("timestamp", "sensor_id", "metric", "value", "unit", "worker_id")

#: Campos opcionales recomendados por la guía (sección 3.2). Si se emiten,
#: se emiten en TODOS los eventos: un esquema irregular obliga a Spark a
#: inferir tipos nulos.
CAMPOS_OPCIONALES = ("site", "asset_type", "status", "seq")

SITIO = "S3"

#: Intervalo de muestreo del terminal, en milisegundos (un evento cada 15 s).
DT_MS_POR_DEFECTO = 15_000


# ---------------------------------------------------------------------------
# Tiempo: base determinista y formateo sin strftime por evento
# ---------------------------------------------------------------------------

_EPOCH_DATE = date(1970, 1, 1)
_EPOCH_DT = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parsear_t0(texto: str) -> int:
    """Convierte `--start-time` (ISO 8601 UTC) a milisegundos desde epoch.

    Se ejecuta UNA sola vez, en el proceso padre. A partir de aquí ningún
    componente del simulador vuelve a manipular objetos `datetime`: el tiempo
    circula como entero de milisegundos, que es picklable, barato y
    determinista. Es la corrección directa al uso de `datetime.now()` como
    base temporal, que rompía la reproducibilidad exigida por la guía.
    """
    limpio = texto.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(limpio)
    except ValueError as exc:
        raise ValueError(
            f"--start-time invalido: {texto!r}. Formato esperado "
            "2026-08-24T00:00:00Z (ISO 8601 UTC)."
        ) from exc
    if dt.tzinfo is None:
        raise ValueError("--start-time debe llevar zona horaria explicita (sufijo Z).")
    t0_ms = int((dt - _EPOCH_DT).total_seconds() * 1000)
    if t0_ms < 0:
        raise ValueError("--start-time anterior a 1970-01-01 no esta soportado.")
    return t0_ms


class FormateadorISO:
    """Formatea milisegundos-epoch a ISO 8601 UTC sin llamar a `strftime`.

    Trampa de ingenieria N.o 7: `strftime` mas el slice y la concatenacion,
    ejecutados diez millones de veces, pueden representar un tercio del tiempo
    total. La observacion que abarata el problema es que en una serie de 15 en
    15 segundos la porcion de FECHA cambia una vez al dia, mientras que hora,
    minuto, segundo y milisegundo son aritmetica entera pura.

    Detalles que no son cosmeticos:
      * `__slots__`: el objeto se consulta millones de veces; evita el
        `__dict__` de instancia en cada acceso a atributo.
      * `divmod`: una sola operacion del interprete en lugar de `//` y `%`.
      * es estado mutable, asi que se instancia DENTRO del proceso hijo,
        igual que `random.Random(semilla + worker_id)` (Trampa N.o 4).
      * no valida `t_ms` negativo: esa validacion se paga una vez en
        `parsear_t0`, no diez millones de veces aqui.
    """

    __slots__ = ("_dia_cache", "_fecha")

    def __init__(self) -> None:
        self._dia_cache = -1  # ningun dia real coincide con este centinela
        self._fecha = ""

    def formatear(self, t_ms: int) -> str:
        seg, ms = divmod(t_ms, 1000)
        dia, resto = divmod(seg, 86_400)
        if dia != self._dia_cache:  # ~10 veces en una corrida de 9 dias
            self._dia_cache = dia
            self._fecha = (_EPOCH_DATE + timedelta(days=dia)).isoformat()
        h, r = divmod(resto, 3_600)
        m, s = divmod(r, 60)
        return f"{self._fecha}T{h:02d}:{m:02d}:{s:02d}.{ms:03d}Z"


def formatear_referencia(t_ms: int) -> str:
    """Implementacion lenta y obviamente correcta, usada solo por los tests.

    Emplea `timedelta(milliseconds=...)` en vez de `fromtimestamp(t_ms/1000)`
    porque la division produciria un float y perderia precision justo en los
    casos limite que el test quiere cubrir.
    """
    dt = _EPOCH_DT + timedelta(milliseconds=t_ms)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Reparto de carga
# ---------------------------------------------------------------------------


def repartir(total: int, n: int) -> list[int]:
    """Reparte `total` en `n` partes que suman EXACTAMENTE `total`.

    El desbalance maximo entre la parte mayor y la menor es de 1 unidad.
    Corrige el `total_events // workers` original, que con --workers 3 y
    10.000.000 dejaba 9.999.999 eventos: un evento bajo el minimo duro, con
    el criterio de calidad del dataset en cero y ninguna senal de error.
    """
    if n <= 0:
        raise ValueError("el numero de partes debe ser positivo")
    if total < 0:
        raise ValueError("el total no puede ser negativo")
    base, resto = divmod(total, n)
    return [base + (1 if i < resto else 0) for i in range(n)]


def ticks_necesarios(total_eventos: int, n_puntos: int) -> int:
    """Ticks de simulacion para alcanzar `total_eventos` como PISO.

    El minimo de 10.000.000 se interpreta como piso, no como valor exacto:
    se redondea hacia arriba para que los ~180 puntos de medicion cubran
    todos exactamente la misma ventana temporal. Recortar el ultimo tick
    dejaria series de distinta longitud justo en el borde del dataset, que es
    donde la Fase 2 buscara huecos.
    """
    if n_puntos <= 0:
        raise ValueError("el inventario no puede estar vacio")
    return -(-total_eventos // n_puntos)  # ceil sin importar math


# ---------------------------------------------------------------------------
# Contratos que cruzan entre procesos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanCorrida:
    """Configuracion completa e inmutable de una corrida.

    Es la unica fuente de configuracion del programa: ningun modulo lee
    `sys.argv` ni consulta constantes globales de modulo. Se construye una
    vez en `main.py` a partir de argparse y se propaga hacia abajo.
    """

    workers: int
    total_events: int
    output_dir: str
    arch: str
    batch_size: int
    seed: int
    t0_ms: int
    dt_ms: int
    n_ticks: int
    n_puntos: int
    esquema: str
    start_method: str
    queue_maxsize: int = 64

    @property
    def eventos_esperados(self) -> int:
        return self.n_puntos * self.n_ticks

    @property
    def sim_days(self) -> float:
        return self.n_ticks * self.dt_ms / 1000.0 / 86_400.0


@dataclass(frozen=True)
class PlanWorker:
    """Lo que el padre le entrega a cada hijo.

    Contiene METADATOS, nunca datos. Es deliberadamente pequeno porque es lo
    unico que se encurta con pickle al arrancar el proceso: en la Opcion B se
    paga un encurtido por worker en toda la corrida, no uno por lote.
    """

    worker_id: int
    indices_activos: tuple[int, ...]
    t0_ms: int
    dt_ms: int
    n_ticks: int
    seed: int
    batch_size: int
    output_dir: str
    esquema: str


@dataclass(frozen=True)
class ResumenWorker:
    """Lo unico que vuelve del hijo al padre: estadisticas, jamas eventos."""

    worker_id: int
    archivo: str
    eventos: int
    bytes: int
    puntos: int
    duracion_s: float


@dataclass
class ResumenCorrida:
    """Agregado de la corrida completa, insumo del manifiesto y del CSV."""

    eventos: int
    bytes: int
    duracion_s: float
    archivos: list[str] = field(default_factory=list)
    detalles: list[ResumenWorker] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sumideros
# ---------------------------------------------------------------------------


class Sumidero(Protocol):
    """Destino de las lineas ya serializadas.

    Existe para que `bucle_worker` se pueda ejercitar con un sumidero falso,
    verificando fisica, esquema y conteo sin tocar el disco y sin lanzar
    procesos, que son las dos cosas que hacen lentos e inestables los tests.
    Como efecto lateral, deja el hueco por donde entraria la Opcion A.
    """

    def escribir(self, lote: list[str]) -> None: ...

    def cerrar(self) -> None: ...


class SumideroArchivo:
    """Sumidero de la Opcion B: un archivo propio por worker.

    `newline="\\n"` evita que Windows traduzca a CRLF y cambie el tamano del
    dataset entre plataformas. El buffer de 4 MB amortiza las syscalls
    `write`: sin el, cada `writelines` de 10.000 lineas provocaria decenas de
    llamadas al kernel.
    """

    __slots__ = ("ruta", "_f", "lineas")

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self.lineas = 0
        self._f = open(
            ruta, "w", encoding="utf-8", newline="\n", buffering=4 * 1024 * 1024
        )

    def escribir(self, lote: list[str]) -> None:
        self._f.writelines(lote)
        self.lineas += len(lote)

    def cerrar(self) -> None:
        self._f.close()


class SumideroNulo:
    """Cuenta lineas sin escribirlas. Para tests y para medir el techo de CPU
    del generador aislado del disco (util en el informe de benchmarking)."""

    __slots__ = ("lineas",)

    def __init__(self) -> None:
        self.lineas = 0

    def escribir(self, lote: list[str]) -> None:
        self.lineas += len(lote)

    def cerrar(self) -> None:
        pass


class AbortoSolicitado(RuntimeError):
    """Se pide al worker que termine porque otro proceso fallo.

    Existe para que un worker bloqueado en `put` sobre una cola que nadie
    drena tenga una salida ordenada, en vez de quedarse esperando para
    siempre a un escritor que ya murio.
    """


class SumideroCola:
    """Sumidero de la Opcion A: encola lotes hacia el proceso escritor.

    Tres cosas de este codigo no son cosmeticas (guia, seccion 2.2):

    1. Recibe lineas YA SERIALIZADAS. El worker paga el `json.dumps`, de modo
       que el escritor solo hace `writelines` y nunca se convierte en el
       cuello de botella de la arquitectura.
    2. Encola LOTES, no eventos sueltos. Cada `put` implica un pickle, un
       write al pipe y un unpickle del otro lado; a razon de diez millones de
       operaciones ese costo se come toda la ganancia del paralelismo.
    3. `put` va con timeout y consulta el evento de aborto. Sin eso, si el
       escritor muere la cola se llena hasta `maxsize`, TODOS los workers
       quedan bloqueados en `put` y el programa se congela sin lanzar nada:
       desde afuera es indistinguible de estar trabajando duro.
    """

    __slots__ = ("cola", "aborto", "timeout", "lineas")

    def __init__(self, cola, aborto, timeout: float = 1.0) -> None:
        self.cola = cola
        self.aborto = aborto
        self.timeout = timeout
        self.lineas = 0

    def escribir(self, lote: list[str]) -> None:
        while True:
            if self.aborto.is_set():
                raise AbortoSolicitado("aborto solicitado por el proceso padre")
            try:
                # Bloquea cuando la cola esta llena: esa contrapresion es lo
                # que frena a los productores al ritmo del disco. Sin ella la
                # diferencia entre produccion y escritura se acumula en RAM.
                self.cola.put(lote, timeout=self.timeout)
            except _queue.Full:
                continue  # reintenta y vuelve a mirar el evento de aborto
            self.lineas += len(lote)
            return

    def cerrar(self) -> None:
        """No cierra nada: el centinela lo emite el worker en su `finally`,
        porque tiene que enviarse tambien cuando el bucle termina por
        excepcion."""


class SumideroMemoria:
    """Retiene las lineas en RAM. Es el sumidero falso que hace testeable el
    generador: permite verificar fisica, esquema y conteo sin tocar el disco
    ni lanzar procesos. Solo para muestras pequenas, por razones obvias."""

    __slots__ = ("lineas",)

    def __init__(self) -> None:
        self.lineas: list[str] = []

    def escribir(self, lote: list[str]) -> None:
        self.lineas.extend(lote)

    def cerrar(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Bucle de generacion compartido
# ---------------------------------------------------------------------------


def bucle_worker(plan: PlanWorker, activos: list, sumidero: Sumidero) -> int:
    """Genera, serializa y lotea. Devuelve el numero de eventos emitidos.

    Este es el codigo que ambas arquitecturas comparten: lo unico que las
    distingue es que reciben un `Sumidero` distinto.

    Dos decisiones de rendimiento visibles aqui:

    1. El timestamp se formatea UNA VEZ POR TICK, no una vez por evento.
       Como la particion es por sensor, los ~22 puntos de un worker comparten
       el mismo instante. Con 55.866 ticks eso son 55.866 formateos en vez de
       1,2 millones: la Trampa N.o 7 casi desaparece por construccion.

    2. Los eventos se serializan a texto AQUI, en el worker. En la Opcion B
       ahorra una copia; en la Opcion A seria lo que impide que el proceso
       escritor se convierta en el cuello de botella.
    """
    fmt = FormateadorISO()
    wid = plan.worker_id
    dt_ms = plan.dt_ms
    dt_s = dt_ms / 1000.0
    t_ms = plan.t0_ms
    batch = plan.batch_size
    completo = plan.esquema == "full"

    # Un tick emite tantas lineas como puntos de medicion tenga este worker
    # (~22 con 8 workers). Si el lote es MAS GRANDE que eso, basta con revisar
    # el buffer una vez por tick y el bucle interno queda sin ninguna
    # comparacion extra. Si el lote es mas chico -que es el caso del
    # experimento de lotes de 1, 100... de la seccion 4.4- hay que revisarlo
    # evento a evento, o `--batch-size 1` produciria en realidad lotes del
    # tamano del tick y el experimento mediria otra cosa.
    puntos = sum(a.n_puntos for a in activos)
    fino = batch < puntos

    buf: list[str] = []
    add = buf.append
    dumps = json.dumps
    emitidos = 0

    for seq in range(plan.n_ticks):
        ts = fmt.formatear(t_ms)
        for activo in activos:
            for sensor_id, metric, unit, value, status, asset_type in activo.tick(
                dt_s, t_ms
            ):
                ev = {
                    "timestamp": ts,
                    "sensor_id": sensor_id,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "worker_id": wid,
                }
                if completo:
                    ev["site"] = SITIO
                    ev["asset_type"] = asset_type
                    ev["status"] = status
                    ev["seq"] = seq
                add(dumps(ev, separators=(",", ":")) + "\n")
                # `fino` es un bool local: cuando es False la condicion se
                # corta en la primera comparacion y no cuesta practicamente
                # nada en la ruta caliente.
                if fino and len(buf) >= batch:
                    sumidero.escribir(buf)
                    emitidos += len(buf)
                    buf = []
                    add = buf.append

        if not fino and len(buf) >= batch:
            sumidero.escribir(buf)
            emitidos += len(buf)
            buf = []
            add = buf.append

        t_ms += dt_ms

    if buf:
        sumidero.escribir(buf)
        emitidos += len(buf)

    return emitidos


# ---------------------------------------------------------------------------
# Validacion del evento
# ---------------------------------------------------------------------------

_UNIDADES_VALIDAS = {"C", "mm/s", "A", "kg", "%"}
_ESTADOS_VALIDOS = {"OK", "WARN", "ALARM"}


def validar_evento(ev: dict) -> None:
    """Verifica un evento contra el contrato. Lanza ValueError si falla.

    No se llama por evento durante la generacion (seria absurdo pagarlo diez
    millones de veces): lo usa `bench/validar.py` sobre el dataset final y
    los tests sobre una muestra.
    """
    for campo in CAMPOS_MINIMOS:
        if campo not in ev:
            raise ValueError(f"falta el campo obligatorio {campo!r}")
    if not isinstance(ev["value"], (int, float)) or isinstance(ev["value"], bool):
        raise ValueError(f"value debe ser numerico, no {type(ev['value']).__name__}")
    if not isinstance(ev["worker_id"], int) or isinstance(ev["worker_id"], bool):
        raise ValueError("worker_id debe ser entero")
    if ev["unit"] not in _UNIDADES_VALIDAS:
        raise ValueError(f"unidad desconocida: {ev['unit']!r}")
    if ev["metric"] != ev["metric"].lower():
        raise ValueError(f"metric debe ir en minusculas: {ev['metric']!r}")
    ts = ev["timestamp"]
    if not (isinstance(ts, str) and len(ts) == 24 and ts.endswith("Z") and ts[10] == "T"):
        raise ValueError(f"timestamp fuera de contrato: {ts!r}")
    if "status" in ev and ev["status"] not in _ESTADOS_VALIDOS:
        raise ValueError(f"status invalido: {ev['status']!r}")
