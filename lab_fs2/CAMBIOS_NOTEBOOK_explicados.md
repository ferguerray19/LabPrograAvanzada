# Notebook para la presentación: qué se revisó, qué cambió y por qué

Archivos de esta carpeta:
- `fase2_pyspark.ipynb`: tu notebook con los cambios. Las imágenes van **dentro** del archivo, así que no hay que entregar una carpeta aparte.
- `diagrama_cluster.png`: el diagrama del clúster, por si lo quieren usar en otro lado.

Actualizado el 14-10: los cambios ahora están aplicados sobre **tu** `fase2_pyspark.ipynb` del PC (el que subiste el 14-10), así que conserva tus salidas y los comentarios que quitaste. Ya no hace falta comparar con el zip.

Actualizado el 18-10: las cifras de estas notas son las de la última corrida completa (18-10, `salida_fase2/metricas.json`), por ejemplo, esquema inferido 28,67 s vs declarado 10,93 s. Los cambios del 18-10 están en las secciones 2.11 y 2.12.

---

## 1. Revisión de Docker y de la configuración

(Las observaciones de código que siguen abiertas están en `REVISION_RUBRICA.md`.)

| Archivo | Estado |
|---|---|
| `docker-compose.yml` | Idéntico al del profesor. |
| `docker/Dockerfile` | Igual al del profesor, más `scipy`, que usa `generar_salida_sitio3.py` para crear `salida_sitio3/`. |
| `docker/spark-defaults.conf` | Idéntico al del profesor (AQE activado, Kryo y registro de eventos). |
| `verificar_cluster.py` | Es otra versión de la del profesor, con las mismas 4 comprobaciones. Tu captura muestra que pasan las 4. |
| `.env` | Perfil "Docker con 8 GB": 2 workers × 2 GB + 2 GB del driver = 6 GB < 15,6 GB (la RAM que Docker tiene asignada, medida en la sección 0.3). Está bien. |

Tres datos que les pueden servir si les preguntan:

- **¿Por qué el perfil de 8 GB si Docker tiene 15,6 GB?** Es a propósito: todas las mediciones del notebook se hicieron con 4 cores, y así son comparables entre corridas. El margen libre (9,6 GB) queda para Docker Desktop, el navegador y la UI de Spark.
- **¿Por qué no usar toda la RAM?** La fórmula solo cuenta la memoria que pide Spark. Además consumen RAM los procesos del master y de los workers, la memoria extra de cada JVM (*overhead*) y el propio Jupyter. Sin margen, Docker se queda sin memoria.
- **La UI :4040 se puede recuperar después.** El `spark-defaults.conf` guarda un registro de eventos. Si levantan el History Server con `docker compose --profile history up -d` y abren `http://localhost:18080`, pueden ver las pestañas Jobs y Stages de una sesión ya cerrada. Les sirve si olvidan capturar algo antes de `spark.stop()`.

---

## 2. Cambios en el notebook, uno por uno

Las celdas viejas no se tocaron, salvo en los puntos que se indican abajo. Todo lo demás son celdas nuevas.

### 2.1 Tabla inicial (celda 1)
Antes citaba la rúbrica vieja (15 %, 25 %). Ahora dice en qué sección está cada una de las 8 implicancias. Sirve como índice durante la presentación.

### 2.2 Sección 0.4 nueva: "Cómo trabaja el clúster" (implicancia 1, criterio 1)
Es una celda de texto con 3 imágenes: el diagrama, la salida de `verificar_cluster.py` y la UI :8080 con los 2 workers. Explica qué hace el driver, el master y los workers, y por qué un `.collect()` de millones de filas es un error.

Explicado simple:
- Una sola máquina tiene un tope de RAM. Spark reparte el trabajo entre varias máquinas (workers), y para crecer se agregan workers. Eso es escalar horizontalmente.
- `collect()` trae todos los datos al driver, que es **una** máquina con 2 GB. Con 10 millones de filas, el driver se queda sin memoria y se pierde la ventaja del clúster.

**¿Por qué `verificar_cluster.py` va como captura y no se ejecuta desde el notebook?** La sesión del notebook ocupa los 4 cores del clúster. Si `verificar_cluster.py` abriera una segunda sesión, se quedaría esperando recursos y daría "0 executors". Por eso se corre antes de abrir el notebook.

La "herramientas de medición" que antes era la 0.4 pasó a ser la 0.5.

### 2.3 Sección 1.2 nueva: "Evaluación perezosa" (implicancia 2, criterio 2)
Era lo único que faltaba por completo. El código nuevo:

