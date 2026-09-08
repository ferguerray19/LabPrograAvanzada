"""Modelos fisicos de los activos del Sitio 3 del Terminal Puerto Coquimbo.

Cada clase mantiene ESTADO entre ticks. Esa es la diferencia practica entre un
dataset creible y uno inservible: sin estado no hay inercia, ni deriva, ni
anomalias con duracion, y en la Fase 2 el detector marcaria falsos positivos
perfectos, imposibles de distinguir de una falla real.

Contrato uniforme de todos los activos:

    tick(dt_s: float, t_ms: int) -> tuple[Lectura, ...]

    donde Lectura = (sensor_id, metric, unit, value, status, asset_type)

Un mismo activo emite varias metricas por tick, y esas metricas estan
ACOPLADAS a traves de su estado interno: no son ruidos independientes con
nombres distintos. La vibracion de una faja sube con la carga, y el amperaje
del motor sube con la misma carga, asi que ambas correlacionan porque
comparten causa.

Inventario del Sitio 3 (~180 puntos de medicion, uno cada 15 s):

    48 reefer   x 3 metricas (temperature, humidity, current) = 144
     6 fajas    x 3 metricas (vibration, current, weight)     =  18
     2 gruas    x 2 metricas (weight, current)                =   4
     1 bascula  x 1 metrica  (weight)                         =   1
    12 patio    x 1 metrica  (temperature)                    =  12
                                                              -----
                                                                179
"""

from __future__ import annotations

import math
import random

# ---------------------------------------------------------------------------
# Constantes fisicas.  Ninguna es magica: todas tienen unidad y justificacion.
# ---------------------------------------------------------------------------

#: Constante de tiempo del lazo termico del reefer, en segundos.
#: Elegida para que con dt_s = 15 el factor de relajacion valga exactamente
#: 0,08, que es el valor del ejemplo de la guia. Expresarlo como tau permite
#: que `dt_s` entre de verdad en la ecuacion sin convertir el modelo en un
#: sistema de ecuaciones diferenciales.
TAU_REEFER_S = 187.5

#: Ganancia termica con la puerta abierta, en C/min (valor de la guia).
#: NO son 8.9: a ese ritmo un reefer pasa de -18 a +4 en menos de dos minutos,
#: que es exactamente el salto imposible contra el que la guia advierte.
GANANCIA_PUERTA_C_MIN = 0.9

#: Deriva termica con el compresor detenido (carga termica del contenedor).
DERIVA_COMPRESOR_OFF_C_MIN = 0.35

#: Probabilidad por tick de que se abra una puerta de reefer. Con ~55.900
#: ticks equivale a unas 2-3 aperturas por contenedor en nueve dias.
P_PUERTA_REEFER = 1 / 20_000

#: Probabilidad por tick de que una faja entre en desbalance progresivo.
P_DESBALANCE_FAJA = 1 / 45_000

TIPOS = ("reefer", "conveyor", "crane", "weighbridge", "yard")


def _tabla_diurna() -> tuple[float, ...]:
    """Perfil diurno de temperatura ambiente, 96 casillas de 15 minutos.

    Se precalcula una vez al importar el modulo para no llamar a `math.sin`
    dentro del bucle caliente. Minimo cerca de las 06:00, maximo cerca de las
    16:00, que es el ciclo tipico de la costa de Coquimbo.
    """
    return tuple(math.sin(2 * math.pi * (i / 96.0 - 0.375)) for i in range(96))


_DIURNA = _tabla_diurna()


def _clasificar(valor: float, warn: float, alarm: float) -> str:
    """Etiqueta OK/WARN/ALARM por umbral simple.

    Este campo es la verdad de terreno para la Fase 2: permite medir cuantas
    anomalias reales detecto el clasificador y cuantas invento.
    """
    if valor >= alarm:
        return "ALARM"
    if valor >= warn:
        return "WARN"
    return "OK"


# ---------------------------------------------------------------------------
# Reefer
# ---------------------------------------------------------------------------


