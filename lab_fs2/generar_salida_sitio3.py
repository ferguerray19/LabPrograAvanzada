# Generado automáticamente desde simulador_sitio3.ipynb (Fase 1).
# Solo incluye las celdas que producen salida_sitio3/: sin pip install, sin la
# corrida corta de prueba y sin gráficos. Ejecutar dentro del contenedor:
#   docker compose exec -w /opt/workspace jupyter python3 generar_salida_sitio3.py

# ---- celda 4 ----
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from collections import deque
import os

# Semilla única para que la corrida sea reproducible de punta a punta.
# Todo objeto que necesite aleatoriedad recibe este mismo generador (o uno
# derivado con rng.spawn()), nunca np.random.* global.
SEMILLA = 42
rng = np.random.default_rng(SEMILLA)

pd.set_option("display.max_columns", 20)
plt.rcParams["figure.figsize"] = (11, 4)


# ---- celda 6 ----
class C:
    """Namespace de constantes físicas. No es una clase de comportamiento: es solo
    un contenedor con nombre para no ensuciar el módulo con globals sueltos."""

    # --- Reloj -------------------------------------------------------
    DT_S = 1.0  # paso fijo del reloj maestro [s]. Todo lo continuo integra con este dt.

    # --- Escala de la corrida -----------------------------------------
    DIAS_SIMULADOS = 7
    N_REEFERS = 100
    HORAS_SIMULADAS = DIAS_SIMULADOS * 24

    # Corrida corta de humo, para validar el motor antes de la corrida larga.
    HORAS_PRUEBA = 2
    N_REEFERS_PRUEBA = 5

    # --- Capa ambiental (Coquimbo, costa) ------------------------------
    AMB_TEMP_MIN_C = 9.0        # mínimo diario típico de invierno/primavera costero
    AMB_TEMP_MAX_C = 22.0       # máximo diario típico
    AMB_HORA_MAX = 16.0         # hora del máximo térmico [h decimal]
    AMB_ESTACIONAL_AMP_C = 1.5  # deriva lenta sobre la semana simulada [°C]
    AMB_ESTACIONAL_PERIODO_D = 180.0  # medio año, solo se nota como rampa suave en 7 días
    AMB_RUIDO_SIGMA_C = 0.15    # amplitud del ruido de baja frecuencia (aprox. "rosa")
    AMB_RUIDO_BETA = 0.995      # polo del AR(1) que aproxima el ruido rosa: entre más
                                # cerca de 1, más "color" (energía concentrada en baja frecuencia)

    PROB_CAMANCHACA = 0.35      # probabilidad de neblina costera matinal, por día
    CAMANCHACA_HORA_INI = 5.0
    CAMANCHACA_HORA_FIN = 11.0
    CAMANCHACA_RAD_FRAC = 0.20  # la radiación cae a este porcentaje de la despejada
    CAMANCHACA_HR_MIN_PCT = 90.0

    RAD_MAX_WM2 = 850.0         # irradiancia de mediodía despejado, costa norte-centro
    VIENTO_MEDIA_MS = 6.0
    VIENTO_AMP_TARDE_MS = 3.0   # refuerzo de viento de tarde (clásico de la costa chilena)
    VIENTO_RACHA_PROB = 0.01    # prob. por paso de ráfaga (paso = 1 s, así que son raras)
    VIENTO_RACHA_AMP_MS = 5.0
    # Episodios de viento fuerte: sin ellos el viento nunca pasa de ~12 m/s y el límite
    # operacional de 20 m/s no se alcanza jamás, así que el dataset no tendría ni una sola
    # detención por viento — justo el hueco correlacionado que el ejercicio quiere ver.
    VIENTO_EPISODIO_PROB_DIA = 0.35
    VIENTO_EPISODIO_DUR_H = (2.0, 5.0)
    VIENTO_EPISODIO_AMP_MS = (9.0, 16.0)

    GRUA_VIENTO_LIMITE_MS = 20.0
    # Al reanudar no basta con que el viento baje del límite: hay una banda de rearme y un
    # tiempo mínimo de espera. Es la práctica operacional real (no se reanuda izaje en la
    # primera bajada de una ráfaga) y además evita que la reanudación quede pegada al
    # cruce del umbral, donde el muestreo de 60 s no alcanza a distinguir qué pasó antes.
    GRUA_VIENTO_REARME_MS = 18.0
    GRUA_STANDDOWN_MIN = 10.0

    MAREA_RANGO_M = 1.5
    MAREA_PERIODO_S = 12.42 * 3600.0  # semidiurna real (M2), no 12h parejo

    # --- Red eléctrica --------------------------------------------------
    N_ALIMENTADORES = 4
    TOMAS_POR_ALIMENTADOR = N_REEFERS // N_ALIMENTADORES
    TENSION_NOMINAL_V = 400.0
    CAIDA_TENSION_MAX_FRAC = 0.08   # caída máx. ~8% con el alimentador a plena capacidad
    ALIMENTADOR_CAPACIDAD_KW = TOMAS_POR_ALIMENTADOR * 6.0 * 1.15  # ~15% de margen sobre
                                                                     # todos los reefers en marcha a la vez
    TRANSFERENCIA_GENERADOR_S = (10.0, 30.0)  # rango de corte antes de restituir por generador

    # --- Reefer -----------------------------------------------------------
    REEFER_SETPOINT_C = -18.0
    REEFER_BANDA_MUERTA_C = 0.5
    REEFER_ANTIRRECICLO_S = 3 * 60.0
    REEFER_UA_WK = 30.0            # coeficiente global de pérdidas de la caja [W/K]
    REEFER_CAPACIDAD_TERMICA_KJ_K = 2800.0
    # ^ estimado a partir de masa de carga + estructura de un contenedor 40' reefer
    #   (carga ~20 t * cp promedio ~2.2 kJ/kg·K para producto refrigerado, más la envolvente).
    #   No viene dado en el enunciado: es la constante que fija cuán "lenta" es la térmica
    #   de la caja: con UA=30 W/K y esta capacidad, una desconexión total tarda horas en
    #   derivar a temperatura ambiente, que es justamente la firma esperada en la tabla de fallas.
    REEFER_POTENCIA_FRIG_KW = 5.0
    REEFER_COP_MIN = 1.2
    REEFER_COP_MAX = 1.8
    REEFER_KW_COMPRESOR = 6.0
    REEFER_KW_RALENTI = 0.5
    REEFER_MUESTREO_S = 60.0
    REEFER_PROB_PUERTA_POR_PASO = 1.0 / (6 * 3600.0)  # ~1 apertura cada 6 h en promedio
    REEFER_PUERTA_CARGA_KW = 4.0     # carga térmica puntual al abrir
    REEFER_PUERTA_TAU_S = 10 * 60.0  # recuperación lenta tras cerrar
    REEFER_TASA_MAX_C_S = 3.0 / 60.0  # 3 °C/min: cota de seguridad, no debería ni acercarse
    # Coeficiente de temperatura sol-aire [K/(W/m2)]: cuánto sube la temperatura exterior
    # *efectiva* que ve la envolvente por cada W/m2 de irradiancia. Equivale a
    # absortividad/coef. de película exterior ~ 0.6/60, es decir unos +8.5 K al mediodía
    # despejado. Ver la nota en PoblacionReefers.paso sobre por qué la radiación no se
    # suma como flujo directo al interior.
    REEFER_K_SOL_AIRE_KM2_W = 0.010
    REEFER_PROB_EXPUESTO = 0.3       # fracción del patio sin sombra de otros contenedores
    REEFER_TENSION_DERATE_MIN = 0.85  # piso del régimen degradado: con tensión baja pero
                                        # presente, el compresor no rinde menos que esto
    REEFER_TENSION_MIN_OPERACION_FRAC = 0.5  # bajo esta fracción de la nominal se considera
                                               # que no hay suministro y el equipo no arranca

    # --- Faja transportadora -------------------------------------------
    FAJA_LARGO_M = 180.0
    FAJA_VEL_NOM_MS = 4.2
    FAJA_RAMPA_S = 45.0
    FAJA_RETARDO_S = FAJA_LARGO_M / FAJA_VEL_NOM_MS  # tiempo muerto cola -> cabeza
    FAJA_CORRIENTE_VACIO_A = 60.0
    FAJA_CORRIENTE_PLENA_A = 210.0
    # Tonelaje nominal a cinta llena [t/h]. Este valor está acoplado a la capacidad de la
    # báscula: todo lo que faja + grúas mueven en el día tiene que poder entrar por un
    # único portón (~55 camiones/h x ~29 t netos ~ 1600 t/h). Con 700 t/h de faja más
    # ~380 t/h de grúas, el portón trabaja al ~65% y el balance de masa diario cierra sin
    # que se acumule material imposible de retirar.
    FAJA_TON_H_PLENA = 700.0
    FAJA_TAU_POLINES_MIN = 15.0
    FAJA_MUESTREO_S = 1.0
    FAJA_UMBRAL_SOBRECARGA_FRAC = 1.15   # % del tonelaje de diseño que se considera sobrecarga
    FAJA_FACTOR_SOBRECARGA = 1.6         # cuánto se excede la carga de diseño durante la falla
    FAJA_PATINAJE_CAIDA_VEL_FRAC = 0.30  # pérdida máxima de velocidad por patinaje
    FAJA_TAU_PATINAJE_S = 20.0
    # ^ el patinaje tampoco es un escalón: la correa empieza a resbalar sobre el tambor
    #   motriz progresivamente. Sin esta constante de tiempo, la velocidad daría un salto
    #   de 1.26 m/s en un paso y violaría la primera regla del simulador.

    # Cota de variación de velocidad, derivada de la física y no puesta a ojo: la suma de
    # lo que puede aportar la rampa de aceleración y lo que puede aportar la entrada del
    # patinaje, con un 20% de margen.
    FAJA_TASA_MAX_VEL_MS_S = (FAJA_VEL_NOM_MS / FAJA_RAMPA_S
                               + FAJA_VEL_NOM_MS * FAJA_PATINAJE_CAIDA_VEL_FRAC / FAJA_TAU_PATINAJE_S) * 1.2
    FAJA_POLINES_K_CARGA_C = 15.0        # aporte a la temp. de equilibrio por carga plena [°C]
    FAJA_POLINES_K_FRICCION_C = 45.0     # aporte por rodamiento 100% degradado [°C]

    # --- Grúas móviles ----------------------------------------------------
    GRUA_FASES = ["posicionar", "enganchar", "izar", "girar", "descender", "soltar", "retornar"]
    GRUA_CICLO_MED_S = 115.0     # entre 90 y 150 s de ciclo completo
    GRUA_CICLO_SIGMA = 0.18      # sigma lognormal (forma), no unidades físicas
    GRUA_INTERFERENCIA_EXTRA_S = 25.0  # penalización esperada cuando ambas grúas están activas
    GRUA_POT_IZAR_KW = 40.0
    GRUA_POT_DESCENSO_KW = -5.0   # regenerativo: entrega energía a la red al bajar
    GRUA_POT_OTRAS_KW = 8.0

    # --- Báscula ------------------------------------------------------------
    BASCULA_TARA_MIN_T = 14.0
    BASCULA_TARA_MAX_T = 16.0
    BASCULA_BRUTO_MAX_T = 45.0
    BASCULA_ASENTAMIENTO_S = (3.0, 6.0)
    BASCULA_TIEMPO_TOTAL_S = (40.0, 90.0)
    BASCULA_HZ_ASENTAMIENTO = 10.0  # frecuencia de registro durante la oscilación amortiguada
    BASCULA_MUESTREO_COLA_S = 60.0
    # Los camiones no llegan porque sí: se despachan para retirar el material que faja y
    # grúas van produciendo. La tasa de despacho es proporcional al material pendiente
    # (ganancia K), acotada, y modulada por el ritmo de los turnos. Así el balance de masa
    # del día cierra por construcción física y no por un ajuste estadístico a posteriori.
    BASCULA_K_DESPACHO_VEH_H_POR_T = 1.2
    BASCULA_TASA_MAX_VEH_H = 70.0    # sobre la capacidad de atención: por eso se forma cola
    BASCULA_MODULACION_TURNO = (0.7, 1.5)  # factor valle / peak de cambio de turno
    BASCULA_CARGA_MIN_T = 5.0        # bajo esto no se despacha un camión

    CARGA_PROMEDIO_GRUA_T = 8.0
    # ^ toneladas de carga por movimiento de grúa. No es el peso de un contenedor lleno:
    #   es el promedio de una mezcla real de llenos (10-14 t de carga) y vacíos (~2 t).

    # --- Buque y turnos --------------------------------------------------
    TURNOS_INICIO_H = [0.0, 8.0, 16.0]
    CAMBIO_TURNO_CAIDA_MIN = (15.0, 20.0)
    BUQUE_N_VENTANAS_RANGO = (2, 3)     # naves distintas a lo largo del horizonte simulado
    # Duración de atraque y separación entre naves como *fracción del horizonte total*
    # (no horas fijas): así la corrida corta de prueba también alcanza a tener una nave
    # en sitio en algún momento, en vez de quedar 100% del tiempo sin actividad.
    # Con 7 días de horizonte, 0.15-0.30 equivale a ~25-50 h por nave, coherente con un
    # buque real trabajándose en el sitio.
    BUQUE_DURACION_FRAC_RANGO = (0.15, 0.30)
    BUQUE_GAP_FRAC_RANGO = (0.05, 0.20)

    # --- Conservación de masa ------------------------------------------
    MASA_MARGEN_PCT = 3.0
    # Piso de producción para exigir el margen diario: en un día casi sin nave, el
    # remanente pendiente de retirar del día anterior domina el cociente y el porcentaje
    # deja de decir nada útil. Esos días se cubren igual con el chequeo acumulado.
    MASA_MIN_DIA_T = 500.0