```python
t0 = time.perf_counter()
alarmas = (raw.filter(F.col("status") == "ALARM")
              .withColumn("value_f", F.col("value") * 9 / 5 + 32)
              .select("timestamp", "sensor_id", "value_f"))
t_transf = time.perf_counter() - t0

alarmas.explain()

t0 = time.perf_counter()
n_alarmas = alarmas.count()
t_accion = time.perf_counter() - t0
```

Línea por línea:
1. `time.perf_counter()` es un cronómetro. Se toma la hora antes y después y se resta.
2. `filter`, `withColumn` y `select` son **transformaciones**: no leen nada, solo anotan pasos en el plan. Por eso `t_transf` sale casi 0.
3. `explain()` imprime el plan que Spark armó, sin ejecutarlo.
4. `count()` es una **acción**: recién aquí Spark lee los archivos. Por eso `t_accion` es el tiempo real.

Qué mostrar en el plan: la línea `FileScan json` tiene `PushedFilters: [IsNotNull(status), EqualTo(status,ALARM)]` y `ReadSchema` con solo 4 columnas. Significa que Spark, como conoce la consulta entera antes de ejecutarla, aplica el filtro mientras lee y solo convierte las columnas que se usan. En la corrida del 15-10 el plan muestra exactamente esas dos cosas.

Cuidado con lo que se afirma del `count()`: demuestra la ejecución perezosa, pero **no** ejecuta el plan del `explain()`. Ese plan es el de la consulta completa, el que correría un `show()` o un `write`. Para contar, Spark vuelve a optimizar y lee solo `status`, filtra y cuenta, sin calcular `value_f`. Su plan propio se ve con `alarmas.groupBy().count().explain()`.

`value_f` es solo el valor pasado a Fahrenheit, para tener una transformación que cree una columna. Se puede cambiar por otra.

Las secciones antiguas 1.2 y 1.3 pasaron a ser 1.3 y 1.4.

### 2.4 Celdas de "Lectura" nuevas
Se agregaron después de 1.1, 1.4, 3.1, 6.2, 6.6 y 7. Cada una dice qué muestra el resultado y por qué importa en Big Data. Son las que más pide el criterio 7 ("contexto e interpretación en cada sección").

No traen tiempos exactos, porque los tiempos cambian en cada corrida; solo usan cifras fijas (filas, carpetas, grupos).

### 2.5 Líneas "En Big Data" y número de implicancia en los títulos
En los títulos de las secciones 1.1, 2, 6, 6.4, 6.6 y 7 se agregó qué implicancia cubren. En 2 y 6 se sumó una frase sobre por qué importa cuando los datos no caben en una máquina.

### 2.6 Los gráficos ahora se ven (sección 6.2)
Se borró la línea `matplotlib.use("Agg")`. "Agg" es un modo de matplotlib que dibuja directo a un archivo y no muestra nada en pantalla, así que los dos gráficos se guardaban pero no aparecían en el notebook. Sin esa línea, Jupyter los muestra.

### 2.7 Captura del straggler en 6.4 (implicancia 6, criterio 4)
Debajo de la "Lectura" del sesgo va la captura de la pestaña Stages (:4040). Qué señalar en ella:
- Duración: mediana 0,1 s y máximo 3 s. Una tarea tarda 30 veces más que la típica.
- Filas: mediana 100.800 y máximo 3.175.200. Esa tarea es la de faja_1.
- Spill: solo esa tarea derramó datos a disco, porque no le cupieron en la memoria de ejecución. La UI muestra **el mismo derrame** con dos cifras: *Spill (memory)* = 384 MiB es lo que ocupaban esos datos en memoria (deserializados) y *Spill (disk)* = 39,4 MiB es lo que ocuparon ya escritos en disco (serializados y comprimidos). Lo que se escribió a disco fueron 39,4 MiB, no 384.

### 2.8 Escritura con `coalesce` (implicancia 8, criterio 6)
Cambio en el código de la sección 7:

```python
# antes
.repartition("fecha")
# ahora
.coalesce(1)
```

La rúbrica dice literalmente "reduce archivos con coalesce, no con repartition".
- `repartition` mueve todas las filas por la red (es un shuffle) para reordenarlas.
- `coalesce` junta particiones que ya existen, sin mover datos por la red. Tu tabla de la sección 6.7 ya lo mide: `repartition` tiene 1 shuffle y `coalesce` tiene 0.
- Con `coalesce(1)` una sola tarea escribe todo, y como se usa `partitionBy("fecha")`, igual queda **un archivo por día**. Lo probé y quedan 7 carpetas con un archivo cada una.
- El costo: una sola tarea hace la escritura, así que esa celda puede tardar algo más que antes. Con 50 MB no importa.

### 2.9 Verificación del esquema al releer (criterio 6)
Antes solo se revisaba que existieran ciertos nombres de columnas. Ahora también se revisan los tipos:

