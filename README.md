# Generador de logs crudos masivos — TPC Sitio 3, Fase 1

Simulador de la telemetría del Sitio 3 del Terminal Puerto Coquimbo. Genera un
dataset sintético de más de diez millones de eventos en formato JSON Lines, con
series temporales que tienen inercia, deriva, ruido y anomalías sostenidas,
para que la Fase 2 tenga algo real que detectar. Están implementadas las dos
arquitecturas de escritura concurrente de la guía, detrás de la misma interfaz.

**Instalación.** No hay instalación. El generador se escribe exclusivamente con
la biblioteca estándar de Python 3.11 o superior: no hay `requirements.txt`, no
hay entorno virtual obligatorio y no hay dependencias que resolver. La única
excepción es `matplotlib`, que se usa únicamente en `bench/graficos.py` para
producir las figuras del informe y no forma parte del simulador; si sólo se
quiere regenerar el dataset, no hace falta instalarlo. Basta con clonar el
repositorio, verificar la versión del intérprete con `python3 --version` y
ejecutar `python -m bench.test_formato`, que corre la suite de tests del
contrato de datos, del reparto de carga y de la física en unos segundos y sin
escribir nada en disco.

**Ejecución.** El comando exacto que regenera el dataset completo es el
siguiente, y es el único que hace falta para reproducir la entrega:

```bash
python -m src.main --workers 8 --total-events 10000000 \
    --output-dir data/raw --arch shard --batch-size 10000 \
    --seed 42 --start-time 2026-08-24T00:00:00Z
```

Todo es parametrizable por línea de comandos y no hay constantes escondidas en
el código. Con la misma semilla y el mismo número de trabajadores, dos
ejecuciones de `--arch shard` producen archivos byte a byte idénticos, porque
la base temporal la fija `--start-time` y no el reloj del sistema. El programa
valida sus argumentos antes de escribir nada: rechaza un número de procesos
desproporcionado, rechaza una cola sin cota, avisa si el total queda bajo el
mínimo exigido y comprueba que haya espacio libre suficiente en disco. Al
terminar deja un `manifiesto.json` en la carpeta de salida y añade una fila a
`bench/mediciones.csv` con las métricas de la corrida, incluido el pico de
memoria residente del proceso padre y del hijo más grande. Para verificar el
resultado, `python -m bench.validar data/raw` recorre todas las líneas de todos
los archivos y comprueba el conteo, el esquema y el balance de carga entre
trabajadores.

**Cuánto demora y cuánto ocupa.** El dataset son 179 puntos de medición
reportando cada quince segundos durante 55.866 ticks, es decir 10.000.014
eventos que cubren unos 9,7 días simulados de operación continua. Cada evento
del esquema completo pesa unos 186 bytes, así que la salida ocupa
aproximadamente **1,9 GB**; con `--esquema min`, que emite sólo los seis campos
obligatorios, baja a unos 1,5 GB. El tiempo de ejecución depende por completo
del equipo y del tipo de disco, y por eso no se anota aquí ninguna cifra: la
duración real de cada corrida queda registrada en `manifiesto.json` y en
`bench/mediciones.csv`, y el análisis está en `docs/reporte_benchmarking.pdf`.
El dataset no está versionado —`data/raw/` está en `.gitignore` desde el primer
commit—; lo que sí se versiona es la muestra de 50.000 eventos en
`data/muestra/`.

## Las dos arquitecturas

| | `--arch shard` (Opción B) | `--arch queue` (Opción A) |
|---|---|---|
| Salida | Un `part-NNN.jsonl` por trabajador | Un `eventos.jsonl` único |
| Sincronización | Ninguna: no hay recurso compartido | Cola multiproceso con `maxsize` acotado |
| Coste de `pickle` | Dos por trabajador en toda la corrida | Uno por lote encolado |
| Riesgo dominante | Shard truncado si muere un worker | Desborde de RAM si falta contrapresión |
| Reproducibilidad | Byte a byte entre corridas | El mismo conjunto de eventos, distinto orden de líneas |

La reproducibilidad byte a byte es imposible en la Opción A por construcción,
no por un defecto: el orden en que los lotes de distintos trabajadores llegan
al escritor lo decide el planificador del sistema operativo. Lo que sí se
garantiza, y `bench/test_formato.py::test_equivalencia_arquitecturas` lo
verifica comparando las líneas ordenadas, es que ambas arquitecturas producen
exactamente el mismo multiconjunto de eventos con la misma semilla.

## Argumentos