class Reefer:
    """Contenedor refrigerado con setpoint, histeresis de compresor y puerta.

    Estado que persiste entre ticks y por que:
      * `temp`: es toda la inercia del modelo. Sin ella, la serie es ruido.
      * `compresor`: la histeresis genera el ciclado ON/OFF caracteristico,
        y es lo que hace que la corriente y la temperatura correlacionen.
      * `puerta_ticks`: convierte una anomalia puntual en una anomalia
        SOSTENIDA. Un pico de un solo tick es indistinguible de ruido; una
        rampa de varios minutos es algo que la Fase 2 puede detectar.
      * `hum`, `amp`: acopladas a los dos anteriores, con su propia inercia.
    """

    __slots__ = ("sid", "rng", "setpoint", "temp", "hum", "amp", "compresor", "puerta_ticks")

    n_puntos = 3
    tipo = "reefer"

    def __init__(self, idx: int, rng: random.Random, setpoint: float = -18.0) -> None:
        self.sid = f"REEFER_S3_{idx:02d}"
        self.rng = rng
        self.setpoint = setpoint
        self.temp = setpoint + rng.uniform(-0.4, 0.4)
        self.hum = 82.0 + rng.uniform(-3.0, 3.0)
        self.amp = 11.5
        self.compresor = True
        self.puerta_ticks = 0

    def tick(self, dt_s: float, t_ms: int):
        rng = self.rng
        minutos = dt_s / 60.0

        # --- anomalia sostenida: la puerta queda abierta varios minutos -----
        if self.puerta_ticks > 0:
            self.puerta_ticks -= 1
        elif rng.random() < P_PUERTA_REEFER:
            self.puerta_ticks = rng.randint(8, 40)  # 2 a 10 minutos
        abierta = self.puerta_ticks > 0

        # --- histeresis del compresor ---------------------------------------
        # Sin banda muerta el compresor conmutaria en cada tick y la corriente
        # seria una onda cuadrada irreal.
        if self.temp > self.setpoint + 0.5:
            self.compresor = True
        elif self.temp < self.setpoint - 0.3:
            self.compresor = False

        # --- balance termico -------------------------------------------------
        if abierta:
            self.temp += GANANCIA_PUERTA_C_MIN * minutos
        elif self.compresor:
            # Euler explicito sobre un lazo de primer orden. `dt_s` entra de
            # verdad; el `min(1.0, ...)` impide que un dt grande sobrepase el
            # setpoint y haga oscilar el modelo.
            self.temp += (self.setpoint - self.temp) * min(1.0, dt_s / TAU_REEFER_S)
        else:
            self.temp += DERIVA_COMPRESOR_OFF_C_MIN * minutos
        self.temp += rng.gauss(0.0, 0.05)  # ruido del sensor

        # --- humedad: acoplada a la puerta ----------------------------------
        objetivo_h = 95.0 if abierta else 82.0
        self.hum += (objetivo_h - self.hum) * 0.10 + rng.gauss(0.0, 0.3)

        # --- corriente: acoplada al compresor -------------------------------
        objetivo_a = 11.5 if self.compresor else 1.2
        self.amp += (objetivo_a - self.amp) * 0.35 + rng.gauss(0.0, 0.08)

        exceso = self.temp - self.setpoint
        st = _clasificar(exceso, 1.5, 3.0)
        sid = self.sid
        return (
            (sid, "temperature", "C", round(self.temp, 2), st, "reefer"),
            (sid, "humidity", "%", round(self.hum, 2), "OK", "reefer"),
            (sid, "current", "A", round(self.amp, 2), "OK", "reefer"),
        )


# ---------------------------------------------------------------------------
# Faja transportadora
# ---------------------------------------------------------------------------


class Faja:
    """Tramo de faja con flujo intermitente y desgaste progresivo.

    El acoplamiento es el punto central de esta clase: `carga` es la causa
    comun de la vibracion y del amperaje, asi que ambas suben y bajan juntas
    con el flujo de concentrado. Un detector de anomalias entrenado sobre
    esto puede aprender la relacion; sobre tres ruidos independientes, no.

    `desbalance` es una anomalia de rampa lenta: no aparece de golpe, crece
    durante decenas de minutos y luego se repara. Es el tipo de falla que un
    umbral fijo no ve pero una tendencia si.
    """

    __slots__ = ("sid", "rng", "carga", "carga_obj", "flujo", "desbalance", "desb_ticks", "vib", "amp")

    n_puntos = 3
    tipo = "conveyor"

    def __init__(self, idx: int, rng: random.Random) -> None:
        self.sid = f"FAJA_S3_C{idx}"
        self.rng = rng
        self.flujo = False
        self.carga = 0.0        # t/h instantaneas
        self.carga_obj = 0.0
        self.desbalance = 0.0   # mm/s adicionales por desgaste
        self.desb_ticks = 0
        self.vib = 0.6
        self.amp = 11.0

    def tick(self, dt_s: float, t_ms: int):
        rng = self.rng

        # --- flujo intermitente: arranques y paradas de la operacion --------
        if self.flujo:
            if rng.random() < 0.004:
                self.flujo = False
                self.carga_obj = 0.0
        elif rng.random() < 0.010:
            self.flujo = True
            self.carga_obj = rng.uniform(850.0, 1350.0)

        # inercia mecanica: la carga sube y baja con rampa, nunca de golpe
        self.carga += (self.carga_obj - self.carga) * min(1.0, dt_s / 90.0)

        # --- anomalia sostenida: desbalance progresivo ----------------------
        if self.desb_ticks > 0:
            self.desb_ticks -= 1
            self.desbalance += 0.004  # rampa de desgaste
        elif self.desbalance > 0.0:
            self.desbalance = max(0.0, self.desbalance - 0.02)  # mantencion
        elif rng.random() < P_DESBALANCE_FAJA:
            self.desb_ticks = rng.randint(200, 800)  # 50 min a 3,3 h

        # --- variables acopladas a la carga ---------------------------------
        vib_obj = 0.55 + 0.0022 * self.carga + self.desbalance
        self.vib += (vib_obj - self.vib) * 0.4 + rng.gauss(0.0, 0.03)

        amp_obj = 10.5 + 0.030 * self.carga + 1.8 * self.desbalance
        self.amp += (amp_obj - self.amp) * 0.4 + rng.gauss(0.0, 0.15)

        # tonelaje efectivamente movido en este tick, en kg
        kg = self.carga * (dt_s / 3600.0) * 1000.0

        sid = self.sid
        return (
            (sid, "vibration", "mm/s", round(self.vib, 3), _clasificar(self.vib, 4.5, 7.1), "conveyor"),
            (sid, "current", "A", round(self.amp, 2), _clasificar(self.amp, 52.0, 60.0), "conveyor"),
            (sid, "weight", "kg", round(kg, 1), "OK", "conveyor"),
        )