```python
tipos_escritos = {c.name: c.dataType for c in etiquetada.schema if c.name != "fecha"}
tipos_releidos = {c.name: c.dataType for c in releida.schema if c.name != "fecha"}
assert tipos_escritos == tipos_releidos, "El esquema cambió al releer"
```

Cada línea arma un diccionario `{columna: tipo}`, uno con lo que se escribió y otro con lo que se leyó, y el `assert` los compara. `fecha` se deja fuera porque, al particionar, no se guarda dentro del archivo: Spark la reconstruye a partir del nombre de la carpeta (`fecha=2026-01-12`) y la pone al final. Lo probé y el `assert` pasa.

### 2.10 Cierre
- El resumen final ahora incluye la fila "Transformaciones vs acción".
- Antes de `spark.stop()` hay un recordatorio: tomar las capturas de :4040 antes de correr esa celda.

### 2.11 Correcciones del 18-10 (según `REVISION_RUBRICA.md`)
1. **Diagrama (0.4).** Ahora dice 15,6 GB de RAM para Docker, igual que la celda 0.3 y `metricas.json`. Se actualizó la imagen incrustada y `capturas/diagrama_cluster.png`.
2. **Range join (6.8).** La condición pasó de `timestamp_utc <= t_fin` a `timestamp_utc < t_fin`. El simulador activa cada falla con `t_inicio <= t < t_fin` (`generar_salida_sitio3.py:1185`): en `t_fin` la falla ya terminó. El texto de la celda lo explica.
3. **`count()` (1.2).** La "Lectura" ahora aclara que el `count` demuestra la ejecución perezosa, pero no ejecuta el plan del `explain()`: Spark lo vuelve a optimizar y solo lee `status`, sin calcular `value_f`.
4. **Recolector de métricas (0.5).** `ejecutar_en_grupo` da a cada ejecución una etiqueta única (`grupo#<uuid>`), así que repetir una celda (incluso la que define las herramientas) ya no mezcla corridas. `tareas` cuenta cada etapa una sola vez aunque la compartan varios jobs, recorre todos los intentos y conserva la última tarea exitosa de cada partición. Si la API falla por otra cosa que una etapa saltada (404), muestra el error en vez de ocultarlo. La columna `tareas` del resumen pasó a llamarse `tareas_con_shuffle`, porque solo cuenta las tareas que leyeron filas del shuffle (31 en la tabla frente a 32 en la captura).
5. **Spill (6.4).** El texto de la captura distingue *Spill (memory)* (384 MiB, tamaño en memoria) de *Spill (disk)* (39,4 MiB, lo que se escribió a disco). Son el mismo derrame medido de dos formas.
6. **Dos frases más precisas.** En 0.4, el driver ya no "no procesa datos": ejecuta el programa y trabaja con los resultados chicos (pandas y matplotlib corren ahí). Lo que no procesa es el volumen distribuido, que es tarea de los executors. En 6.8, una falla más corta que el muestreo ya no es "invisible para cualquier detector": puede no dejar ninguna lectura dentro de su ventana, como F005, aunque podría notarse por sus efectos posteriores.

El 18-10 se volvió a ejecutar el notebook completo en el clúster (equivale a **Restart Kernel and Run All**): 37 celdas con contadores 1–37, ninguna con error, y todas las aserciones pasaron. El plan del range join ya muestra `< t_fin`, y los conteos no cambiaron (6.395.323 filas, 436.218 lecturas en falla), porque los `t_fin` tienen fracciones de segundo y la telemetría usa segundos enteros. Con esa corrida se actualizaron las cifras de las "Lectura" de 6.4 y 6.5.

### 2.12 Correcciones de `REVISION_RUBRICA.md` (18-10, segunda ronda)
1. **Executors (0.2).** La sesión ya no sigue con el primer executor que aparece: espera uno por cada worker vivo del master y se detiene con un `assert` si falta alguno o si hay 0. Ahora la salida muestra `Executors: 2 (workers vivos en el master: 2)`.
2. **`verificar_cluster.py`.** Hace lo mismo: falla si hay menos executors que workers vivos y repite la prueba de visibilidad hasta que respondan todos los contenedores, para no aprobar un clúster incompleto.
3. **Acciones (1.2).** Ya no dicen "ejecutan el plan completo": Spark optimiza el plan y corre lo que esa acción necesita.
4. **Limpieza (5).** Se agregaron aserciones de nulos en las columnas obligatorias (`timestamp_utc`, `entidad_id`, `variable`, `valor`, `calidad_sensor`), porque el filtro de rangos no ve los nulos, y del dominio de `calidad_sensor`. También hay una celda "Lectura" nueva que cierra la sección: qué se quitó (2 duplicados), qué se conservó y por qué.
5. **Particiones (6.2).** La mejora se calcula contra la configuración manual más rápida (2x o 4x cores), no siempre contra 8. El texto aclara que cuál de las dos gana cambia entre corridas.
6. **Relectura (7).** Hay un `assert` que verifica que `fecha` vuelva como `date`.
7. **Capturas (0.4).** Se indica que son del 29-09 y que la prueba de humo se volvió a correr antes de la ejecución final.
8. **`docker-compose.yml`.** El puerto 4040 se sigue eligiendo en `.env` y 4041–4044 quedan como mapeos fijos, así que cambiar `PUERTO_DRIVER_UI` ya no rompe el rango.