| Argumento | Por defecto | Qué hace |
|---|---|---|
| `--workers` | núcleos del equipo | Procesos trabajadores |
| `--total-events` | `10000000` | Piso de eventos; el total real redondea hacia arriba al tick completo |
| `--sim-days` | — | Si se indica, la ventana simulada manda sobre `--total-events` |
| `--output-dir` | `data/raw` | Carpeta de salida |
| `--arch` | `shard` | `shard` o `queue` |
| `--batch-size` | `10000` | Eventos por lote antes de cada `writelines` o cada `put` |
| `--queue-maxsize` | `64` | Sólo con `queue`: mensajes máximos en la cola. Acota la RAM en ~`maxsize × batch-size` eventos |
| `--seed` | `42` | Semilla maestra |
| `--start-time` | `2026-08-24T00:00:00Z` | Instante inicial simulado. Constante, nunca el reloj del sistema |
| `--interval-s` | `15.0` | Período de muestreo de los sensores |
| `--esquema` | `full` | `min` (6 campos) o `full` (además `site`, `asset_type`, `status`, `seq`) |
| `--start-method` | el del sistema | `fork`, `spawn` o `forkserver` |
| `--etiqueta` | — | Nombre del experimento; agrupa corridas en el CSV |
| `--repeticion` | `1` | Número de repetición. **`0` marca la corrida de calentamiento**, que se descarta al calcular medianas |
| `--bench-csv` | `bench/mediciones.csv` | CSV al que se anexa la fila de la corrida |
| `--force` | — | Sobrescribe una carpeta de salida que ya tenga shards |
| `--log-level` | `INFO` | Nivel del log operativo |

## Verificación

Antes de medir nada, comprobar que el simulador está sano. Ninguno de estos
comandos tarda más que segundos y ninguno escribe en `data/raw/`.

```bash
python -m bench.test_formato              # suite de tests
python -m bench.validar data/raw --profundo   # valida un dataset ya generado
```

`test_formato` cubre el contrato de datos (equivalencia del formateador ISO
contra `strftime`, reparto exacto, esquema de los eventos), la física (que un
reefer no salte más de 1 °C entre lecturas, que las anomalías efectivamente se
disparen, que la vibración y la corriente de una faja correlacionen) y la
equivalencia entre las dos arquitecturas. `validar` recorre todas las líneas de
todos los shards —los registros rotos aparecen en el medio, nunca al principio—
y reporta el conteo por trabajador, que es lo que hace auditable el paralelismo.

Y la prueba de reproducibilidad, que es un requisito duro de la guía y conviene
tener ensayada porque la pueden pedir en vivo:

```bash
python -m src.main --workers 4 --total-events 1000000 --output-dir /tmp/r1 --seed 42
python -m src.main --workers 4 --total-events 1000000 --output-dir /tmp/r2 --seed 42
diff -r /tmp/r1 /tmp/r2 --exclude=manifiesto.json   # sin salida = idénticos
```

Se excluye el manifiesto porque registra la fecha real de ejecución y la
duración, que obviamente cambian entre corridas. Los datos no. Con `--arch
queue` esta comparación falla por diseño: ahí lo que se conserva es el
multiconjunto de eventos, no el orden de las líneas.

## La campaña de mediciones

El informe del §4.4 tiene siete puntos. Cinco se contestan con un experimento
concreto; los otros dos son escritura. Este es el mapa completo:

| Punto del §4.4 | Qué experimento lo contesta | Archivo que produce |
|---|---|---|
| 1. Entorno de pruebas | ninguno: lo registra cada corrida | columnas `python`, `so`, `maquina`, `nucleos_logicos` de `mediciones.csv` |
| 2. Curva de escalabilidad | `--barrido escalabilidad` | `escalabilidad.csv` |
| 3. Speedup y eficiencia | el mismo, agregado | `resumen.csv`, figuras 1 y 2 |
| 4. Rendimiento de E/S | el mismo, columnas de throughput | `mediciones.csv`, figura 3 |
| 5. Costo de `pickle` | `micro_pickle` **y** `--barrido lotes` | `mediciones_pickle.csv`, `comparacion_lotes.csv`, figuras 4 y 7 |
| 6. Gestión de memoria | barrido manual de `--queue-maxsize` | columnas `pico_*_mb` de `mediciones.csv` |
| 7. Interpretación crítica | se escribe, no se mide | — |

Fuera de esa tabla quedan dos experimentos que la guía pide en otras secciones
y que conviene tener: **hilos contra procesos** (§1.3, «el mejor argumento que
van a tener en la defensa») y la **comparación arquitectónica** entre las
Opciones A y B (§2.4, «un argumento del tipo *elegimos B porque...* vale
muchísimo más que cualquier explicación teórica»).

### Orden sugerido