C.TOMAS_POR_ALIMENTADOR  # fuerza evaluación temprana si algo en la clase quedó mal tipeado


# ---- celda 8 ----
class Reloj:
    """Reloj maestro. Avanza en pasos fijos de `dt` segundos y es la única fuente
    de tiempo simulado: nadie muestrea por su cuenta, todos preguntan a este objeto.
    """

    def __init__(self, inicio_utc: datetime, dt_s: float = C.DT_S) -> None:
        self.inicio_utc = inicio_utc
        self.dt = dt_s
        self.paso_actual = 0

    @property
    def t_s(self) -> float:
        """Segundos transcurridos desde el inicio de la simulación."""
        return self.paso_actual * self.dt

    @property
    def hora_decimal(self) -> float:
        """Hora del día en formato decimal (0.0-24.0), para curvas diurnas."""
        return (self.t_s / 3600.0) % 24.0

    @property
    def dia(self) -> int:
        return int(self.t_s // 86400)

    @property
    def timestamp_utc(self) -> datetime:
        return self.inicio_utc + timedelta(seconds=self.t_s)

    def avanzar(self) -> None:
        self.paso_actual += 1


# ---- celda 10 ----
class Ambiente:
    """Capa ambiental costera (Coquimbo). Avanza con el reloj maestro y expone el
    estado del clima que todas las entidades consultan en modo lectura.
    """

    def __init__(self, reloj: Reloj, rng: np.random.Generator) -> None:
        self.reloj = reloj
        self.rng = rng

        self.temp_c: float = (C.AMB_TEMP_MIN_C + C.AMB_TEMP_MAX_C) / 2
        self.rad_wm2: float = 0.0
        self.hr_pct: float = 65.0
        self.viento_ms: float = C.VIENTO_MEDIA_MS
        self.marea_m: float = 0.0
        self.camanchaca_activa: bool = False

        self._ruido_ar1_c: float = 0.0
        self._dia_sorteado: Optional[int] = None
        self._camanchaca_hoy: bool = False
        self._episodio_viento: Optional[tuple] = None  # (hora_inicio, duracion_h, amplitud)

    def _amplitud_episodio_viento(self, hora: float) -> float:
        """Amplitud del episodio de viento fuerte del día, con entrada y salida suaves.
        La ventana de coseno alzado evita que el viento aparezca de golpe: también es una
        variable con inercia, aunque no esté sujeta a una aserción de tasa_max."""
        if self._episodio_viento is None:
            return 0.0
        inicio, duracion, amplitud = self._episodio_viento
        if not (inicio <= hora < inicio + duracion):
            return 0.0
        avance = (hora - inicio) / duracion
        return amplitud * (0.5 - 0.5 * np.cos(2 * np.pi * avance))

    def _temperatura_base(self, hora: float, t_s: float) -> float:
        """Ciclo diurno (una armónica, ver TODO ALUMNO 1 más abajo) + deriva estacional lenta."""
        # TODO ALUMNO (extensión 1): una sola armónica pone el mínimo ~12 h antes del
        # máximo exacto (aquí cae cerca de las 04:00 en vez de las 06:30 pedidas). Agrega
        # una segunda armónica (`+ amp2*cos(2*fase + phi)`) para desplazar el mínimo sin
        # mover el máximo de las 16:00.
        medio = (C.AMB_TEMP_MIN_C + C.AMB_TEMP_MAX_C) / 2
        amp = (C.AMB_TEMP_MAX_C - C.AMB_TEMP_MIN_C) / 2
        fase = 2 * np.pi * (hora - C.AMB_HORA_MAX) / 24.0
        diurno = medio + amp * np.cos(fase)
        estacional = C.AMB_ESTACIONAL_AMP_C * np.sin(2 * np.pi * t_s / (C.AMB_ESTACIONAL_PERIODO_D * 86400))
        return diurno + estacional

    def paso(self, dt: float) -> None:
        t_s = self.reloj.t_s
        hora = self.reloj.hora_decimal
        dia = self.reloj.dia

        # La camanchaca se sortea una vez al día (evento diario), no por paso.
        if dia != self._dia_sorteado:
            self._dia_sorteado = dia
            self._camanchaca_hoy = self.rng.random() < C.PROB_CAMANCHACA
            if self.rng.random() < C.VIENTO_EPISODIO_PROB_DIA:
                duracion = self.rng.uniform(*C.VIENTO_EPISODIO_DUR_H)
                self._episodio_viento = (
                    self.rng.uniform(8.0, 22.0 - duracion),  # los temporales de la costa
                                                                # entran de día, no de noche
                    duracion,
                    self.rng.uniform(*C.VIENTO_EPISODIO_AMP_MS),
                )
            else:
                self._episodio_viento = None

        self.camanchaca_activa = (
            self._camanchaca_hoy and C.CAMANCHACA_HORA_INI <= hora < C.CAMANCHACA_HORA_FIN
        )

        # --- temperatura: base determinística + ruido AR(1) (aprox. ruido rosa) ---
        beta = C.AMB_RUIDO_BETA
        sigma_innovacion = C.AMB_RUIDO_SIGMA_C * np.sqrt(1 - beta ** 2)
        self._ruido_ar1_c = beta * self._ruido_ar1_c + self.rng.normal(0.0, sigma_innovacion)
        self.temp_c = self._temperatura_base(hora, t_s) + self._ruido_ar1_c

        # --- radiación solar: campana diurna, apagada de noche, recortada por camanchaca ---
        if 6.0 <= hora <= 18.0:
            rad_despejada = C.RAD_MAX_WM2 * max(0.0, np.sin(np.pi * (hora - 6.0) / 12.0))
        else:
            rad_despejada = 0.0
        self.rad_wm2 = rad_despejada * (C.CAMANCHACA_RAD_FRAC if self.camanchaca_activa else 1.0)

        # --- humedad relativa: inversa a la temperatura, piso alto con camanchaca ---
        hr_base = 75.0 - (self.temp_c - (C.AMB_TEMP_MIN_C + C.AMB_TEMP_MAX_C) / 2) * 1.5
        if self.camanchaca_activa:
            hr_base = max(hr_base, C.CAMANCHACA_HR_MIN_PCT + abs(self.rng.normal(0.0, 1.5)))
        self.hr_pct = float(np.clip(hr_base, 20.0, 100.0))

        # --- viento: perfil diario con refuerzo de tarde + ráfagas ocasionales ---
        refuerzo_tarde = C.VIENTO_AMP_TARDE_MS * max(0.0, np.sin(np.pi * (hora - 10.0) / 14.0))
        racha = C.VIENTO_RACHA_AMP_MS if self.rng.random() < C.VIENTO_RACHA_PROB else 0.0
        episodio = self._amplitud_episodio_viento(hora)
        self.viento_ms = max(0.0, C.VIENTO_MEDIA_MS + refuerzo_tarde - C.VIENTO_MEDIA_MS / 2
                              + episodio + racha + self.rng.normal(0.0, 0.4))

        # --- marea: semidiurna M2 ---
        self.marea_m = (C.MAREA_RANGO_M / 2) * np.sin(2 * np.pi * t_s / C.MAREA_PERIODO_S)


# ---- celda 12 ----
@dataclass
class Alimentador:
    """Un alimentador del patio: agrupa `TOMAS_POR_ALIMENTADOR` tomas de reefer."""

    id: int
    reefer_ids: np.ndarray  # ids de los reefers que cuelgan de este alimentador
    capacidad_kw: float = C.ALIMENTADOR_CAPACIDAD_KW
    energizado: bool = True
    tension_v: float = C.TENSION_NOMINAL_V
    demanda_kw: float = 0.0
    en_generador: bool = False


class RedElectrica:
    """Red eléctrica del patio de reefers, con topología explícita alimentador -> reefers.

    La tensión de cada alimentador cae con su propia carga (lazo de realimentación: a mayor
    demanda, menor tensión, y con menor tensión el compresor rinde menos y alarga su ciclo,
    lo que a su vez sostiene la demanda). Los eventos de protección y de transferencia a
    generador los dispara `InyectorFallas`; esta clase solo ejecuta el efecto físico.
    """

    def __init__(self, n_reefers: int = C.N_REEFERS, n_alimentadores: int = C.N_ALIMENTADORES) -> None:
        ids = np.arange(n_reefers)
        grupos = np.array_split(ids, n_alimentadores)
        self.alimentadores = [Alimentador(id=i, reefer_ids=grupo) for i, grupo in enumerate(grupos)]

        self.id_a_alimentador = np.empty(n_reefers, dtype=int)
        for alim in self.alimentadores:
            self.id_a_alimentador[alim.reefer_ids] = alim.id

        # Tensión "vista" por cada reefer en el paso anterior (rompe la circularidad
        # tensión->potencia->demanda->tensión dentro del mismo instante: se usa el valor
        # del paso t-1 para calcular el comportamiento del reefer en el paso t).
        self.tension_por_reefer_v = np.full(n_reefers, C.TENSION_NOMINAL_V)

    def _tension_alimentador(self, alim: Alimentador) -> float:
        if not alim.energizado:
            return 0.0
        carga_frac = alim.demanda_kw / alim.capacidad_kw
        caida_frac = C.CAIDA_TENSION_MAX_FRAC * min(carga_frac, 1.5)
        return C.TENSION_NOMINAL_V * (1.0 - caida_frac)

    def paso(self, demanda_por_reefer_kw: np.ndarray) -> None:
        """Recalcula demanda y tensión de cada alimentador a partir del consumo real
        de sus reefers en *este* paso, y publica la tensión que verán los reefers en
        el paso siguiente."""
        for alim in self.alimentadores:
            if alim.energizado:
                alim.demanda_kw = float(demanda_por_reefer_kw[alim.reefer_ids].sum())
                alim.tension_v = self._tension_alimentador(alim)
                self.tension_por_reefer_v[alim.reefer_ids] = alim.tension_v
            else:
                alim.demanda_kw = 0.0
                alim.tension_v = 0.0
                self.tension_por_reefer_v[alim.reefer_ids] = 0.0

    def abrir_proteccion(self, alimentador_id: int) -> None:
        self.alimentadores[alimentador_id].energizado = False

    def cerrar_proteccion(self, alimentador_id: int) -> None:
        self.alimentadores[alimentador_id].energizado = True


# ---- celda 14 ----
class Sensor:
    """Sensor base: agrega ruido gaussiano y cuantización a una lectura del estado
    verdadero. Estas dos degradaciones son intrínsecas a cualquier instrumento y por
    eso viven en la clase base, no en una subclase.
    """

    def __init__(self, ruido_sigma: float, resolucion: float, rng: np.random.Generator,
                 id_entidad: Optional[int] = None) -> None:
        self.ruido_sigma = ruido_sigma
        self.resolucion = resolucion
        self.rng = rng
        self.id_entidad = id_entidad
        self.calidad = "ok"

    def _con_ruido(self, valor_verdadero: float) -> float:
        return valor_verdadero + self.rng.normal(0.0, self.ruido_sigma)

    def _cuantizado(self, valor: float) -> float:
        if self.resolucion <= 0:
            return valor
        return float(np.round(valor / self.resolucion) * self.resolucion)

    def leer(self, valor_verdadero: float) -> float:
        self.calidad = "ok"
        return self._cuantizado(self._con_ruido(valor_verdadero))


class SensorConDeriva(Sensor):
    """Mixin funcional: agrega un offset lento (deriva) que crece a una tasa fija
    mientras la falla de tipo 'deriva de sensor' esté activa. La deriva se acumula
    en el instrumento y es independiente del estado real del proceso: por eso, en
    telemetría, se ve como sesgo creciente sin que la variable física se mueva.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.deriva_actual = 0.0
        self.deriva_tasa = 0.0  # unidades de la señal por segundo; 0 = sin falla activa

    def avanzar_deriva(self, dt: float) -> None:
        self.deriva_actual += self.deriva_tasa * dt

    def leer(self, valor_verdadero: float) -> float:
        self.calidad = "ok" if self.deriva_tasa == 0.0 else "deriva"
        return self._cuantizado(self._con_ruido(valor_verdadero) + self.deriva_actual)


class SensorPegable(Sensor):
    """Mixin funcional: el instrumento puede quedar pegado en el último valor válido,
    ignorando por completo el estado real. Es la firma de 'sensor pegado': valor
    constante en telemetría mientras el proceso real sigue variando.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pegado = False
        self.valor_pegado: Optional[float] = None

    def pegar(self, valor_actual: float) -> None:
        self.pegado = True
        self.valor_pegado = valor_actual

    def despegar(self) -> None:
        self.pegado = False
        self.valor_pegado = None

    def leer(self, valor_verdadero: float) -> float:
        if self.pegado:
            self.calidad = "pegado"
            return self.valor_pegado
        return super().leer(valor_verdadero)


class SensorInstrumento(SensorConDeriva, SensorPegable):
    """Sensor de instrumento completo: ruido + cuantización (de `Sensor`) más deriva
    y falla pegada. Es el que se usa para las variables sobre las que `InyectorFallas`
    programa fallas de sensor (p. ej. la temperatura de cada reefer)."""

    def leer(self, valor_verdadero: float) -> float:
        if self.pegado:
            self.calidad = "pegado"
            return self.valor_pegado
        self.calidad = "ok" if self.deriva_tasa == 0.0 else "deriva"
        return self._cuantizado(self._con_ruido(valor_verdadero) + self.deriva_actual)


# ---- celda 16 ----
class PoblacionReefers:
    """Estado físico verdadero de los `n` reefers del patio, íntegramente vectorizado.

    Balance térmico de primer orden por contenedor:
        C_termica * dT/dt = Q_ext - Q_frig * compresor_on
        Q_ext = (UA + UA_extra_falla) * (T_amb - T) + carga_puerta + Q_radiacion(si expuesto)
        Q_frig = potencia_frig_efectiva * cop_efectivo

    El control on/off con banda muerta y antirreciclo es idéntico al de un termostato real
    de reefer: no persigue el punto exacto, alterna entre los bordes de la banda.

    # TODO ALUMNO (extensión 2): no se modela condensación/escarchamiento del evaporador.
    # En la realidad, cuando la humedad relativa ambiente es alta (con camanchaca activa,
    # `ambiente.hr_pct` sube sobre 90%) el evaporador escarcha más rápido, el UA efectivo
    # cae con el tiempo entre desescarches y el ciclo de trabajo sube sin que haya ninguna
    # falla programada. Es una buena fuente de "falso positivo" realista para poner a
    # prueba al detector de anomalías de la Fase 2.
    """

    def __init__(self, n: int, rng: np.random.Generator) -> None:
        self.n = n
        self.rng = rng

        self.temp_c = rng.normal(C.REEFER_SETPOINT_C, 0.3, size=n)
        self.setpoint_c = np.full(n, C.REEFER_SETPOINT_C)
        self.compresor_on = rng.random(n) < 0.5
        self.t_en_estado_s = np.zeros(n)
        self.expuesto = rng.random(n) < C.REEFER_PROB_EXPUESTO
        self.carga_puerta_kw = np.zeros(n)

        # Parámetros que las fallas alteran (1.0 / 0.0 = sin falla activa):
        self.ua_extra_wk = np.zeros(n)       # 'puerta mal cerrada'
        self.cop_factor = np.ones(n)         # 'compresor degradado'
        self.potencia_activa = np.ones(n, dtype=bool)  # False = 'desconexión de equipo'
        self.tiempo_encendido_acumulado_s = np.zeros(n)  # para derivar el setpoint tras
                                                            # sostener el ciclo de trabajo alto
        self._sin_suministro_prev = np.zeros(n, dtype=bool)

        self.sensores_temp = [
            SensorInstrumento(ruido_sigma=0.15, resolucion=0.1, rng=rng, id_entidad=i)
            for i in range(n)
        ]

    def _cop(self, delta_t: np.ndarray) -> np.ndarray:
        """COP decrece con el salto térmico (T_amb - T_interior): a mayor diferencia,
        más le cuesta al compresor mover calor. Interpolación lineal entre los extremos
        de catálogo, acotada al rango físico dado."""
        delta_ref_max = C.AMB_TEMP_MAX_C - C.REEFER_SETPOINT_C
        frac = np.clip(delta_t / delta_ref_max, 0.0, 1.0)
        return C.REEFER_COP_MAX - frac * (C.REEFER_COP_MAX - C.REEFER_COP_MIN)

    def paso(self, dt: float, ambiente: "Ambiente", tension_por_reefer_v: np.ndarray) -> np.ndarray:
        """Integra un paso y devuelve la demanda eléctrica [kW] de cada reefer, que la
        red usa para recalcular la tensión del paso siguiente."""
        n = self.n

        # --- aperturas de puerta: evento raro por paso, con recuperación exponencial ---
        self.carga_puerta_kw *= np.exp(-dt / C.REEFER_PUERTA_TAU_S)
        abre_puerta = self.rng.random(n) < C.REEFER_PROB_PUERTA_POR_PASO * dt
        self.carga_puerta_kw[abre_puerta] += C.REEFER_PUERTA_CARGA_KW

        # --- derrateo por tensión: motor mal alimentado rinde menos (lazo de
        #     realimentación tensión -> capacidad -> ciclo -> demanda -> tensión).
        # Ojo con el piso del clip: es el límite del régimen *degradado*, no un mínimo
        # universal. Sin la rama de "sin suministro", un reefer colgando de un alimentador
        # abierto (0 V) seguiría enfriando al 85% y la apertura de protección no dejaría
        # ninguna firma térmica.
        frac_tension_cruda = tension_por_reefer_v / C.TENSION_NOMINAL_V
        sin_suministro = frac_tension_cruda < C.REEFER_TENSION_MIN_OPERACION_FRAC
        frac_tension = np.where(
            sin_suministro, 0.0,
            np.clip(frac_tension_cruda, C.REEFER_TENSION_DERATE_MIN, 1.0),
        )

        # --- carga térmica externa, vía temperatura sol-aire para los contenedores
        #     expuestos. La radiación NO entra como flujo directo al interior: calienta
        #     la piel del contenedor, que a su vez pierde calor por convección al aire.
        #     El efecto neto es que la envolvente "ve" una temperatura exterior más alta
        #     que la del aire. Sumar la irradiancia como kW directos daría cargas de
        #     decenas de kW sobre una caja que solo tiene UA = 30 W/K: absurdo, y le
        #     ganaría por goleada a los 5 kW de potencia frigorífica.
        temp_exterior_efectiva = ambiente.temp_c + np.where(
            self.expuesto, C.REEFER_K_SOL_AIRE_KM2_W * ambiente.rad_wm2, 0.0
        )
        delta_t = temp_exterior_efectiva - self.temp_c
        ua_total_kw = (C.REEFER_UA_WK + self.ua_extra_wk) / 1000.0
        q_ext_kw = ua_total_kw * delta_t + self.carga_puerta_kw

        # --- capacidad frigorífica cuando el compresor está encendido ---
        cop = self._cop(np.abs(delta_t)) * self.cop_factor
        potencia_frig_efectiva = C.REEFER_POTENCIA_FRIG_KW * frac_tension * self.potencia_activa
        q_frig_kw = potencia_frig_efectiva * cop * self.compresor_on

        # --- balance térmico de primer orden ---
        # Unidades: [kW] * [s] = [kJ], dividido por [kJ/K] = [K]. Ojo con esta línea:
        # mezclar W con kJ/K mete un factor 1000 y el contenedor se calienta a °C por
        # segundo en vez de °C por hora.
        dT = (q_ext_kw - q_frig_kw) * dt / C.REEFER_CAPACIDAD_TERMICA_KJ_K
        temp_anterior = self.temp_c.copy()
        self.temp_c = self.temp_c + dT

        # Invariante no negociable: ninguna variable con inercia salta.
        tasa = np.abs(self.temp_c - temp_anterior) / dt
        if np.any(tasa > C.REEFER_TASA_MAX_C_S):
            peor = int(np.argmax(tasa))
            raise AssertionError(
                f"Reefer {peor}: tasa de cambio de temperatura {tasa[peor]:.4f} °C/s "
                f"excede tasa_max={C.REEFER_TASA_MAX_C_S:.4f} °C/s. Revisa la física, "
                f"no relajes la aserción."
            )

        # --- control on/off con banda muerta y antirreciclo ---
        self.t_en_estado_s += dt
        puede_conmutar = self.t_en_estado_s >= C.REEFER_ANTIRRECICLO_S
        debe_encender = (self.temp_c > self.setpoint_c + C.REEFER_BANDA_MUERTA_C) & ~self.compresor_on
        debe_apagar = (self.temp_c < self.setpoint_c - C.REEFER_BANDA_MUERTA_C) & self.compresor_on
        conmuta = puede_conmutar & (debe_encender | debe_apagar)
        self.compresor_on = np.where(conmuta, ~self.compresor_on, self.compresor_on)
        self.t_en_estado_s = np.where(conmuta, 0.0, self.t_en_estado_s)

        # --- corte y restitución de suministro ---
        # Sin tensión el compresor está detenido, punto: dejarlo "encendido" reportaría un
        # equipo funcionando a oscuras. Y al volver la tensión, todos los equipos del grupo
        # que estén sobre consigna arrancan a la vez (los controladores de reefer reponen
        # así tras un corte). Ese arranque en sincronía es el peak de demanda que el
        # enunciado pide ver en la transferencia a generador; en régimen normal los ciclos
        # están desfasados entre sí y ese peak no aparece.
        restablecido = self._sin_suministro_prev & ~sin_suministro
        self.compresor_on = np.where(sin_suministro, False, self.compresor_on)
        self.compresor_on = np.where(restablecido & (self.temp_c > self.setpoint_c),
                                      True, self.compresor_on)
        self.t_en_estado_s = np.where(sin_suministro | restablecido, 0.0, self.t_en_estado_s)
        self._sin_suministro_prev = sin_suministro

        # --- firma de 'compresor degradado': ciclo de trabajo alto y sostenido termina
        #     derivando el setpoint (representa que el operador sube el punto de consigna
        #     para que el equipo alcance a enfriar, un síntoma operativo real) ---
        degradado = self.cop_factor < 1.0
        self.tiempo_encendido_acumulado_s = np.where(
            degradado & self.compresor_on,
            self.tiempo_encendido_acumulado_s + dt,
            self.tiempo_encendido_acumulado_s * (~degradado),  # se resetea si la falla ya pasó
        )
        umbral_s = 2 * 3600.0  # 2 h de ciclo de trabajo sostenido antes de que derive el setpoint
        deriva_setpoint = (self.tiempo_encendido_acumulado_s > umbral_s) & degradado
        self.setpoint_c = np.where(deriva_setpoint, self.setpoint_c + 0.002 * dt, self.setpoint_c)

        # --- demanda eléctrica real de cada reefer ---
        # Un equipo desconectado o sin tensión no consume, aunque su termostato siga
        # pidiendo frío: si no se descuenta aquí, la telemetría reportaría 6 kW en un
        # contenedor que está a oscuras.
        demanda_kw = np.where(
            ~self.potencia_activa | sin_suministro, 0.0,
            np.where(self.compresor_on, C.REEFER_KW_COMPRESOR, C.REEFER_KW_RALENTI),
        )
        return demanda_kw

    def leer_sensores(self, indices: np.ndarray) -> np.ndarray:
        """Lee (con ruido/deriva/pegado) la temperatura de los reefers indicados.
        Se llama solo en los pasos de muestreo (cada `REEFER_MUESTREO_S`), no cada dt."""
        return np.array([self.sensores_temp[i].leer(self.temp_c[i]) for i in indices])


# ---- celda 18 ----
class Faja:
    """Faja transportadora de concentrado. Mantiene su propio estado físico verdadero
    (velocidad, tonelaje en cola y en cabeza, corriente, temperatura de polines) y no
    conoce nada de sensores: eso lo agrega la capa de sensores por separado.
    """

    def __init__(self, rng: np.random.Generator, dt: float = C.DT_S) -> None:
        self.rng = rng
        self.dt = dt
        self.velocidad_ms = 0.0          # velocidad real de la correa
        self.velocidad_motriz_ms = 0.0   # velocidad del tambor motriz (la que manda el variador)
        self.deslizamiento = 0.0         # fracción de patinaje correa/tambor, 0 = agarre total
        self.velocidad_objetivo_ms = 0.0
        self.tonelaje_cola_th = 0.0
        self.tonelaje_cabeza_th = 0.0
        self.corriente_a = C.FAJA_CORRIENTE_VACIO_A
        self.temp_polines_c = 15.0
        self.friccion_factor = 0.0  # 0 = rodamientos sanos, 1 = falla total (falla 'rodamiento')
        self.patinaje_activo = False

        n_retardo = max(1, round(C.FAJA_RETARDO_S / dt))
        self._buffer_cola = deque([0.0] * n_retardo, maxlen=n_retardo)

        self._utilizacion = 0.0  # AR(1) lento: qué tan llena viene la cinta desde el buque

    def paso(self, dt: float, ambiente: "Ambiente", operativa: bool, sobrecarga_activa: bool) -> float:
        """Devuelve la corriente del motor [A], que consume la red de servicios generales
        (no modelada con topología: solo los reefers la tienen, según el enunciado)."""
        vel_anterior = self.velocidad_ms

        # --- utilización de la cinta: cuánto concentrado entrega el buque en este instante ---
        self._utilizacion = 0.9 * self._utilizacion + 0.1 * self.rng.uniform(0.6, 1.0)
        objetivo_carga_frac = self._utilizacion if operativa else 0.0
        if sobrecarga_activa:
            objetivo_carga_frac *= C.FAJA_FACTOR_SOBRECARGA

        self.velocidad_objetivo_ms = C.FAJA_VEL_NOM_MS if operativa else 0.0
        # rampa de aceleración del tambor motriz: la correa cargada no llega a la nominal
        # entre dos muestras
        paso_max = (C.FAJA_VEL_NOM_MS / C.FAJA_RAMPA_S) * dt
        diff = self.velocidad_objetivo_ms - self.velocidad_motriz_ms
        self.velocidad_motriz_ms += np.clip(diff, -paso_max, paso_max)

        # --- patinaje bajo sobrecarga: cae la velocidad y sube la corriente a la vez ---
        # El deslizamiento entra y sale como sistema de primer orden, no como escalón: la
        # correa empieza a resbalar de forma progresiva sobre el tambor.
        self.patinaje_activo = objetivo_carga_frac > C.FAJA_UMBRAL_SOBRECARGA_FRAC
        objetivo_desl = C.FAJA_PATINAJE_CAIDA_VEL_FRAC if self.patinaje_activo else 0.0
        self.deslizamiento += (objetivo_desl - self.deslizamiento) * (dt / C.FAJA_TAU_PATINAJE_S)
        self.velocidad_ms = self.velocidad_motriz_ms * (1.0 - self.deslizamiento)

        # Invariante: la velocidad tampoco puede saltar.
        tasa_vel = abs(self.velocidad_ms - vel_anterior) / dt
        if tasa_vel > C.FAJA_TASA_MAX_VEL_MS_S:
            raise AssertionError(
                f"Faja: tasa de cambio de velocidad {tasa_vel:.3f} m/s/s excede la cota "
                f"física {C.FAJA_TASA_MAX_VEL_MS_S:.3f} m/s/s."
            )

        self.tonelaje_cola_th = C.FAJA_TON_H_PLENA * objetivo_carga_frac * (self.velocidad_ms / C.FAJA_VEL_NOM_MS if C.FAJA_VEL_NOM_MS else 0.0)
        self._buffer_cola.append(self.tonelaje_cola_th)
        self.tonelaje_cabeza_th = self._buffer_cola[0]

        # --- corriente: proporcional al tonelaje instantáneo + fricción en vacío ---
        frac_carga = np.clip(self.tonelaje_cola_th / C.FAJA_TON_H_PLENA, 0.0, 1.3)
        self.corriente_a = C.FAJA_CORRIENTE_VACIO_A + frac_carga * (C.FAJA_CORRIENTE_PLENA_A - C.FAJA_CORRIENTE_VACIO_A)
        if self.patinaje_activo:
            self.corriente_a *= 1.25  # el motor tira más corriente tratando de vencer el patinaje

        # --- temperatura de polines: primer orden forzado por carga + ambiente + fricción ---
        tau_s = C.FAJA_TAU_POLINES_MIN * 60.0
        t_equilibrio = (
            ambiente.temp_c
            + C.FAJA_POLINES_K_CARGA_C * frac_carga
            + C.FAJA_POLINES_K_FRICCION_C * self.friccion_factor
        )
        self.temp_polines_c += (t_equilibrio - self.temp_polines_c) * (dt / tau_s)

        return self.corriente_a


# ---- celda 20 ----
class Grua:
    """Grúa móvil de carga general/contenedores. Máquina de estados con fases
    posicionar -> enganchar -> izar -> girar -> descender -> soltar -> retornar.

    # TODO ALUMNO (extensión 3): la exclusión espacial hoy es una penalización de tiempo
    # fija (`GRUA_INTERFERENCIA_EXTRA_S`) cuando ambas grúas están activas a la vez. Un
    # modelo más fiel dividiría el frente en zonas y bloquearía por completo el avance de
    # una grúa si la otra ocupa la zona de destino (en vez de solo alargar el ciclo),
    # lo que generaría paradas abruptas y no solo ciclos más lentos.
    """

    def __init__(self, id_grua: int, rng: np.random.Generator) -> None:
        self.id = id_grua
        self.rng = rng
        self.fase_idx: Optional[int] = None  # None = detenida (sin nave o viento excesivo)
        self.tiempo_en_fase_s = 0.0
        self.duracion_fase_s = 0.0
        self.movimientos = 0
        self.potencia_kw = 0.0
        self.eventos: list = []  # (t_s, fase_nueva) — para 'un evento por transición de fase'
        self.ciclos_completados_ts: list = []  # instantes en que se cierra un ciclo completo
                                                  # (evento de throughput, distinto del de fase)

    def _sortear_duracion_fase(self, interferencia: bool) -> float:
        # El ciclo completo (7 fases) debe promediar GRUA_CICLO_MED_S; cada fase se lleva
        # una fracción de ese total, todas con la misma forma lognormal relativa.
        media_fase = C.GRUA_CICLO_MED_S / len(C.GRUA_FASES)
        mu = np.log(media_fase) - 0.5 * C.GRUA_CICLO_SIGMA ** 2
        dur = self.rng.lognormal(mu, C.GRUA_CICLO_SIGMA)
        if interferencia:
            dur += C.GRUA_INTERFERENCIA_EXTRA_S / len(C.GRUA_FASES)
        return dur

    def _potencia_de_fase(self, nombre_fase: str) -> float:
        if nombre_fase == "izar":
            return C.GRUA_POT_IZAR_KW
        if nombre_fase == "descender":
            return C.GRUA_POT_DESCENSO_KW
        return C.GRUA_POT_OTRAS_KW

    def paso(self, dt: float, t_s: float, puede_operar: bool, interferencia: bool) -> None:
        """`puede_operar` ya incorpora nave en sitio + límite de viento (lo decide el
        Simulador, que es quien conoce el estado del Ambiente y del Buque)."""
        if not puede_operar:
            if self.fase_idx is not None:
                self.fase_idx = None
                self.potencia_kw = 0.0
                self.eventos.append((t_s, "detenida"))
            return

        if self.fase_idx is None:
            self.fase_idx = 0
            self.tiempo_en_fase_s = 0.0
            self.duracion_fase_s = self._sortear_duracion_fase(interferencia)
            self.potencia_kw = self._potencia_de_fase(C.GRUA_FASES[self.fase_idx])
            self.eventos.append((t_s, C.GRUA_FASES[self.fase_idx]))
            return

        self.tiempo_en_fase_s += dt
        if self.tiempo_en_fase_s >= self.duracion_fase_s:
            self.tiempo_en_fase_s = 0.0
            self.fase_idx = (self.fase_idx + 1) % len(C.GRUA_FASES)
            if self.fase_idx == 0:
                self.movimientos += 1
                self.ciclos_completados_ts.append(t_s)
            self.duracion_fase_s = self._sortear_duracion_fase(interferencia)
            self.potencia_kw = self._potencia_de_fase(C.GRUA_FASES[self.fase_idx])
            self.eventos.append((t_s, C.GRUA_FASES[self.fase_idx]))

    @property
    def activa(self) -> bool:
        return self.fase_idx is not None


# ---- celda 22 ----
class Bascula:
    """Báscula de acceso vehicular con cola M(t)/G/1 (llegadas de Poisson no homogéneo,
    servicio de duración variable, un solo tablero de pesaje).
    """

    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng
        self.cola: list = []  # cargas [t] ya comprometidas de los vehículos en espera
        self.en_servicio = False
        self.servicio_fin_t = 0.0
        self.tara_t = 0.0
        self.bruto_t = 0.0
        self.carga_en_servicio_t = 0.0
        self.asentamiento_dur_s = 0.0
        self._proximas_muestras_asentamiento: list = []  # (t_s, valor) pendientes de emitir

        self.generado_acumulado_t = 0.0    # tonelaje que faja + grúas han producido
        self.cubierto_acumulado_t = 0.0    # tonelaje ya pesado y retirado
        self.comprometido_t = 0.0          # tonelaje asignado a camiones aún sin pesar
        self._ultimo_muestreo_cola_t = -np.inf
        self._contador_vehiculos = 0

    @property
    def pendiente_t(self) -> float:
        """Material producido que todavía no tiene camión asignado. Es lo que gobierna el
        despacho: descontar lo ya comprometido evita mandar el doble de camiones de los
        necesarios mientras los primeros hacen fila."""
        return self.generado_acumulado_t - self.cubierto_acumulado_t - self.comprometido_t

    @staticmethod
    def _modulacion_turno(hora: float) -> float:
        """Ritmo de los turnos sobre el despacho: peaks de 1 h en cada cambio de turno
        (00:00, 08:00, 16:00) sobre un valle base."""
        bajo, alto = C.BASCULA_MODULACION_TURNO
        factor = bajo
        for inicio_turno in C.TURNOS_INICIO_H:
            dist = min(abs(hora - inicio_turno), 24.0 - abs(hora - inicio_turno))
            if dist < 1.0:
                factor = max(factor, bajo + (1.0 - dist) * (alto - bajo))
        return factor

    def registrar_generacion(self, delta_toneladas: float) -> None:
        """Faja y grúas reportan aquí, paso a paso, cuánto tonelaje van moviendo."""
        self.generado_acumulado_t += delta_toneladas

    def _curva_asentamiento(self, bruto: float) -> list:
        """Oscilación amortiguada de la celda de carga al recibir el peso del vehículo:
        sobrepico inicial que decae hacia el valor firme. Muestreada a alta frecuencia
        para que, en Fase 2, se vea la curva de asentamiento y no un escalón instantáneo."""
        n_muestras = max(1, int(self.asentamiento_dur_s * C.BASCULA_HZ_ASENTAMIENTO))
        zeta = 3.0 / self.asentamiento_dur_s
        omega = 2 * np.pi * 2.0 / self.asentamiento_dur_s
        muestras = []
        for k in range(n_muestras):
            tau = k / C.BASCULA_HZ_ASENTAMIENTO
            valor = bruto + bruto * 0.08 * np.exp(-zeta * tau) * np.cos(omega * tau)
            muestras.append((tau, valor))
        return muestras

    def paso(self, t_s: float, dt: float, hora: float) -> list:
        """Devuelve una lista de filas (dict) listas para telemetría, generadas en este paso."""
        filas = []

        # --- despacho de camiones: Poisson no homogéneo cuya tasa la fija el material
        #     pendiente de retirar, modulada por el ritmo de los turnos ---
        pendiente = self.pendiente_t
        if pendiente > C.BASCULA_CARGA_MIN_T:
            tasa_h = min(C.BASCULA_K_DESPACHO_VEH_H_POR_T * pendiente,
                          C.BASCULA_TASA_MAX_VEH_H) * self._modulacion_turno(hora)
            if self.rng.random() < (tasa_h / 3600.0) * dt:
                # La carga máxima sale de la restricción de bruto: tara máxima + carga
                # no puede pasar del bruto máximo permitido en el portón.
                carga = float(np.clip(pendiente, C.BASCULA_CARGA_MIN_T,
                                       C.BASCULA_BRUTO_MAX_T - C.BASCULA_TARA_MAX_T))
                self.cola.append(carga)
                self.comprometido_t += carga

        # --- muestras de asentamiento pendientes de un pesaje en curso ---
        while self._proximas_muestras_asentamiento and self._proximas_muestras_asentamiento[0][0] <= t_s:
            _, valor = self._proximas_muestras_asentamiento.pop(0)
            filas.append(dict(entidad_id="bascula_1", entidad_tipo="bascula",
                               variable="peso_bruto_kg", valor=valor * 1000.0, unidad="kg",
                               calidad_sensor="asentamiento"))

        # --- fin de servicio ---
        if self.en_servicio and t_s >= self.servicio_fin_t:
            neto_t = self.bruto_t - self.tara_t
            self.cubierto_acumulado_t += neto_t
            self.comprometido_t -= self.carga_en_servicio_t
            filas.append(dict(entidad_id="bascula_1", entidad_tipo="bascula",
                               variable="peso_neto_t", valor=neto_t, unidad="t",
                               calidad_sensor="ok"))
            self.en_servicio = False

        # --- inicio de servicio si hay cola y el tablero está libre ---
        if not self.en_servicio and self.cola:
            self.carga_en_servicio_t = self.cola.pop(0)
            self._contador_vehiculos += 1
            self.tara_t = self.rng.uniform(C.BASCULA_TARA_MIN_T, C.BASCULA_TARA_MAX_T)
            # El bruto es tara + la carga que este camión venía a retirar, más la
            # variación real de llenado (±50 kg): el balance de masa cierra por física,
            # pero no de forma exacta hasta el último kilo.
            self.bruto_t = min(self.tara_t + self.carga_en_servicio_t + self.rng.normal(0.0, 0.05),
                                C.BASCULA_BRUTO_MAX_T)
            tiempo_total_s = self.rng.uniform(*C.BASCULA_TIEMPO_TOTAL_S)
            self.asentamiento_dur_s = self.rng.uniform(*C.BASCULA_ASENTAMIENTO_S)
            self.en_servicio = True
            self.servicio_fin_t = t_s + tiempo_total_s
            self._proximas_muestras_asentamiento = [
                (t_s + tau, valor) for tau, valor in self._curva_asentamiento(self.bruto_t)
            ]

        # --- heartbeat de la cola: la cola es estado, se registra a intervalo fijo ---
        if t_s - self._ultimo_muestreo_cola_t >= C.BASCULA_MUESTREO_COLA_S:
            self._ultimo_muestreo_cola_t = t_s
            filas.append(dict(entidad_id="bascula_1", entidad_tipo="bascula",
                               variable="cola_vehiculos", valor=float(len(self.cola)),
                               unidad="veh", calidad_sensor="ok"))

        return filas


# ---- celda 24 ----
class BuqueYTurnos:
    """Genera las ventanas de atraque de toda la corrida y expone, paso a paso, si hay
    nave en sitio y si el sitio está en una caída de productividad por cambio de turno.

    # TODO ALUMNO (extensión 4): este modelo asume un único frente de atraque. Si quieres
    # simular un segundo sitio (p. ej. Sitio 4 del mismo terminal), la forma más limpia es
    # instanciar una segunda `BuqueYTurnos` + su propia `Faja`/`Grua` con ventanas de
    # atraque independientes, y agregar una restricción de recursos compartidos si ambos
    # sitios usan la misma dotación de grúas o el mismo alimentador de respaldo.
    """

    def __init__(self, rng: np.random.Generator, horizonte_s: float) -> None:
        self.rng = rng
        self.ventanas_atraque: list = []
        t_cursor = rng.uniform(0.01, 0.05) * horizonte_s  # la primera nave no llega en t=0
        n_naves = rng.integers(*C.BUQUE_N_VENTANAS_RANGO, endpoint=True)
        for _ in range(n_naves):
            duracion_s = rng.uniform(*C.BUQUE_DURACION_FRAC_RANGO) * horizonte_s
            if t_cursor >= horizonte_s:
                break
            fin_s = min(t_cursor + duracion_s, horizonte_s)
            self.ventanas_atraque.append((t_cursor, fin_s))
            t_cursor = fin_s + rng.uniform(*C.BUQUE_GAP_FRAC_RANGO) * horizonte_s

        self.nave_en_sitio = False
        self.en_cambio_turno = False
        self.turno_actual = 0
        self._caida_turno_s = {h: rng.uniform(*C.CAMBIO_TURNO_CAIDA_MIN) * 60.0 for h in C.TURNOS_INICIO_H}

    def paso(self, t_s: float, hora: float) -> None:
        self.nave_en_sitio = any(ini <= t_s < fin for ini, fin in self.ventanas_atraque)

        # turno vigente: el que tenga el inicio más cercano por debajo de la hora actual
        self.turno_actual = max(i for i, h in enumerate(C.TURNOS_INICIO_H) if h <= hora)

        self.en_cambio_turno = False
        for h in C.TURNOS_INICIO_H:
            minutos_desde_inicio = (hora - h) * 60.0
            if 0.0 <= minutos_desde_inicio < self._caida_turno_s[h] / 60.0:
                self.en_cambio_turno = True


# ---- celda 26 ----
class F:
    """Parámetros del escenario de fallas: cuántas, de qué magnitud, cuánto duran. A
    diferencia de `C` (física de la planta), esto describe el guion de la corrida y es
    lo primero que un docente querría variar entre secciones de un mismo curso."""

    # Fracción de la ventana en la que la rampa alcanza su magnitud máxima; después se
    # mantiene. Ver _actualizar_rampa.
    FRACCION_RAMPA = 0.5

    DURACION_COMPRESOR_H = (6.0, 18.0)
    MAGNITUD_COMPRESOR_FRAC = (0.35, 0.6)    # caída de COP relativa al valor sano

    DURACION_PUERTA_H = (3.0, 10.0)
    # UA extra sostenida mientras el sello falla. La carga se vuelve UA_total * dT; con
    # dT ~ 45 K y una potencia frigorífica útil de ~6.8 kW, el equipo deja de dar abasto
    # sobre unos 150 W/K totales. Por eso el rango llega hasta 220: en los casos severos
    # la temperatura se estabiliza *sobre* el setpoint con el compresor permanentemente
    # en marcha (la firma del enunciado), y en los leves solo sube el ciclo de trabajo.
    MAGNITUD_PUERTA_UA_WK = (60.0, 220.0)

    DURACION_DESCONEXION_H = (1.0, 4.0)

    # Duración de la apertura de protección. No son 5 minutos: un disparo que deja un
    # alimentador sin tensión exige que alguien vaya, revise y reponga. Además, con
    # UA = 30 W/K la caja sube ~1.3 °C/h, así que un corte corto produce una rampa de
    # décimas de grado — invisible dentro de la banda muerta de ±0.5 °C del control.
    # Con 30-120 min la subida es de 0.7 a 2.6 °C y la firma correlacionada del grupo
    # se distingue sin ambigüedad, que es justamente lo que la Fase 2 debe aprender.
    DURACION_ALIMENTADOR_MIN = (30.0, 120.0)

    DURACION_TRANSFERENCIA_S = C.TRANSFERENCIA_GENERADOR_S

    DURACION_RODAMIENTO_H = (10.0, 30.0)      # una rampa de horas, nunca un salto
    MAGNITUD_RODAMIENTO_FRAC = (0.6, 1.0)     # fracción de fricción máxima alcanzada

    DURACION_SOBRECARGA_MIN = (20.0, 60.0)

    DURACION_SENSOR_PEGADO_H = (2.0, 8.0)

    DURACION_DERIVA_SENSOR_H = (8.0, 24.0)
    MAGNITUD_DERIVA_C_H = (0.15, 0.4)          # °C/h de offset creciente


@dataclass
class EventoFalla:
    falla_id: str
    tipo_falla: str
    entidad_afectada: str
    alimentador_afectado: Optional[int]
    t_inicio: float
    t_fin: float
    parametro_alterado: str
    magnitud: float
    severidad: str
    _aplicada: bool = False
    _extra: dict = field(default_factory=dict)


def _severidad(frac: float) -> str:
    if frac < 0.35:
        return "leve"
    if frac < 0.7:
        return "moderada"
    return "severa"


class InyectorFallas:
    """Programa el cronograma de fallas y aplica/revierte sus efectos paso a paso sobre
    las entidades reales. No escribe telemetría: solo altera parámetros físicos."""

    def __init__(self, reefers: "PoblacionReefers", red: "RedElectrica", faja: "Faja",
                 horizonte_s: float, rng: np.random.Generator,
                 ventanas_atraque: Optional[list] = None) -> None:
        self.reefers = reefers
        self.red = red
        self.faja = faja
        self.rng = rng
        self.ventanas_atraque = ventanas_atraque or []
        self.sobrecarga_faja_activa = False
        self._contador = 0
        self.eventos: list[EventoFalla] = []

        # En una corrida corta de humo (horizonte pequeño) un margen fijo de 2 h puede
        # comerse todo el horizonte; se escala hacia abajo para que _t_inicio_aleatorio
        # siempre tenga un rango válido, incluso si eso significa fallas que no alcanzan
        # a completarse dentro de la ventana de prueba.
        margen = min(2 * 3600.0, max(1.0, horizonte_s * 0.05))
        self._programar_compresor_degradado(horizonte_s, margen)
        self._programar_puerta_mal_cerrada(horizonte_s, margen)
        self._programar_desconexion(horizonte_s, margen)
        self._programar_apertura_alimentador(horizonte_s, margen)
        self._programar_transferencia_generador(horizonte_s, margen)
        self._programar_rodamiento_faja(horizonte_s, margen)
        self._programar_sobrecarga_faja(horizonte_s, margen)
        self._programar_sensor_pegado(horizonte_s, margen)
        self._programar_deriva_sensor(horizonte_s, margen)
        self.eventos.sort(key=lambda e: e.t_inicio)

    def _nuevo_id(self) -> str:
        self._contador += 1
        return f"F{self._contador:03d}"

    def _t_inicio_aleatorio(self, horizonte_s: float, margen: float, duracion_s: float) -> float:
        low, high = margen, horizonte_s - margen - duracion_s
        if high <= low:
            # Horizonte demasiado corto para esta duración de falla (típico de la corrida
            # de prueba): se relaja el margen en vez de reventar con un rango inválido.
            return self.rng.uniform(0.0, max(1.0, horizonte_s * 0.5))
        return self.rng.uniform(low, high)

    def _t_inicio_en_operacion(self, horizonte_s: float, margen: float, duracion_s: float) -> float:
        """Programa la falla dentro de una ventana de atraque. Una falla de faja que cae
        en un hueco sin nave ocurre con la correa detenida: queda etiquetada en la verdad
        de terreno pero no deja ni un dato anómalo en la telemetría. Para la Fase 2 eso no
        es una anomalía difícil, es un falso negativo imposible de acertar."""
        if not self.ventanas_atraque:
            return self._t_inicio_aleatorio(horizonte_s, margen, duracion_s)
        ini, fin = self.ventanas_atraque[int(self.rng.integers(len(self.ventanas_atraque)))]
        # Se exige que al menos ~70% de la falla caiga dentro de la ventana de operación.
        tope = max(ini, fin - duracion_s * 0.7)
        return float(self.rng.uniform(ini, tope)) if tope > ini else float(ini)

    # --- programación de cada tipo -------------------------------------------------
    def _programar_compresor_degradado(self, horizonte_s, margen):
        i = int(self.rng.integers(0, self.reefers.n))
        dur = self.rng.uniform(*F.DURACION_COMPRESOR_H) * 3600.0
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        mag = self.rng.uniform(*F.MAGNITUD_COMPRESOR_FRAC)
        self.eventos.append(EventoFalla(self._nuevo_id(), "compresor_degradado", f"reefer_{i}",
                                         None, t0, t0 + dur, "cop_factor", mag, _severidad(mag),
                                         _extra={"reefer_idx": i}))

    def _programar_puerta_mal_cerrada(self, horizonte_s, margen):
        i = int(self.rng.integers(0, self.reefers.n))
        dur = self.rng.uniform(*F.DURACION_PUERTA_H) * 3600.0
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        mag = self.rng.uniform(*F.MAGNITUD_PUERTA_UA_WK)
        frac = (mag - F.MAGNITUD_PUERTA_UA_WK[0]) / (F.MAGNITUD_PUERTA_UA_WK[1] - F.MAGNITUD_PUERTA_UA_WK[0])
        self.eventos.append(EventoFalla(self._nuevo_id(), "puerta_mal_cerrada", f"reefer_{i}",
                                         None, t0, t0 + dur, "ua_extra_wk", mag, _severidad(frac),
                                         _extra={"reefer_idx": i}))

    def _programar_desconexion(self, horizonte_s, margen):
        i = int(self.rng.integers(0, self.reefers.n))
        dur = self.rng.uniform(*F.DURACION_DESCONEXION_H) * 3600.0
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        self.eventos.append(EventoFalla(self._nuevo_id(), "desconexion_equipo", f"reefer_{i}",
                                         None, t0, t0 + dur, "potencia_activa", 1.0, "severa",
                                         _extra={"reefer_idx": i}))

    def _programar_apertura_alimentador(self, horizonte_s, margen):
        alim_id = int(self.rng.integers(0, C.N_ALIMENTADORES))
        dur = self.rng.uniform(*F.DURACION_ALIMENTADOR_MIN) * 60.0
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        self.eventos.append(EventoFalla(self._nuevo_id(), "apertura_alimentador",
                                         f"alimentador_{alim_id}", alim_id, t0, t0 + dur,
                                         "energizado", 1.0, "severa"))

    def _programar_transferencia_generador(self, horizonte_s, margen):
        alim_id = int(self.rng.integers(0, C.N_ALIMENTADORES))
        dur = self.rng.uniform(*F.DURACION_TRANSFERENCIA_S)
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        self.eventos.append(EventoFalla(self._nuevo_id(), "transferencia_generador",
                                         f"alimentador_{alim_id}", alim_id, t0, t0 + dur,
                                         "energizado", 1.0, "moderada"))

    def _programar_rodamiento_faja(self, horizonte_s, margen):
        dur = self.rng.uniform(*F.DURACION_RODAMIENTO_H) * 3600.0
        t0 = self._t_inicio_en_operacion(horizonte_s, margen, dur)
        mag = self.rng.uniform(*F.MAGNITUD_RODAMIENTO_FRAC)
        self.eventos.append(EventoFalla(self._nuevo_id(), "rodamiento_faja", "faja_1", None,
                                         t0, t0 + dur, "friccion_factor", mag, _severidad(mag)))

    def _programar_sobrecarga_faja(self, horizonte_s, margen):
        dur = self.rng.uniform(*F.DURACION_SOBRECARGA_MIN) * 60.0
        t0 = self._t_inicio_en_operacion(horizonte_s, margen, dur)
        self.eventos.append(EventoFalla(self._nuevo_id(), "sobrecarga_faja", "faja_1", None,
                                         t0, t0 + dur, "carga_objetivo_frac",
                                         C.FAJA_UMBRAL_SOBRECARGA_FRAC, "moderada"))

    def _programar_sensor_pegado(self, horizonte_s, margen):
        i = int(self.rng.integers(0, self.reefers.n))
        dur = self.rng.uniform(*F.DURACION_SENSOR_PEGADO_H) * 3600.0
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        self.eventos.append(EventoFalla(self._nuevo_id(), "sensor_pegado", f"reefer_{i}", None,
                                         t0, t0 + dur, "sensor_temperatura", 1.0, "moderada",
                                         _extra={"reefer_idx": i}))

    def _programar_deriva_sensor(self, horizonte_s, margen):
        i = int(self.rng.integers(0, self.reefers.n))
        dur = self.rng.uniform(*F.DURACION_DERIVA_SENSOR_H) * 3600.0
        t0 = self._t_inicio_aleatorio(horizonte_s, margen, dur)
        mag_h = self.rng.uniform(*F.MAGNITUD_DERIVA_C_H)
        frac = (mag_h - F.MAGNITUD_DERIVA_C_H[0]) / (F.MAGNITUD_DERIVA_C_H[1] - F.MAGNITUD_DERIVA_C_H[0])
        self.eventos.append(EventoFalla(self._nuevo_id(), "deriva_sensor", f"reefer_{i}", None,
                                         t0, t0 + dur, "sensor_temperatura", mag_h, _severidad(frac),
                                         _extra={"reefer_idx": i}))

    # --- aplicación paso a paso -------------------------------------------------------
    def paso(self, t_s: float, dt: float) -> None:
        self.sobrecarga_faja_activa = False
        for ev in self.eventos:
            activa = ev.t_inicio <= t_s < ev.t_fin
            if activa and not ev._aplicada:
                self._activar(ev)
                ev._aplicada = True
            elif not activa and ev._aplicada:
                self._revertir(ev)
                ev._aplicada = False

            if ev._aplicada:
                self._actualizar_rampa(ev, t_s, dt)

    def _activar(self, ev: EventoFalla) -> None:
        if ev.tipo_falla == "puerta_mal_cerrada":
            self.reefers.ua_extra_wk[ev._extra["reefer_idx"]] = ev.magnitud
        elif ev.tipo_falla == "desconexion_equipo":
            self.reefers.potencia_activa[ev._extra["reefer_idx"]] = False
        elif ev.tipo_falla in ("apertura_alimentador", "transferencia_generador"):
            self.red.abrir_proteccion(ev.alimentador_afectado)
        elif ev.tipo_falla == "sensor_pegado":
            i = ev._extra["reefer_idx"]
            self.reefers.sensores_temp[i].pegar(self.reefers.temp_c[i])
        elif ev.tipo_falla == "deriva_sensor":
            i = ev._extra["reefer_idx"]
            self.reefers.sensores_temp[i].deriva_tasa = ev.magnitud / 3600.0  # °C/h -> °C/s
        elif ev.tipo_falla == "sobrecarga_faja":
            pass  # se maneja como flag continuo en _actualizar_rampa

    def _actualizar_rampa(self, ev: EventoFalla, t_s: float, dt: float) -> None:
        duracion = max(ev.t_fin - ev.t_inicio, 1.0)
        avance = np.clip((t_s - ev.t_inicio) / duracion, 0.0, 1.0)
        # La degradación progresa y después se estanca. Si la rampa recién alcanzara su
        # magnitud máxima en el último instante, la firma quedaría concentrada al final y
        # el promedio de la ventana casi no se movería respecto al estado sano.
        avance_saturado = np.clip(avance / F.FRACCION_RAMPA, 0.0, 1.0)

        if ev.tipo_falla == "compresor_degradado":
            i = ev._extra["reefer_idx"]
            self.reefers.cop_factor[i] = 1.0 - avance_saturado * ev.magnitud
        elif ev.tipo_falla == "rodamiento_faja":
            self.faja.friccion_factor = avance_saturado * ev.magnitud
        elif ev.tipo_falla == "sobrecarga_faja":
            self.sobrecarga_faja_activa = True
        elif ev.tipo_falla == "deriva_sensor":
            # La deriva se acumula en el instrumento: hay que hacerla avanzar en cada
            # paso mientras la falla esté activa, o el offset se queda en cero y la
            # falla no deja ninguna huella en la telemetría.
            self.reefers.sensores_temp[ev._extra["reefer_idx"]].avanzar_deriva(dt)

    def _revertir(self, ev: EventoFalla) -> None:
        if ev.tipo_falla == "compresor_degradado":
            self.reefers.cop_factor[ev._extra["reefer_idx"]] = 1.0
            self.reefers.tiempo_encendido_acumulado_s[ev._extra["reefer_idx"]] = 0.0
        elif ev.tipo_falla == "puerta_mal_cerrada":
            self.reefers.ua_extra_wk[ev._extra["reefer_idx"]] = 0.0
        elif ev.tipo_falla == "desconexion_equipo":
            self.reefers.potencia_activa[ev._extra["reefer_idx"]] = True
        elif ev.tipo_falla in ("apertura_alimentador", "transferencia_generador"):
            self.red.cerrar_proteccion(ev.alimentador_afectado)
        elif ev.tipo_falla == "sensor_pegado":
            self.reefers.sensores_temp[ev._extra["reefer_idx"]].despegar()
        elif ev.tipo_falla == "deriva_sensor":
            i = ev._extra["reefer_idx"]
            self.reefers.sensores_temp[i].deriva_tasa = 0.0
            self.reefers.sensores_temp[i].deriva_actual = 0.0
        elif ev.tipo_falla == "rodamiento_faja":
            self.faja.friccion_factor = 0.0

    def obtener_verdad_terreno(self, inicio_utc: datetime) -> pd.DataFrame:
        filas = [dict(
            falla_id=ev.falla_id,
            tipo_falla=ev.tipo_falla,
            entidad_afectada=ev.entidad_afectada,
            alimentador_afectado=ev.alimentador_afectado,
            t_inicio=inicio_utc + timedelta(seconds=ev.t_inicio),
            t_fin=inicio_utc + timedelta(seconds=ev.t_fin),
            parametro_alterado=ev.parametro_alterado,
            magnitud=ev.magnitud,
            severidad=ev.severidad,
        ) for ev in self.eventos]
        return pd.DataFrame(filas)


# ---- celda 28 ----
class Simulador:
    """Orquesta la corrida completa y acumula la telemetría en memoria."""

    def __init__(self, horas: float, n_reefers: int, rng: np.random.Generator,
                 inicio_utc: Optional[datetime] = None) -> None:
        self.horas = horas
        self.n_reefers = n_reefers
        self.rng = rng
        self.horizonte_s = horas * 3600.0

        self.reloj = Reloj(inicio_utc or datetime(2026, 1, 12, tzinfo=timezone.utc), C.DT_S)
        self.ambiente = Ambiente(self.reloj, rng)

        n_alim = max(1, min(C.N_ALIMENTADORES, n_reefers))
        self.red = RedElectrica(n_reefers=n_reefers, n_alimentadores=n_alim)
        self.reefers = PoblacionReefers(n_reefers, rng)
        self.faja = Faja(rng, dt=C.DT_S)
        self.gruas = [Grua(0, rng), Grua(1, rng)]
        self.bascula = Bascula(rng)
        self.buque = BuqueYTurnos(rng, horizonte_s=self.horizonte_s)
        # El inyector recibe las ventanas de atraque para poder programar las fallas de
        # faja dentro de un período con nave en sitio (ver _t_inicio_en_operacion).
        self.inyector = InyectorFallas(self.reefers, self.red, self.faja, self.horizonte_s,
                                        rng, ventanas_atraque=self.buque.ventanas_atraque)

        # La telemetría se acumula como lista de dicts y se vuelca a DataFrame cada
        # FILAS_POR_CHUNK filas. Con 7 días y 100 reefers son millones de filas: mantener
        # todo como dicts de Python cuesta del orden de gigabytes (cada dict pesa cientos
        # de bytes), mientras que en columnas de pandas son decenas de MB.
        self.telemetria: list = []
        self._chunks: list = []
        self._filas_totales = 0
        self.FILAS_POR_CHUNK = 400_000
        self._ultimo_muestreo_reefer_s = -np.inf
        self._suspension_viento = False
        self._t_ultimo_viento_alto = -np.inf
        self._nave_previa: Optional[bool] = None
        self._suspension_previa: Optional[bool] = None
        self.masa_faja_por_dia_t: dict = {}
        self.masa_grua_por_dia_t: dict = {}
        self.masa_bascula_por_dia_t: dict = {}

    def _registrar(self, entidad_id: str, entidad_tipo: str, variable: str, valor: float,
                    unidad: str, calidad_sensor: str = "ok", alimentador_id: Optional[int] = None) -> None:
        """`valor` es siempre numérico: las variables categóricas (la fase de la grúa) se
        registran como código entero, con el diccionario en C.GRUA_FASES. Mezclar texto y
        números en la misma columna la degrada a tipo objeto y multiplica el tamaño del
        Parquet por varias veces."""
        self.telemetria.append(dict(
            timestamp_utc=self.reloj.timestamp_utc, entidad_id=entidad_id,
            entidad_tipo=entidad_tipo, alimentador_id=alimentador_id, variable=variable,
            valor=float(valor), unidad=unidad, calidad_sensor=calidad_sensor,
        ))

    def _volcar_chunk(self) -> None:
        """Convierte lo acumulado a un DataFrame y libera la lista de dicts."""
        if not self.telemetria:
            return
        self._chunks.append(pd.DataFrame(self.telemetria))
        self._filas_totales += len(self.telemetria)
        self.telemetria = []

    def correr(self, progreso_cada_h: float = 12.0) -> None:
        n_pasos = int(round(self.horizonte_s / C.DT_S))
        indices_reefer = np.arange(self.n_reefers)
        proximo_reporte_s = 0.0

        for _ in range(n_pasos):
            t_s = self.reloj.t_s
            hora = self.reloj.hora_decimal
            dia = self.reloj.dia

            self.ambiente.paso(C.DT_S)
            self.buque.paso(t_s, hora)
            self.inyector.paso(t_s, C.DT_S)

            # La tensión que "ve" cada reefer en este paso es la calculada en el paso
            # anterior: rompe la circularidad tensión -> potencia -> demanda -> tensión
            # dentro de un mismo instante (retardo de un paso, técnica estándar en
            # simulación de paso fijo con lazos algebraicos).
            tension_previa = self.red.tension_por_reefer_v.copy()
            demanda_kw = self.reefers.paso(C.DT_S, self.ambiente, tension_previa)
            self.red.paso(demanda_kw)

            # --- suspensión por viento, con histéresis y stand-down ---
            # Una vez suspendida la operación, no se reanuda apenas el viento baje del
            # límite: tiene que bajar de la banda de rearme y mantenerse ahí el tiempo
            # mínimo. Suspende el frente completo, así que faja y grúas quedan con huecos
            # correlacionados en el mismo instante.
            if self.ambiente.viento_ms > C.GRUA_VIENTO_LIMITE_MS:
                self._suspension_viento = True
                self._t_ultimo_viento_alto = t_s
            elif self._suspension_viento:
                calmado = self.ambiente.viento_ms < C.GRUA_VIENTO_REARME_MS
                esperado = (t_s - self._t_ultimo_viento_alto) >= C.GRUA_STANDDOWN_MIN * 60.0
                if calmado and esperado:
                    self._suspension_viento = False

            nave_en_sitio = self.buque.nave_en_sitio
            frente_operativo = nave_en_sitio and not self._suspension_viento
            puede_operar_grua = frente_operativo

            # Los estados discretos se registran por CAMBIO, además del heartbeat de 60 s.
            # Si solo se registraran cada 60 s, una grúa que arranca en el segundo exacto
            # en que atraca la nave aparecería —en el propio archivo de salida— operando
            # "sin nave", porque la última muestra disponible sería anterior al atraque.
            # Es logging por cambio de estado, que es como se instrumentan estas señales.
            if nave_en_sitio != self._nave_previa:
                self._registrar("buque_1", "buque", "nave_en_sitio", float(nave_en_sitio), "bool")
                self._nave_previa = nave_en_sitio
            if self._suspension_viento != self._suspension_previa:
                self._registrar("sitio_3", "operacion", "suspension_viento",
                                 float(self._suspension_viento), "bool")
                self._suspension_previa = self._suspension_viento

            interferencia = self.gruas[0].activa and self.gruas[1].activa
            tonelaje_grua_t = 0.0
            for g in self.gruas:
                g.paso(C.DT_S, t_s, puede_operar_grua, interferencia)
                assert not g.activa or puede_operar_grua, (
                    "Invariante violado: grúa activa sin nave en sitio o con viento sobre "
                    f"el límite operacional ({self.ambiente.viento_ms:.1f} m/s)."
                )
                # La grúa se registra por evento, no por tick (el enunciado pide "un evento
                # por transición de fase"): la potencia es constante dentro de cada fase,
                # así que registrarla en la transición basta para reconstruir el perfil
                # completo, y evita más de un millón de filas redundantes en la corrida larga.
                while g.eventos:
                    _, fase = g.eventos.pop(0)
                    codigo = -1.0 if fase == "detenida" else float(C.GRUA_FASES.index(fase))
                    self._registrar(f"grua_{g.id}", "grua", "fase_actual", codigo, "codigo_fase")
                    self._registrar(f"grua_{g.id}", "grua", "potencia_kw", g.potencia_kw, "kW")
                while g.ciclos_completados_ts:
                    g.ciclos_completados_ts.pop(0)
                    tonelaje_grua_t += C.CARGA_PROMEDIO_GRUA_T
                    self._registrar(f"grua_{g.id}", "grua", "carga_movida_t",
                                     C.CARGA_PROMEDIO_GRUA_T, "t")

            vel_faja_previa = self.faja.velocidad_ms
            corriente_faja = self.faja.paso(C.DT_S, self.ambiente, frente_operativo,
                                             self.inyector.sobrecarga_faja_activa)
            # Sin nave, la faja no puede estar *accionada*. Ojo: no se le puede exigir
            # velocidad cero instantánea, porque tarda FAJA_RAMPA_S en frenar — esa es
            # justamente la inercia que el ejercicio quiere. Lo que sí debe cumplirse es
            # que la consigna sea cero y que la velocidad solo pueda ir bajando.
            if not nave_en_sitio:
                assert self.faja.velocidad_objetivo_ms == 0.0, (
                    "Invariante violado: faja con consigna de marcha sin nave en sitio."
                )
                assert self.faja.velocidad_ms <= vel_faja_previa + 1e-9, (
                    f"Invariante violado: la faja acelera sin nave en sitio "
                    f"({vel_faja_previa:.3f} -> {self.faja.velocidad_ms:.3f} m/s)."
                )
            self._registrar("faja_1", "faja", "velocidad_ms", self.faja.velocidad_ms, "m/s")
            self._registrar("faja_1", "faja", "corriente_a", corriente_faja, "A")
            self._registrar("faja_1", "faja", "temperatura_polines_c", self.faja.temp_polines_c, "C")
            self._registrar("faja_1", "faja", "tonelaje_cola_th", self.faja.tonelaje_cola_th, "t/h")
            self._registrar("faja_1", "faja", "tonelaje_cabeza_th", self.faja.tonelaje_cabeza_th, "t/h")

            # --- acoplamiento de masa: lo que faja y grúas mueven alimenta la demanda
            #     de camiones que la báscula debe cubrir en el mismo día ---
            tonelaje_faja_t = self.faja.tonelaje_cabeza_th * (C.DT_S / 3600.0)
            self.bascula.registrar_generacion(tonelaje_faja_t + tonelaje_grua_t)
            self.masa_faja_por_dia_t[dia] = self.masa_faja_por_dia_t.get(dia, 0.0) + tonelaje_faja_t
            self.masa_grua_por_dia_t[dia] = self.masa_grua_por_dia_t.get(dia, 0.0) + tonelaje_grua_t

            filas_bascula = self.bascula.paso(t_s, C.DT_S, hora)
            for fila in filas_bascula:
                if fila["variable"] == "peso_neto_t":
                    self.masa_bascula_por_dia_t[dia] = self.masa_bascula_por_dia_t.get(dia, 0.0) + fila["valor"]
                self._registrar(**fila)

            if t_s - self._ultimo_muestreo_reefer_s >= C.REEFER_MUESTREO_S:
                self._ultimo_muestreo_reefer_s = t_s
                lecturas = self.reefers.leer_sensores(indices_reefer)
                for i in indices_reefer:
                    alim_id = int(self.red.id_a_alimentador[i])
                    self._registrar(f"reefer_{i}", "reefer", "temperatura_c", float(lecturas[i]),
                                     "C", self.reefers.sensores_temp[i].calidad, alim_id)
                    self._registrar(f"reefer_{i}", "reefer", "potencia_kw", float(demanda_kw[i]),
                                     "kW", "ok", alim_id)
                    self._registrar(f"reefer_{i}", "reefer", "compresor_on",
                                     float(self.reefers.compresor_on[i]), "bool", "ok", alim_id)
                for alim in self.red.alimentadores:
                    self._registrar(f"alimentador_{alim.id}", "alimentador", "tension_v",
                                     alim.tension_v, "V", "ok", alim.id)
                    self._registrar(f"alimentador_{alim.id}", "alimentador", "demanda_kw",
                                     alim.demanda_kw, "kW", "ok", alim.id)
                    # Invariante: si la demanda excede la capacidad, tiene que haber un
                    # evento de protección registrado — si no, el modelo de red está mal.
                    if alim.demanda_kw > alim.capacidad_kw and alim.energizado:
                        raise AssertionError(
                            f"Alimentador {alim.id}: demanda {alim.demanda_kw:.1f} kW supera "
                            f"su capacidad {alim.capacidad_kw:.1f} kW sin protección abierta."
                        )

                # Contexto ambiental y del buque, para que la Fase 2 (y la celda de
                # validación) puedan cruzar actividad vs. condiciones sin tocar el objeto
                # Simulador: todo lo que hace falta queda en el propio parquet de salida.
                self._registrar("ambiente_1", "ambiente", "temperatura_c", self.ambiente.temp_c, "C")
                self._registrar("ambiente_1", "ambiente", "viento_ms", self.ambiente.viento_ms, "m/s")
                self._registrar("ambiente_1", "ambiente", "humedad_pct", self.ambiente.hr_pct, "%")
                self._registrar("ambiente_1", "ambiente", "radiacion_wm2", self.ambiente.rad_wm2, "W/m2")
                self._registrar("ambiente_1", "ambiente", "marea_m", self.ambiente.marea_m, "m")
                self._registrar("buque_1", "buque", "nave_en_sitio", float(nave_en_sitio), "bool")
                self._registrar("sitio_3", "operacion", "suspension_viento",
                                 float(self._suspension_viento), "bool")

            self.reloj.avanzar()

            if len(self.telemetria) >= self.FILAS_POR_CHUNK:
                self._volcar_chunk()

            if t_s >= proximo_reporte_s:
                acumuladas = self._filas_totales + len(self.telemetria)
                print(f"  ... {t_s/3600.0:6.1f} h / {self.horas:.1f} h simuladas "
                      f"({acumuladas:,} filas de telemetría)")
                proximo_reporte_s += progreso_cada_h * 3600.0

        self._volcar_chunk()

    def dataframes(self) -> tuple:
        """Devuelve (telemetria_df, verdad_terreno_df) listos para escribir a Parquet."""
        self._volcar_chunk()
        tele = pd.concat(self._chunks, ignore_index=True)
        # Las columnas de texto son unos pocos valores distintos repetidos millones de
        # veces: como categorías ocupan una fracción y Parquet las guarda como diccionario.
        for col in ("entidad_id", "entidad_tipo", "variable", "unidad", "calidad_sensor"):
            tele[col] = tele[col].astype("category")
        tele["alimentador_id"] = tele["alimentador_id"].astype("Int16")
        tele["fecha"] = tele["timestamp_utc"].dt.date.astype(str)
        verdad = self.inyector.obtener_verdad_terreno(self.reloj.inicio_utc)
        return tele, verdad


# ---- celda 32 ----
def validar_simulacion(tele: pd.DataFrame, verdad: pd.DataFrame) -> None:
    """Criterios de aceptación del enunciado. Sin mensaje claro, un fallo silencioso en
    Fase 2 se ve como "el detector de anomalías rinde mal" en vez de "el dataset está roto".
    """
    tele = tele.sort_values("timestamp_utc")

    # 1) tasa_max de la temperatura de reefer, recalculada desde la propia salida.
    for entidad, grupo in tele[tele.variable == "temperatura_c"].groupby("entidad_id"):
        grupo = grupo.sort_values("timestamp_utc")
        dt_s = grupo["timestamp_utc"].diff().dt.total_seconds()
        tasa = (grupo["valor"].diff() / dt_s).abs()
        peor = tasa.max()
        if pd.notna(peor) and peor > C.REEFER_TASA_MAX_C_S:
            raise AssertionError(
                f"[validación] {entidad}: la telemetría de salida muestra una tasa de cambio "
                f"de {peor:.4f} °C/s, sobre la cota física {C.REEFER_TASA_MAX_C_S:.4f} °C/s."
            )

    # 1b) tasa_max de la velocidad de la faja. La cota sale de la física (rampa de
    #     aceleración + entrada del patinaje), no de un margen puesto a ojo.
    faja_vel = tele[(tele.entidad_id == "faja_1") & (tele.variable == "velocidad_ms")].sort_values("timestamp_utc")
    dt_s = faja_vel["timestamp_utc"].diff().dt.total_seconds()
    tasa = (faja_vel["valor"].diff() / dt_s).abs()
    limite_faja = C.FAJA_TASA_MAX_VEL_MS_S
    if (tasa > limite_faja).any():
        raise AssertionError(
            f"[validación] faja_1: la velocidad de salida cambia más rápido que la cota "
            f"física ({tasa.max():.3f} m/s/s > {limite_faja:.3f} m/s/s)."
        )

    # 2) balance de masa diario: báscula vs. faja + grúas, dentro de MASA_MARGEN_PCT.
    faja_dia = (tele[(tele.entidad_id == "faja_1") & (tele.variable == "tonelaje_cabeza_th")]
                .assign(t=lambda d: d["valor"] * (C.DT_S / 3600.0))
                .groupby("fecha")["t"].sum())
    grua_dia = tele[tele.variable == "carga_movida_t"].groupby("fecha")["valor"].sum()
    bascula_dia = tele[tele.variable == "peso_neto_t"].groupby("fecha")["valor"].sum()
    movido_dia = faja_dia.add(grua_dia, fill_value=0.0)
    for fecha, movido in movido_dia.items():
        cubierto = bascula_dia.get(fecha, 0.0)
        if movido < C.MASA_MIN_DIA_T:
            continue  # ver MASA_MIN_DIA_T: en un día casi sin nave el remanente del día
                      # anterior domina el cociente y el porcentaje no dice nada
        error_pct = abs(cubierto - movido) / movido * 100.0
        if error_pct > C.MASA_MARGEN_PCT:
            raise AssertionError(
                f"[validación] {fecha}: balance de masa fuera de margen — movido por "
                f"faja+grúas={movido:.1f} t, cubierto por báscula={cubierto:.1f} t "
                f"({error_pct:.1f}% > {C.MASA_MARGEN_PCT}%)."
            )

    # Balance acumulado de toda la corrida: aquí el material que cruza la medianoche ya no
    # se puede esconder, así que este chequeo cubre los días que el filtro anterior salta.
    total_movido, total_cubierto = movido_dia.sum(), bascula_dia.sum()
    if total_movido > 0:
        error_pct = abs(total_cubierto - total_movido) / total_movido * 100.0
        if error_pct > C.MASA_MARGEN_PCT:
            raise AssertionError(
                f"[validación] balance de masa acumulado fuera de margen — movido="
                f"{total_movido:.1f} t, pesado={total_cubierto:.1f} t "
                f"({error_pct:.1f}% > {C.MASA_MARGEN_PCT}%)."
            )

    # La fase viene codificada: -1 = detenida, 0..6 = índice en C.GRUA_FASES.
    fase = tele[tele.variable == "fase_actual"].sort_values("timestamp_utc")
    COD_DETENIDA, COD_POSICIONAR = -1.0, float(C.GRUA_FASES.index("posicionar"))

    # 3) actividad de grúa o faja sin nave en sitio.
    nave = tele[(tele.entidad_id == "buque_1") & (tele.variable == "nave_en_sitio")].sort_values("timestamp_utc")
    if not nave.empty:
        for grua_id, grupo in fase.groupby("entidad_id"):
            grupo = grupo.sort_values("timestamp_utc")
            estado = pd.merge_asof(grupo[["timestamp_utc"]], nave[["timestamp_utc", "valor"]],
                                    on="timestamp_utc", direction="backward")
            activa = grupo["valor"].to_numpy() != COD_DETENIDA
            sin_nave = estado["valor"].fillna(0.0).to_numpy() < 0.5
            if np.any(activa & sin_nave):
                raise AssertionError(f"[validación] {grua_id}: hay fases activas sin nave en sitio.")

        faja_v = tele[(tele.entidad_id == "faja_1") & (tele.variable == "velocidad_ms")].sort_values("timestamp_utc")
        estado = pd.merge_asof(faja_v[["timestamp_utc"]], nave[["timestamp_utc", "valor"]],
                                on="timestamp_utc", direction="backward")
        sin_nave = estado["valor"].fillna(0.0).to_numpy() < 0.5
        # Tolerancia = tiempo de rampa: la faja tarda FAJA_RAMPA_S en frenar tras zarpar,
        # así que solo se exige velocidad ~0 lejos de cualquier transición reciente de nave.
        cambia_nave = nave["valor"].diff().fillna(0.0).to_numpy() != 0.0
        cerca_de_transicion = pd.Series(False, index=faja_v.index)
        for t_transicion in nave.loc[cambia_nave, "timestamp_utc"]:
            cerca_de_transicion |= (faja_v["timestamp_utc"] - t_transicion).abs().dt.total_seconds() < C.FAJA_RAMPA_S * 1.5
        violacion = sin_nave & (faja_v["valor"].to_numpy() > 0.05) & (~cerca_de_transicion.to_numpy())
        if violacion.any():
            raise AssertionError("[validación] faja_1: hay movimiento sostenido sin nave en sitio.")

    # 4) actividad de grúa con viento sobre el límite operacional.
    viento = tele[(tele.entidad_id == "ambiente_1") & (tele.variable == "viento_ms")].sort_values("timestamp_utc")
    if not viento.empty:
        for grua_id, grupo in fase.groupby("entidad_id"):
            grupo = grupo.sort_values("timestamp_utc")
            estado = pd.merge_asof(grupo[["timestamp_utc"]], viento[["timestamp_utc", "valor"]],
                                    on="timestamp_utc", direction="backward")
            activa = grupo["valor"].to_numpy() != COD_DETENIDA
            viento_excesivo = estado["valor"].to_numpy() > C.GRUA_VIENTO_LIMITE_MS
            if np.any(activa & viento_excesivo):
                raise AssertionError(f"[validación] {grua_id}: fase activa con viento sobre el límite operacional.")

    # 5) demanda de alimentador sobre capacidad sin evento de protección que lo explique.
    fallas_red = verdad[verdad.tipo_falla.isin(["apertura_alimentador", "transferencia_generador"])]
    demanda = tele[tele.variable == "demanda_kw"].dropna(subset=["alimentador_id"]).sort_values("timestamp_utc")
    for alim_id, grupo in demanda.groupby("alimentador_id"):
        for _, fila in grupo[grupo["valor"] > C.ALIMENTADOR_CAPACIDAD_KW].iterrows():
            cubierta = fallas_red[
                (fallas_red.alimentador_afectado == alim_id)
                & (fallas_red.t_inicio <= fila["timestamp_utc"])
                & (fila["timestamp_utc"] <= fallas_red.t_fin)
            ]
            if cubierta.empty:
                raise AssertionError(
                    f"[validación] alimentador {alim_id}: demanda {fila['valor']:.1f} kW excede "
                    f"la capacidad ({C.ALIMENTADOR_CAPACIDAD_KW:.1f} kW) sin evento de protección."
                )

    # 6) las duraciones de ciclo de grúa deben ser lognormales, no uniformes.
    for grua_id, grupo in fase.groupby("entidad_id"):
        grupo = grupo.sort_values("timestamp_utc")
        inicios_ciclo = grupo[grupo["valor"] == COD_POSICIONAR]["timestamp_utc"]
        duraciones = inicios_ciclo.diff().dt.total_seconds().dropna().to_numpy()
        if len(duraciones) < 8:
            continue  # muy pocos ciclos para un test estadístico confiable (típico de la prueba corta)
        _, p_valor = stats.kstest(duraciones, "uniform",
                                   args=(duraciones.min(), duraciones.max() - duraciones.min()))
        if p_valor > 0.10:
            raise AssertionError(
                f"[validación] {grua_id}: las duraciones de ciclo no se distinguen de una "
                f"uniforme (KS p={p_valor:.3f}); revisa el sorteo lognormal en Grua."
            )

    print("Validación OK: no se detectaron violaciones de los criterios de aceptación.")


# (la llamada sobre la corrida de prueba se omite: la prueba corta no se ejecuta aquí)


# ---- celda 34 ----
sim = Simulador(horas=C.HORAS_SIMULADAS, n_reefers=C.N_REEFERS, rng=rng)
sim.correr(progreso_cada_h=C.HORAS_SIMULADAS / 20)

tele, verdad = sim.dataframes()
print(f"\nFilas de telemetría: {len(tele):,}")
print(f"Fallas programadas: {len(verdad)}")


# ---- celda 36 ----
validar_simulacion(tele, verdad)


# ---- celda 37 ----
try:
    import pyarrow  # noqa: F401 - motor de E/S que usa pandas.to_parquet para particionar;
                     # no es una librería de simulación, así que no rompe la restricción de
                     # "solo numpy/pandas/scipy/matplotlib" del enunciado.
except ImportError as exc:
    raise ImportError(
        "Escribir Parquet particionado por día (pandas.to_parquet(partition_cols=...)) "
        "requiere pyarrow instalado. Instálalo con: pip install pyarrow"
    ) from exc

DIR_SALIDA = "salida_sitio3"
import shutil
shutil.rmtree(DIR_SALIDA, ignore_errors=True)  # partition_cols AGREGA archivos: sin esto se duplicarían filas
os.makedirs(DIR_SALIDA, exist_ok=True)

# CAMBIO FASE 2: pandas guarda los timestamps en NANOsegundos y Spark 4 no sabe leer
# ese tipo (falla con "Illegal Parquet type: INT64 (TIMESTAMP(NANOS,true))").
# Se fuerzan MICROsegundos, que es la precisión nativa de Spark.
opciones_ts = dict(coerce_timestamps="us", allow_truncated_timestamps=True)
tele.to_parquet(os.path.join(DIR_SALIDA, "telemetria.parquet"),
                 partition_cols=["fecha"], index=False, **opciones_ts)
verdad.to_parquet(os.path.join(DIR_SALIDA, "verdad_terreno.parquet"), index=False, **opciones_ts)

print(f"Escrito: {DIR_SALIDA}/telemetria.parquet/  (particionado por columna 'fecha')")
print(f"Escrito: {DIR_SALIDA}/verdad_terreno.parquet")