Se volvió a ejecutar el notebook completo: 37 celdas con contadores 1–37, sin errores y con todas las aserciones aprobadas.

**Quedan abiertos a propósito:**
- La consigna (`setpoint_c`) del simulador no se restaura tras `compresor_degradado`. Cambiarlo regeneraría `salida_sitio3` y todos los resultados; es una decisión para la Fase 3.
- El range join con fallas superpuestas: la aserción lo detectaría, pero hoy no ocurre.
- `primer_contacto.ipynb` deja `timestamp` como texto; es solo introductorio.

---

## 3. Cómo dejarlo listo en tu PC

1. Guarda una copia de tu `fase2_pyspark.ipynb` actual y pon el nuevo en la carpeta del proyecto (la que se monta en `/opt/workspace`).
2. `docker compose up -d`, y después `docker compose exec jupyter python3 verificar_cluster.py`.
3. Abre `http://localhost:8889` → **Kernel → Restart Kernel and Run All Cells**. Esto es obligatorio: si no corre de principio a fin, los criterios 4 a 6 quedan con máximo 2.
4. Toma una captura nueva de Stages con el straggler. Como "Run All" también ejecuta `spark.stop()` al final, hay dos formas de hacerlo: seleccionar la última celda y usar **Run → Restart Kernel and Run up to Selected Cell**, capturar y después correr la última; o correr todo y capturar desde el History Server (`localhost:18080`). Si cambias la captura, actualiza los números de la celda 6.4 (mediana y máximo).
5. Revisa estas frases contra los números de la nueva corrida, porque dependen de cada ejecución:
   - 6.4, "Lectura": "unas 14 veces la mediana" (en la corrida del 18-10 dio 14,1x).
   - 6.5, "Lectura": "de ~15x a ~4x" (en la corrida del 18-10 dio 15,3x → 4,2x). Los tiempos totales de 6.4 y 6.5 varían mucho entre corridas; el texto ya lo dice y se apoya en el reparto de filas, que es estable.
6. Guarda el notebook con las salidas visibles. Eso es lo que se entrega.

---

## 4. Sobre los comentarios y el estilo

El código nuevo casi no tiene comentarios y los textos son cortos y directos. No intenté disfrazar que hubo ayuda de IA: no hay forma de garantizarlo y no es lo que les asegura la nota. La rúbrica evalúa (criterios 8 y 9, 30 % de la nota) que cada uno explique **con sus palabras** y responda preguntas apoyándose en su notebook. Lo más útil es que cada integrante **reescriba a su manera la celda "Lectura" de su implicancia**. Así queda en su estilo y, además, lo entiende. Si el ramo pide declarar el uso de IA, declárenlo.

---

## 5. Reparto propuesto para 6 integrantes

Son 15 minutos con preguntas, así que cada uno tiene cerca de 1,5 minutos de exposición. El orden sigue el notebook.

| Integrante | Implicancias | Secciones del notebook | Qué número mostrar |
|---|---|---|---|
| 1 | 1 Procesamiento distribuido + 2 Evaluación perezosa | 0.3, 0.4, 1.2 | 6 GB < 15,6 GB; 2 workers en :8080; transformaciones ≈ 0 s vs count |
| 2 | 3 Esquemas + 8 Columnar y particionado | 1.1, 1.4, 3.1, 7 | inferido 28,67 s vs declarado 10,93 s; 1.791 MB JSON vs 22 MB Parquet; 7 carpetas vs 604.800 |
| 3 | 4 Calidad de datos | 2, 4, 5 | 0 nulos en el crudo; 109.982 "duplicados" que no lo son; 124.219 lecturas marcadas, no borradas |
| 4 | 5 Shuffling | 6.1, 6.2, 6.3 | tabla de `Exchange`; 200 / 8 / AQE |
| 5 | 6 Sesgo | 6.4, 6.5 | faja_1 = 47,28 %; captura de Stages; salting |
| 6 | 7 Joins | 6.6, 6.8 | sort-merge vs broadcast; 6.395.323 → 9.419.323 filas con el join ingenuo; `assert` del range join |

El integrante 2 habla dos veces (al principio y al final): son las dos caras de "leer y escribir datos a escala".