Los cuatro primeros son baratos y responden preguntas distintas; el quinto es
el que consume las horas de máquina. Conviene correrlos en este orden porque si
algo está mal configurado, es preferible descubrirlo en el experimento de diez
minutos y no en el de tres horas.

**1. ¿Cuánto va a tardar todo esto?** Una pasada mínima para calibrar. Si esto
tarda T, la campaña completa del paso 5 tarda del orden de 40·T.

```bash
python -m bench.campana --total-events 1000000 --workers 1 8 --repeticiones 1
```

**2. ¿Por qué procesos y no hilos?** Genera la misma carga de forma secuencial,
con `ThreadPoolExecutor` y con `ProcessPoolExecutor`. Escribe a un sumidero
nulo a propósito: al sacar el disco de la ecuación, cualquier diferencia es
atribuible al GIL y no al almacenamiento. Es esperable que la versión con
hilos resulte **algo más lenta** que la secuencial, por los cambios de contexto
y la contención por el candado.

```bash
python -m bench.campana --barrido hilos --total-events 2000000 --workers 1 2 4 8
```

**3. ¿Cuánto cuesta la comunicación entre procesos?** Dos experimentos que se
complementan y que es importante no confundir:

- `micro_pickle` **aísla el canal**: una cola, un productor, un consumidor, sin
  física, sin disco y sin formateo. El tiempo medido es atribuible al IPC y a
  nada más, que es la condición para poder afirmar algo sobre él.
- `--barrido lotes` mide **el simulador completo** con `--arch queue`. Muestra
  cuánto de ese costo se ve en el tiempo total cuando compite con la generación
  y la escritura.

```bash
python -m bench.micro_pickle --eventos 1000000 --repeticiones 3
python -m bench.campana --barrido lotes --total-events 2000000 \
    --workers-fijo 8 --lotes 1 100 1000 10000
```

Con `--batch-size 1` se paga un `pickle`, un `write` al pipe y un `unpickle`
por cada evento; esa serie tarda varias veces más que las otras tres juntas. Si
se hace impracticable, baje `--total-events`, pero no por debajo de un millón:
a menos escala el ruido del sistema operativo domina la medición.

**4. ¿Por qué esta arquitectura y no la otra?** Misma carga, mismos
trabajadores, mismo reparto de activos; lo único que cambia es cómo llegan los
eventos al disco.

```bash
python -m bench.campana --barrido arquitectura --total-events 10000000 --workers-fijo 8
```

Al interpretarlo: la Opción A produce un archivo y la B produce N. En SSD NVMe
se espera que B aproveche mejor el ancho de banda; en disco mecánico puede ser
al revés, porque varios flujos simultáneos obligan al cabezal a saltar. Si
trabajan sobre HDD, eso es un hallazgo del informe, no un error.

**5. ¿Dónde se aplana la curva?** El experimento central y el más largo: cinco
configuraciones por cuatro corridas cada una, con diez millones de eventos.

```bash
python -m bench.campana --barrido escalabilidad --total-events 10000000 \
    --workers 1 2 4 8 16
```

**6. ¿Cuánta memoria se usa y de qué depende?** El punto 6 pide decir qué
`maxsize` se eligió y por qué, y contar si llegaron a provocar un desborde. No
hay barrido automático porque cada corrida es independiente:

```bash
for ms in 4 16 64 256; do
  python -m src.main --arch queue --workers 8 --total-events 2000000 \
    --output-dir /tmp/ms --queue-maxsize $ms --etiqueta maxsize --force
done
```

El techo de RAM de la cola es aproximadamente `maxsize × batch-size ×
bytes_por_evento`. Con `--queue-maxsize 4096 --batch-size 10000` se puede
provocar el desborde a propósito: la guía dice que si lo provocaron, lo
cuenten, porque es un resultado.

**6b. ¿Dónde se paga exactamente el `pickle`?** Es una de las preguntas
anunciadas para la defensa (§4.5). Este script parcha `ForkingPickler.dumps`
—por donde pasa todo lo que cruza entre procesos— y cuenta las llamadas reales
de cada arquitectura sobre la misma carga.

```bash
python -m bench.donde_pickle --workers 4 --total-events 200000 --lotes 1 100 1000 10000
```

No escribe CSV: es para entender y para tener el número a mano en la defensa.

**7. Agregar y graficar.**

```bash
python -m bench.resumen     # tabla de medianas, speedup y eficiencia
pip install matplotlib
python -m bench.graficos    # figuras en docs/figuras/
```

### Cómo se relacionan los archivos

Cada ejecución del simulador —venga de donde venga, incluso una corrida
manual— añade su fila a `mediciones.csv`. Los barridos escriben además su
propio resumen. Nada se sobrescribe: los CSV son acumulativos y se ordenan
solos.