# ---------------------------------------------------------------------------
# Grua movil
# ---------------------------------------------------------------------------


class Grua:
    """Grua con telemetria de ciclo: izar, trasladar, bajar, retornar.

    El estado que persiste es la MAQUINA DE ESTADOS del ciclo, no un valor
    numerico. Es lo que produce el patron periodico caracteristico: la
    corriente tiene un pico en el izaje y cae en el retorno en vacio, y el
    peso en el spreader es cero exactamente durante esa fase de retorno.
    """

    __slots__ = ("sid", "rng", "fase", "restante", "carga", "amp")

    n_puntos = 2
    tipo = "crane"

    #: (nombre, ticks tipicos, corriente base en A, lleva carga)
    _FASES = (
        ("izar", 8, 46.0, True),
        ("trasladar", 10, 24.0, True),
        ("bajar", 6, 14.0, True),
        ("retorno", 12, 11.0, False),
    )

    def __init__(self, idx: int, rng: random.Random) -> None:
        self.sid = f"GRUA_S3_STS{idx:02d}"
        self.rng = rng
        self.fase = rng.randrange(4)  # desfase inicial: no arrancan sincronizadas
        self.restante = self._FASES[self.fase][1]
        self.carga = rng.uniform(8_000.0, 28_000.0)
        self.amp = 20.0

    def tick(self, dt_s: float, t_ms: int):
        rng = self.rng
        self.restante -= 1
        if self.restante <= 0:
            self.fase = (self.fase + 1) % 4
            nombre, dur, _, _ = self._FASES[self.fase]
            self.restante = max(1, dur + rng.randint(-2, 2))
            if nombre == "izar":
                # contenedor nuevo: entre un vacio de 2 t y un lleno de 30 t
                self.carga = rng.uniform(2_200.0, 30_000.0)

        _, _, amp_base, con_carga = self._FASES[self.fase]
        # la corriente escala con la carga izada: acoplamiento explicito
        amp_obj = amp_base * (1.0 + 0.6 * self.carga / 30_000.0 if con_carga else 1.0)
        self.amp += (amp_obj - self.amp) * 0.5 + rng.gauss(0.0, 0.4)

        peso = self.carga if con_carga else 0.0
        sid = self.sid
        return (
            (sid, "weight", "kg", round(peso, 1), "OK", "crane"),
            (sid, "current", "A", round(self.amp, 2), _clasificar(self.amp, 70.0, 85.0), "crane"),
        )


# ---------------------------------------------------------------------------
# Bascula de acceso vehicular
# ---------------------------------------------------------------------------


class Bascula:
    """Bascula camionera: plataforma vacia la mayor parte del tiempo.

    Es el unico activo cuya serie es fundamentalmente discontinua, y por eso
    vale la pena tenerlo: obliga a que la Fase 2 no asuma que toda metrica es
    una senal continua. El estado que persiste es cuantos ticks le quedan al
    pesaje en curso, para que un camion ocupe varias lecturas consecutivas y
    no un unico pico aislado.
    """

    __slots__ = ("sid", "rng", "restante", "peso")

    n_puntos = 1
    tipo = "weighbridge"

    def __init__(self, idx: int, rng: random.Random) -> None:
        self.sid = f"BASCULA_S3_{idx:02d}"
        self.rng = rng
        self.restante = 0
        self.peso = 0.0

    def tick(self, dt_s: float, t_ms: int):
        rng = self.rng
        if self.restante > 0:
            self.restante -= 1
            # el camion se asienta sobre la plataforma: el valor converge
            self.peso += rng.gauss(0.0, 12.0)
        elif rng.random() < 0.020:  # ~1 camion cada 12 minutos
            self.restante = rng.randint(3, 8)
            self.peso = rng.uniform(12_000.0, 42_000.0)
        else:
            self.peso = abs(rng.gauss(0.0, 4.0))  # deriva de la celda de carga

        return (
            (self.sid, "weight", "kg", round(self.peso, 1),
             _clasificar(self.peso, 40_000.0, 45_000.0), "weighbridge"),
        )


# ---------------------------------------------------------------------------
# Sensor ambiental de patio
# ---------------------------------------------------------------------------


class Ambiental:
    """Temperatura ambiente del patio, con ciclo diurno y deriva local.

    Es el unico activo cuya fisica depende del INSTANTE ABSOLUTO y no solo
    del paso `dt_s`: usa `t_ms` para saber la hora del dia. Por eso todos los
    activos reciben `t_ms` en el contrato de `tick`, aunque la mayoria lo
    ignore: una interfaz uniforme es mas facil de defender que cinco firmas.
    """

    __slots__ = ("sid", "rng", "base", "amplitud", "temp")

    n_puntos = 1
    tipo = "yard"

    def __init__(self, idx: int, rng: random.Random) -> None:
        self.sid = f"AMBIENTE_S3_{idx:02d}"
        self.rng = rng
        self.base = 14.5 + rng.uniform(-1.0, 1.0)   # microclima de la posicion
        self.amplitud = 5.5 + rng.uniform(-0.8, 0.8)
        self.temp = self.base

    def tick(self, dt_s: float, t_ms: int):
        casilla = (t_ms // 900_000) % 96  # indice de cuarto de hora del dia
        objetivo = self.base + self.amplitud * _DIURNA[casilla]
        # inercia termica del aire: la lectura sigue al objetivo con retraso
        self.temp += (objetivo - self.temp) * 0.05 + self.rng.gauss(0.0, 0.08)
        return (
            (self.sid, "temperature", "C", round(self.temp, 2), "OK", "yard"),
        )


# ---------------------------------------------------------------------------
# Inventario y reparto entre workers
# ---------------------------------------------------------------------------

#: (clase, cantidad). El inventario es una constante del sitio simulado.
INVENTARIO = (
    (Reefer, 48),
    (Faja, 6),
    (Grua, 2),
    (Bascula, 1),
    (Ambiental, 12),
)


def construir_inventario(semilla: int) -> list:
    """Instancia los 69 activos del Sitio 3 en un orden canonico y estable.

    Cada activo recibe su PROPIO `random.Random`, derivado del indice global
    y no del worker que lo ejecuta. Consecuencias:

      * Trampa N.o 4 evitada por construccion: nadie usa el modulo `random`
        global, asi que ningun hijo hereda el estado del padre tras el fork.
      * La serie de un sensor dado es identica corra en el worker que corra.
        La reproducibilidad deja de depender de `--workers`, que es una
        garantia mas fuerte que la que pide la guia.
    """
    activos = []
    idx_global = 0
    for clase, cantidad in INVENTARIO:
        for i in range(1, cantidad + 1):
            rng = random.Random(semilla * 1_000_003 + idx_global)
            activos.append(clase(i, rng))
            idx_global += 1
    return activos


def contar_puntos(activos: list) -> int:
    """Puntos de medicion totales: un activo emite varias metricas por tick."""
    return sum(a.n_puntos for a in activos)


def asignar_workers(activos: list, n_workers: int) -> list[tuple[int, ...]]:
    """Reparte los activos entre workers equilibrando PUNTOS, no activos.

    Los activos son heterogeneos: un reefer emite 3 metricas y una bascula 1.
    Un round-robin sobre activos dejaria workers con hasta 3x mas trabajo que
    otros, y el desbalance se veria directamente como una meseta prematura en
    la curva de speedup.

    La heuristica es LPT (Longest Processing Time first): ordenar por carga
    descendente y dar cada activo al worker que va mas descargado. Con este
    inventario deja un desbalance maximo de 1 punto entre workers.

    Un activo NUNCA se parte entre dos workers: su estado fisico es
    indivisible, y sus metricas acopladas deben salir del mismo objeto.
    """
    if n_workers <= 0:
        raise ValueError("n_workers debe ser positivo")
    orden = sorted(range(len(activos)), key=lambda i: -activos[i].n_puntos)
    cargas = [0] * n_workers
    cubos: list[list[int]] = [[] for _ in range(n_workers)]
    for i in orden:
        destino = min(range(n_workers), key=lambda w: cargas[w])
        cubos[destino].append(i)
        cargas[destino] += activos[i].n_puntos
    # se reordena cada cubo al orden canonico para que el archivo resultante
    # tenga los sensores en orden estable entre corridas
    return [tuple(sorted(c)) for c in cubos]