```
python -m src.main ...  ──►  data/raw/manifiesto.json   (metadata de ESA corrida)
                        └─►  bench/mediciones.csv       (registro CRUDO, 1 fila por corrida)
                                    │
python -m bench.campana ┐           ├──►  bench/resumen.py   ──►  resumen.csv
   --barrido escalabilidad ──────►  escalabilidad.csv
   --barrido arquitectura ───────►  comparacion_arquitecturas.csv
   --barrido lotes ──────────────►  comparacion_lotes.csv
   --barrido hilos ──────────────►  hilos_vs_procesos.csv
python -m bench.micro_pickle ────►  mediciones_pickle.csv
                                            │
                                            └──►  bench/graficos.py  ──►  docs/figuras/*.png
```

`mediciones.csv` es el registro crudo que la guía pide conservar: una fila por
ejecución, **incluidas las de calentamiento**, marcadas en la columna `fase`.
Se descartan del análisis pero se registran, porque la guía pide dejar dicho
que se hizo el calentamiento. `resumen.csv` es la vista agregada: mediana —no
la mejor corrida—, desviación estándar, speedup y eficiencia. Esa es la tabla
que se copia al informe.

Las siete figuras que produce `graficos.py`: speedup contra el ideal (1),
eficiencia (2), throughput y MB/s (3), costo del IPC aislado (4), hilos contra
procesos (5), comparación arquitectónica (6) y efecto del lote sobre el
simulador completo (7). Todas con ejes rotulados y unidades, porque un informe
de ingeniería no se sustenta en capturas del terminal.

## Estructura

```
src/main.py            punto de entrada, argparse, validaciones, memoria, manifiesto
src/simulador.py       modelos físicos con estado de cada familia de activo
src/esquema.py         contratos, formateo de tiempo, reparto, sumideros, bucle común
src/arquitectura_b.py  Opción B: un .jsonl por proceso (archivos segmentados)
src/arquitectura_a.py  Opción A: proceso escritor único alimentado por cola
bench/campana.py       los cuatro barridos experimentales
bench/resumen.py       agrega mediciones.csv en la tabla del informe
bench/micro_pickle.py  costo del canal IPC aislado, por tamaño de lote
bench/donde_pickle.py  cuenta las llamadas reales a pickle de cada arquitectura
bench/validar.py       validación del dataset completo
bench/test_formato.py  tests del contrato de datos, del reparto y de la física
bench/graficos.py      figuras del informe (único lugar donde se usa matplotlib)
```

## Inventario simulado

| Activo | Cantidad | Métricas | Puntos |
|---|---|---|---|
| Contenedor reefer | 48 | `temperature`, `humidity`, `current` | 144 |
| Tramo de faja | 6 | `vibration`, `current`, `weight` | 18 |
| Grúa móvil | 2 | `weight`, `current` | 4 |
| Báscula de acceso | 1 | `weight` | 1 |
| Sensor ambiental de patio | 12 | `temperature` | 12 |
| | | | **179** |

Las métricas de un mismo activo están acopladas a través de su estado interno:
la vibración y el amperaje de una faja suben juntos porque ambos dependen de la
carga, y la corriente de un reefer sigue la histéresis de su compresor. No son
señales independientes con nombres distintos.

## Esquema del evento

Los seis campos obligatorios más los cuatro opcionales recomendados, presentes
en todos los eventos:

```json
{"timestamp":"2026-08-24T00:00:00.000Z","sensor_id":"REEFER_S3_01","metric":"temperature","value":-17.88,"unit":"C","worker_id":0,"site":"S3","asset_type":"reefer","status":"OK","seq":0}
```

`status` es la verdad de terreno de las anomalías: permite medir en la Fase 2
cuántas detectó el clasificador y cuántas inventó.

## Medición de memoria

El manifiesto y el CSV registran el pico de RSS del proceso padre y del hijo
más grande, obtenidos con `resource.getrusage`. Tres advertencias antes de
citar esas cifras en el informe:

- `RUSAGE_CHILDREN` devuelve el pico de **un** hijo, el más alto, no la suma de
  todos. Responde a «¿algún proceso se acercó al límite de RAM?», no a «¿cuánta
  memoria usó el sistema completo?».
- La unidad de `ru_maxrss` no está estandarizada: kilobytes en Linux, bytes en
  macOS. El código normaliza a MB detectando la plataforma explícitamente.
- En Windows el módulo `resource` no existe. La corrida no falla: el manifiesto
  registra `"medido_con": "no disponible"` y las celdas del CSV quedan vacías.

`tracemalloc` no sirve para esto, porque mide el heap de Python del proceso que
lo activa y no ve la memoria de los procesos hijos.
