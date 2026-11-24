# Informe de estudio: notebook PySpark y presentación oral

Preparado el 19 de octubre de 2026 a partir de `fase2_pyspark.ipynb`, sus salidas guardadas, `salida_fase2/metricas.json` y las dos páginas de `Rubrica_Fase2_PySpark (2).pdf`.

## Cómo usar este informe

Este documento explica las **82 celdas del notebook principal**, incluidas sus 45 celdas de texto y sus 37 celdas de código. Al final se incluye el notebook introductorio `primer_contacto.ipynb`, las ocho implicancias de la rúbrica y preguntas de práctica.

La numeración «celda 1, 2, 3…» cuenta todas las celdas de arriba hacia abajo. `In [n]` identifica el contador de ejecución guardado de una celda de código. Por ejemplo, la celda 45 corresponde a `In [21]`. Si vuelves a ejecutar celdas por separado, esos contadores pueden cambiar.

Las frases «En tus palabras» son ejemplos para comprender y adaptar, no un texto que tengas que memorizar. Para practicar, sigue esta secuencia: **qué problema había → qué hicimos → qué resultado vimos → por qué importa a mayor escala**.

Las cifras se tomaron de la ejecución ya guardada. Para elaborar este informe no se volvió a ejecutar Spark ni se recontaron los Parquet. Los tiempos son observaciones de esa ejecución, no garantías de rendimiento futuro. El notebook y los datos originales no se modificaron.

## El proyecto completo, antes de mirar las celdas

El objetivo es preparar datos de sensores del Sitio 3 del Terminal Puerto Coquimbo mediante procesamiento distribuido. El notebook levanta una sesión de Spark, compara formas de leer datos, estudia su calidad, demuestra problemas de distribución y de joins, y entrega telemetría limpia y etiquetada para la Fase 3.

Hay **dos conjuntos de datos distintos**. No se concatenan ni se convierten uno en otro:

| Conjunto | Origen y contenido | Uso en el notebook |
|---|---|---|
| `data/raw/*.jsonl` | 10.000.014 eventos del receptor TCP; cuatro archivos, aproximadamente 1,8 GB decimales | Ingesta a escala, esquemas, evaluación perezosa y conversión a Parquet |
| `salida_sitio3/telemetria.parquet` | 6.395.325 lecturas del simulador entre el 12 y el 18 de enero de 2026 | Perfilado, limpieza, sesgo, joins y salida final |
| `salida_sitio3/verdad_terreno.parquet` | Nueve fallas conocidas que el simulador introdujo | Asignar etiquetas correctas a las lecturas del simulador |

El flujo tiene dos ramas:

```text
Crudo JSONL → lectura con esquema → Parquet bronze → perfilado del crudo

Telemetría del simulador → perfilado → limpieza → experimentos de Spark
                                             ↓
Verdad de terreno ───────────────────→ etiquetado temporal
                                             ↓
                         Parquet limpio por fecha → Fase 3
```

**En tus palabras:** «Usamos un conjunto grande para estudiar la lectura y otro con fallas conocidas para estudiar la limpieza y el etiquetado. Al final dejamos una tabla que la siguiente fase podrá usar para evaluar un detector».

## Vocabulario básico para leer el código

| Término | Qué significa en este proyecto |
|---|---|
| Apache Spark | Motor que distribuye operaciones sobre datos entre procesos de ejecución |
| PySpark | Interfaz de Python para programar Spark |
| Jupyter / notebook | Documento que combina código ejecutable, resultados y explicaciones |
| Markdown | Formato de texto con títulos, tablas, listas e imágenes; sus celdas explican, no procesan datos |
| Docker / contenedor | Entorno aislado con las dependencias y servicios del laboratorio |
| Clúster | Conjunto coordinado de nodos o procesos que aportan recursos; aquí se simula con contenedores en un mismo PC |
| Driver | Proceso que ejecuta el programa, prepara planes y coordina las tareas |
| Master | Administrador de recursos del clúster Spark Standalone; registra workers y asigna recursos a las aplicaciones |
| Worker | Servicio de un nodo que ofrece recursos y aloja executors |
| Executor | Proceso de una aplicación Spark que ejecuta tareas y conserva datos reutilizables |
| Core | Recurso de CPU que permite ejecutar trabajo; aquí hay cuatro cores asignados al conjunto de workers |
| DataFrame | Tabla distribuida con columnas y tipos; no equivale a una tabla completa cargada en Python |
| Partición de ejecución | Porción de datos que una tarea procesa dentro de una etapa |
| Job, stage y task | Trabajo disparado por una acción, etapa de ese trabajo y tarea sobre una partición; una acción puede dar lugar a varios jobs |
| Esquema | Nombres, tipos y metadatos de las columnas |
| JSONL | Archivo de texto con un objeto JSON por línea |
| Telemetría | Mediciones registradas por sensores a lo largo del tiempo |
| Entidad | Equipo o elemento observado: faja, grúa, reefer, báscula, etc. |
| Reefer | Contenedor refrigerado |
| Alimentador | Circuito de alimentación eléctrica que abastece equipos |
| Verdad de terreno | Registro conocido de qué fallas ocurrieron, dónde y cuándo; sirve como referencia |
| Capa bronze | Copia inicial de los datos, aquí convertida a Parquet sin aplicar la limpieza del simulador |
| `assert` | Comprobación que detiene la ejecución si su condición es falsa |
| `F` | Alias de `pyspark.sql.functions`; permite construir expresiones distribuidas como `F.avg` o `F.col` |
| `F.col`, `F.lit`, `alias`, `cast` | Referenciar una columna, crear un literal, nombrar un resultado y convertir su tipo |
| `groupBy(...).agg(...)` | Agrupar filas por claves y calcular resúmenes como conteos, mínimos o promedios |
| `show`, `first`, `collect`, `toPandas` | Obtener resultados en el driver: una muestra, una fila, todas las filas o una tabla pandas, respectivamente |

Dos distinciones fundamentales: una **partición de ejecución** no es lo mismo que una **carpeta de almacenamiento por fecha**; y `sensor_confiable` no significa lo mismo que `en_falla`. Un sensor confiable puede medir una falla real del proceso.

## Recorrido detallado: celdas 1 a 23, entorno e ingesta

### Celda 1 — Portada e índice [Markdown]

Presenta el proyecto, indica que debe ejecutarse en el Jupyter del clúster y relaciona las ocho implicancias con las secciones del notebook. Sirve como mapa durante la exposición. No crea una sesión ni carga datos.

**En tus palabras:** «Este índice muestra dónde demostramos cada tema que pide la rúbrica».

### Celda 2 — Contexto de la guarda de entorno [Markdown]

Explica por qué se debe comprobar el entorno: puede haber otro Jupyter de la Fase 1 que carece de Spark o de la configuración del clúster.

**En tus palabras:** «Antes de procesar, verificamos que abrimos el notebook en el entorno correcto».

### Celda 3 — Comprobación del entorno [Código, In 1]

Importa `os`, `shutil` y `sys`. Construye una lista de problemas: comprueba si existe `/opt/spark`, si Java está disponible mediante `shutil.which('java')` y si PySpark se importa desde la instalación esperada. Si encuentra problemas, los imprime y termina con `SystemExit`. Si todo está bien, muestra Python, Java y la ruta de PySpark.

La salida guardada indica Python 3.10.12 y el entorno correcto. Java es necesario porque Spark utiliza la JVM, la máquina virtual de Java. Esta celda valida el entorno local del driver; todavía no demuestra que los workers estén disponibles.

**En tus palabras:** «Esta celda evita que confundamos un problema de instalación con un problema de nuestro código».

### Celda 4 — Comunicación del driver [Markdown]

Introduce `spark.driver.host` y `spark.driver.bindAddress`. El primero anuncia a los executors un nombre alcanzable, `jupyter`; el segundo indica que el driver escuche en todas las interfaces del contenedor, `0.0.0.0`.

**En tus palabras:** «Los executors necesitan saber cómo comunicarse de vuelta con el notebook».

### Celda 5 — Crear la sesión y comprobar executors [Código, In 2]

Importa herramientas de tiempo, JSON, expresiones regulares, estadísticas, identificadores únicos, consultas HTTP, pandas y las funciones y tipos de Spark. `SparkSession.builder` configura el nombre de la aplicación, el master, la dirección del driver y la memoria. `getOrCreate()` obtiene una sesión existente o crea una nueva.

Después obtiene el `SparkContext`, consulta al master cuántos workers están vivos y espera hasta 60 segundos a que se registren los executors. Resta uno al registro de memoria porque también aparece el driver. Dos aserciones impiden seguir si no hay executors o faltan respecto de los esperados. Finalmente define `CORES` e inicializa el diccionario de mediciones `M`.

La salida muestra Spark 4.0.1, **dos executors y paralelismo cuatro**. La expectativa de un executor por worker corresponde a esta configuración del laboratorio; worker y executor siguen siendo conceptos diferentes.

**En tus palabras:** «Nos conectamos al clúster y comprobamos que realmente tenemos los dos executors para repartir el trabajo en cuatro tareas simultáneas».

### Celda 6 — Presupuesto de memoria [Markdown]

Explica el cálculo que pide la rúbrica: la memoria destinada a workers y driver debe quedar bajo la RAM disponible para Docker, dejando margen para otros procesos.

**En tus palabras:** «No basta con pedir memoria: debemos demostrar que la configuración cabe en nuestra máquina».

### Celda 7 — Medir y justificar los recursos [Código, In 3]

`a_gb()` interpreta los tamaños de configuración expresados en `m` o `g`. La celda lee `/proc/meminfo`, consulta los workers vivos al master y suma su memoria junto con la del driver. Comprueba que la memoria solicitada por el executor cabe en los workers de este perfil y que el presupuesto total no supera la RAM visible.

Resultado: **2 workers × 2 GB + 2 GB del driver = 6 GB**, frente a **15,6 GB** visibles para el entorno Docker/WSL. Quedan aproximadamente 9,6 GB de margen. Se conserva el perfil de cuatro cores para mantener comparables los experimentos.

Este cálculo es un presupuesto simplificado, no una medición del consumo total: también existen memoria adicional de los procesos, Jupyter y el sistema. La lectura de `/proc/meminfo` describe este entorno; no es una regla universal para descubrir límites de cualquier contenedor.

**En tus palabras:** «Elegimos una configuración conservadora que cabe con margen y nos permite comparar todas las pruebas con los mismos recursos».

### Celda 8 — Arquitectura y riesgo de `collect()` [Markdown]

Explica el papel de driver, master y workers e incluye el diagrama, la prueba de humo y la UI del master. Las capturas se identifican como históricas. La prueba de humo debe correrse antes de abrir la sesión que ocupa los recursos del laboratorio.

También explica por qué traer millones de filas con `collect()` puede saturar la memoria del driver o superar su límite de resultados. El driver sí procesa el programa y pequeños resultados; el volumen distribuido se trabaja en los executors.

**En tus palabras:** «Repartimos los datos entre executors, pero si al final los traemos todos al notebook volvemos a concentrarlos en una sola memoria».

**Precisión para la exposición:** añadir contenedores en este PC no crea RAM ni CPU física adicional. El laboratorio demuestra la arquitectura; el escalado horizontal de capacidad requiere agregar recursos reales, por ejemplo otras máquinas.

### Celda 9 — Introducción a las mediciones [Markdown]

Presenta las herramientas para medir tiempos, reconocer intercambios en los planes y consultar métricas de tareas. La idea es que cada afirmación de rendimiento tenga evidencia y que el traslado de todas las filas al driver no distorsione el experimento.

**En tus palabras:** «Antes de comparar técnicas, dejamos preparada una forma consistente de medirlas».

### Celda 10 — Funciones auxiliares [Código, In 4]

Esta celda define funciones; al definirlas no ejecuta todavía todos los experimentos. Sus responsabilidades son:

| Función o variable | Explicación |
|---|---|
| `medir(df, reps=3)` | Ejecuta una escritura `noop`, que consume el resultado sin generar un dataset útil ni devolver todas las filas al driver. Cronometra las repeticiones y retorna su mediana redondeada |
| `plan_fisico(df)` | Obtiene el plan físico desde la JVM y oculta las ramas internas bajo `InMemoryRelation`, para no confundir la preparación del caché con la consulta estudiada |
| `mostrar_plan(df)` | Imprime ese plan de forma legible |
| `contar_exchanges(df)` | Busca en el texto operadores de redistribución y cuenta por separado los `BroadcastExchange` |
| `ultima_etiqueta` | Guarda la última identificación de cada experimento |
| `ejecutar_en_grupo(grupo, df)` | Asigna una etiqueta con UUID, ejecuta el DataFrame con `noop`, mide la duración y restaura el grupo de jobs en un `finally` |
| `tareas(grupo)` | Consulta la API de Spark: obtiene jobs, etapas e intentos; evita contar una etapa repetida y conserva tareas exitosas |
| `resumen_etapa_shuffle(grupo)` | Selecciona la etapa con mayor volumen leído de shuffle y resume duración mediana, máxima, cociente y filas por tarea |

La pausa de dos segundos permite que la UI registre métricas; está después del cronometraje. `max(mediana, 1)` evita dividir por cero. `tareas_con_shuffle` solo cuenta tareas que leyeron registros de shuffle, no necesariamente todas las tareas de la etapa. El conteo por expresiones regulares es una ayuda para estos planes: no es una medición de bytes de red ni una descripción infalible de cualquier plan adaptativo.

**En tus palabras:** «Medimos consultas sin descargar los millones de registros al notebook. También miramos cada tarea, porque el tiempo total puede ocultar que una sola se está atrasando».

### Celda 11 — Ingesta y comparación de esquemas [Markdown]

Presenta los cuatro JSONL e introduce dos alternativas: dejar que Spark descubra los tipos o proporcionarle un esquema. En la lectura usada aquí, inferir agrega un recorrido de los datos antes del procesamiento posterior.

**En tus palabras:** «Si ya conocemos la estructura, podemos evitar que Spark tenga que descubrirla recorriendo los archivos».

### Celda 12 — Leer con esquema inferido y declarado [Código, In 5]

Define `RAW` y un `StructType` con diez `StructField`. Cada campo declara nombre, tipo y si admite nulos. Se utiliza `TimestampType` para la fecha y hora, `DoubleType` para el valor, `LongType` para identificadores numéricos y texto para las categorías.

Mide por separado la creación del DataFrame y su `count()` con ambas estrategias. Verifica que los conteos coincidan, imprime tiempos y guarda los resultados en `M`.

| Estrategia | `spark.read` | `count` | Total |
|---|---:|---:|---:|
| Inferida | 17,14 s | 11,53 s | 28,67 s |
| Declarada | 0,16 s | 10,77 s | 10,93 s |

Ambas cuentan **10.000.014 registros**. El beneficio observado es aproximadamente 2,6 veces respecto del tiempo total. La lectura declarada aún tiene preparación y acceso a metadatos; lo que evita es el recorrido para inferir tipos.

**En tus palabras:** «Las dos opciones leyeron la misma cantidad de filas. La declarada tardó menos porque le dimos la estructura desde el comienzo».

### Celda 13 — Comparar tipos obtenidos [Código, In 6]

Recorre `schema.fields` e imprime cada nombre y su tipo mediante `simpleString()`. La diferencia visible es que `timestamp` queda como `string` con la inferencia y como `timestamp` con el esquema declarado.

**En tus palabras:** «El esquema también mejora la interpretación: la fecha queda como fecha y hora, no como una cadena de texto».

### Celda 14 — Interpretación del esquema [Markdown]

Relaciona la diferencia de tiempo con la pasada adicional de inferencia y explica la estabilidad de tipos. Un esquema declarado no garantiza que todos los valores sean válidos; por eso se inspeccionan nulos y problemas de conversión después de leer.

**En tus palabras:** «Definir tipos da un contrato estable, pero todavía debemos revisar si los datos cumplen ese contrato».

### Celda 15 — Transformaciones y acciones [Markdown]

Define las transformaciones como pasos que construyen una consulta y las acciones como solicitudes que disparan el trabajo necesario para un resultado. La evaluación perezosa permite optimizar antes de ejecutar.

**En tus palabras:** «Primero describimos qué queremos hacer y luego una acción pide el resultado».

### Celda 16 — Demostración de evaluación perezosa [Código, In 7]

Construye `alarmas` con tres transformaciones: filtra `status = 'ALARM'`, añade `value_f` mediante una fórmula y selecciona tres columnas. Mide cuánto tarda construir esa consulta, muestra `explain()` y luego cronometra `count()`.

La construcción tarda **0,204 s** y el conteo **11,02 s**, con **2.198 alarmas**. En el plan aparecen `FileScan`, `Filter`, `Project`, `PushedFilters` y cuatro columnas de lectura.

La expresión `value * 9 / 5 + 32` es una demostración de columna calculada; no debe presentarse como una conversión válida para cualquier métrica. En este crudo las alarmas observadas corresponden a temperatura, algo que se confirma después.

**En tus palabras:** «Crear los pasos fue rápido porque aún no se había hecho el procesamiento de las filas. Al pedir el conteo apareció el costo de leer y filtrar».

### Celda 17 — Qué demuestra el plan y qué ejecuta el conteo [Markdown]

Explica que Spark puede adelantar filtros y descartar columnas innecesarias. En JSON aún debe recorrer el texto; en un formato columnar puede evitar leer columnas enteras.

La precisión clave es que **`count()` no necesita calcular `value_f`**. Spark optimiza la consulta para la acción concreta. El plan de `alarmas.explain()` describe la consulta que produce las columnas; no prueba que el conteo haya calculado todas ellas.

**En tus palabras:** «Spark no ejecuta operaciones inútiles para el resultado pedido: para contar alarmas necesita el estado, pero no la conversión del valor».

### Celda 18 — Particiones de lectura [Markdown]

Introduce cómo los archivos se dividen en fragmentos y cómo se agrupan para formar particiones de lectura. Cada tarea procesa una partición de su etapa.

**En tus palabras:** «Las particiones son los paquetes de trabajo que Spark reparte».

### Celda 19 — Tamaños, bloques y particiones reales [Código, In 8]

`glob` encuentra archivos; `os.path.getsize` suma bytes; `math.ceil` calcula bloques aproximados por archivo considerando 128 MiB. La celda contrasta esa estimación con `raw.rdd.getNumPartitions()` y la relaciona con los cuatro cores.

Muestra cuatro archivos, 16 fragmentos previos al empaquetamiento y **15 particiones reales**. Dividir 15 entre 4 da 3,75: se necesitan aproximadamente cuatro tandas de trabajo, no quince tareas simultáneas.

Los rótulos del notebook dicen MB/GB, aunque varias conversiones dividen por potencias de 1024; técnicamente corresponden a MiB/GiB. Por eso 1,75 GiB y cerca de 1,8 GB decimales describen el mismo volumen.

**En tus palabras:** «Tener quince particiones no significa tener quince cores. Con cuatro cores las procesamos por tandas».

### Celda 20 — Interpretar las quince particiones [Markdown]

Aclara por qué no basta dividir el tamaño total por 128: Spark considera fragmentos de cada archivo y puede agrupar fragmentos pequeños. Los cuatro archivos producen 16 trozos y el empaquetamiento da 15 particiones en esta lectura.

**En tus palabras:** «El reparto depende también de cómo están organizados los archivos, no solo de cuántos bytes suman».

### Celda 21 — Introducción a la capa bronze [Markdown]

Propone convertir el crudo a Parquet para que las consultas siguientes no vuelvan a pagar el parseo de JSON. Parquet organiza datos por columnas y utiliza compresión.

**En tus palabras:** «Pagamos una conversión inicial para abaratar las lecturas que vienen después».

### Celda 22 — Convertir y comparar JSON con Parquet [Código, In 9]

Escribe `raw` como `bronze_raw.parquet` con `mode('overwrite')`, que reemplaza esa salida si ya existía. Relee el Parquet, calcula su tamaño y compara la misma agregación: promedio de `value` por `metric`.

La conversión tarda **27,5 s**. Los tamaños mostrados bajan de **1.791 a 22** en las unidades usadas por el notebook. La consulta tarda **13,7 s en JSON** y **1,4 s en Parquet**. La medición de JSON usa una repetición y la de Parquet dos; es evidencia del laboratorio, no un benchmark exhaustivo.

**En tus palabras:** «Conservamos la información en otro formato y conseguimos una lectura más pequeña y rápida para esta consulta».

### Celda 23 — Interpretar la mejora de Parquet [Markdown]

Relaciona la mejora con leer solo `metric` y `value`, y con la compresión de columnas donde muchos valores se repiten. La gran reducción observada depende del contenido de estos datos; no hay que prometer ese mismo factor para cualquier archivo.

**En tus palabras:** «Ganamos porque la consulta usa dos columnas y porque estos datos tienen mucha repetición aprovechable para comprimir».

## Recorrido detallado: celdas 24 a 46, perfilado y limpieza

### Celda 24 — Perfilar antes de limpiar [Markdown]

Presenta las preguntas del diagnóstico: cuántos nulos hay, si existen duplicados, qué rangos tienen los valores y cómo se distribuyen entre sensores y estados. Establece que cada modificación debe responder a evidencia.

**En tus palabras:** «Antes de borrar algo, debemos entender si realmente es un error».

### Celda 25 — Nulos y duplicados del crudo [Código, In 10]

Cuenta filas y calcula nulos con `isNull().cast('int')`: cada nulo aporta uno y cada valor presente aporta cero. La suma por columna produce una tabla pequeña que puede convertirse a pandas.

Comprueba que no haya timestamps nulos. Después calcula duplicados restando al total el número de filas tras `dropDuplicates()`, primero con todas las columnas y luego con la clave `timestamp, sensor_id, metric`. Los resultados son **cero nulos y cero duplicados** en ambas comprobaciones.

**En tus palabras:** «No decidimos que el crudo estaba limpio por mirar cinco filas; lo comprobamos con conteos sobre el conjunto completo».

### Celda 26 — Rangos y composición del crudo [Código, In 11]

Agrupa por métrica y unidad para calcular cantidad, mínimo, máximo y promedio. Agrupa por tipo de activo para contar sensores, lecturas y alarmas. Finalmente obtiene fechas mínima y máxima y sensores distintos con una agregación global seguida de `first()`.

Muestra cinco métricas, **69 sensores** y un periodo del 24 de agosto al 2 de septiembre de 2026. `first()` trae una única fila de resumen. Los promedios por métrica conservan una unidad interpretable; no es lo mismo que mezclar todas las variables indiscriminadamente.

**En tus palabras:** «Revisamos que las unidades y los rangos tengan sentido y entendemos qué equipos aportan los datos».

### Celda 27 — Inspección de alarmas [Código, In 12]

Filtra `ALARM`, agrupa por tipo de activo y métrica y calcula conteos y extremos. Las **2.198 alarmas** son temperaturas de reefers, entre −15 y −8,51 °C según el redondeo mostrado.

**En tus palabras:** «Una alarma puede ser una lectura válida de una condición problemática del equipo. No significa automáticamente que el dato esté mal».

### Celda 28 — Estados y distribución por sensor [Código, In 13]

Cuenta estados, desglosa `WARN` por equipo y métrica y compara sensores con muchas y pocas lecturas. Guarda conteos en `M`. Resultados: **9.992.911 OK**, **4.905 WARN** y **2.198 ALARM**.

El distinto volumen por sensor puede responder a variables o frecuencias de registro diferentes. No se igualan conteos artificialmente. Las tablas ayudan a interpretar el origen de la desigualdad.

**En tus palabras:** «Los sensores no tienen por qué producir la misma cantidad de filas. Primero vemos cómo registra cada equipo».

### Celda 29 — Conclusión del perfilado del crudo [Markdown]

Concluye que los controles aplicados no encontraron problemas que justifiquen eliminar filas. Conserva `WARN` y `ALARM` porque son información útil para estudiar anomalías. Esta conclusión se refiere a las comprobaciones realizadas, no a una garantía de perfección de cualquier aspecto del dataset.

**En tus palabras:** «Limpiar con criterio también puede significar no modificar nada cuando las verificaciones no encuentran un defecto».

### Celda 30 — Cambio al dataset del simulador [Markdown]

Presenta siete días de telemetría y nueve fallas inyectadas. Desde aquí cambia el origen de los datos: los 6,4 millones de registros del simulador no son el resultado de filtrar los diez millones de JSONL.

**En tus palabras:** «Ahora pasamos a los datos donde conocemos las fallas reales, para estudiar cómo preparar y etiquetar las lecturas».

### Celda 31 — Cargar telemetría y verdad de terreno [Código, In 14]

Lee dos rutas Parquet, cuenta telemetría, imprime su esquema, muestra las carpetas diarias y ordena las fallas por inicio. Resultado: **6.395.325 lecturas**, siete carpetas y nueve eventos de falla.

La verdad de terreno incluye identificador, tipo, entidad o alimentador afectados, inicio, término y severidad. Es la referencia para etiquetar, no un resultado inferido por un modelo.

**En tus palabras:** «Tenemos las mediciones por un lado y el registro de las fallas introducidas por otro. Después los relacionaremos por equipo y tiempo».

### Celda 32 — Introducción a partition pruning [Markdown]

Explica que guardar por fecha permite descartar carpetas antes de leer sus registros. En el plan aparece como `PartitionFilters`.

**En tus palabras:** «Si pido un día, Spark puede evitar abrir los datos de los otros días».

### Celda 33 — Medir lectura completa frente a un día [Código, In 15]

Filtra la fecha 14 de enero de 2026 usando un literal convertido a `date`, obtiene el plan y extrae el texto de `PartitionFilters` con una expresión regular. Compara el consumo completo de siete días y de un día mediante `medir()`.

Resultado: **1,01 s frente a 0,30 s**. El filtro de partición en el plan es la evidencia del descarte de carpetas; el cociente de tiempos no tiene que ser exactamente siete.

**En tus palabras:** «Comprobamos en el plan que el filtro aprovecha la organización por fecha, y medimos cuánto cambia la lectura».

### Celda 34 — Interpretación del pruning [Markdown]

Explica que los costos fijos de lanzar tareas siguen existiendo aunque se lean menos datos. A mayor historial, descartar carpetas innecesarias evita mucho más trabajo.

**En tus palabras:** «El beneficio no es solo filtrar el resultado: es evitar leer datos que ya sabemos que no necesitamos».

### Celda 35 — Inicio del perfilado del simulador [Markdown]

Separa el diagnóstico del segundo conjunto de datos. Recuerda que las conclusiones obtenidas sobre el crudo no pueden trasladarse automáticamente al simulador.

**En tus palabras:** «Este conjunto tiene otro origen y necesita su propia revisión».

### Celda 36 — Localizar nulos del simulador [Código, In 16]

Cuenta nulos por columna y después agrupa por `entidad_tipo` para localizar los de `alimentador_id`. Hay **3.290.685 nulos** en esa columna antes de limpiar y cero en las demás mostradas.

Los nulos corresponden a entidades para las que el modelo no registra un alimentador. Reefers y alimentadores sí tienen el dato. El desglose por tipo permite interpretar el nulo, en vez de decidir solo por su cantidad.

**En tus palabras:** «Encontramos muchos nulos, pero todos se explican por el significado de la columna en este modelo».

### Celda 37 — Nulos estructurales [Markdown]

Aclara que `NULL` representa «no aplica» en esas entidades. Rellenar con cero inventaría una relación con un alimentador inexistente. Es una característica de este modelo de datos, no una afirmación general de que las grúas o fajas no usen electricidad.

**En tus palabras:** «No reemplazamos un dato que no corresponde por un número inventado».

### Celda 38 — Calidad del sensor y duplicados exactos [Código, In 17]

Agrupa por `calidad_sensor` y cuenta filas. Después calcula duplicados exactos y muestra los grupos repetidos considerando todas las columnas. Encuentra dos filas sobrantes: estados iniciales de `buque_1` y `sitio_3` registrados dos veces.

Antes de limpiar hay **6.271.106 `ok`**, **123.241 `asentamiento`**, **607 `deriva`** y **371 `pegado`**. «Dos duplicados» significa que se eliminará una copia sobrante en cada uno de los dos grupos, no ambas filas de cada grupo.

**En tus palabras:** «Aquí sí identificamos dos repeticiones exactas que no aportan información nueva».

### Celda 39 — Poner a prueba una posible clave única [Código, In 18]

Prueba la combinación `timestamp_utc, entidad_id, variable`. Calcula cuántas filas desaparecerían al deduplicar por esa clave, agrupa las claves repetidas y muestra una muestra de la báscula.

El conteo da **109.982 filas sobrantes bajo esa regla**, pero incluye **109.980 muestras válidas** además de los dos duplicados exactos. Hay hasta once lecturas de peso distintas en el mismo segundo. La resolución temporal guardada no permite identificarlas individualmente con esa clave.

**En tus palabras:** «Descubrimos que nuestra supuesta clave única no era única: la báscula puede medir varias veces dentro del mismo segundo».

### Celda 40 — Por qué no deduplicar por clave [Markdown]

Explica que las mediciones de la curva de asentamiento tienen información distinta aunque compartan instante, entidad y variable. Deduplicar por esos campos borraría muestras válidas y conservaría una de forma no justificada.

**En tus palabras:** «Que dos filas compartan una clave elegida por nosotros no demuestra que representen la misma medición».

### Celda 41 — Revisar rangos por variable [Código, In 19]

Agrupa por variable y unidad y muestra conteo, mínimo y máximo. Permite revisar temperaturas, velocidad, humedad, peso, potencia y estados sin traer millones de filas al driver.

**En tus palabras:** «Los resúmenes nos dejan contrastar cada variable con su significado físico».

### Celda 42 — Valores negativos válidos [Markdown]

Interpreta dos ejemplos: la potencia de −5 kW representa frenado regenerativo de la grúa y `fase_actual = -1` representa un código de grúa detenida. Un valor negativo solo es incorrecto si viola el dominio de esa variable.

**En tus palabras:** «No podemos borrar todos los negativos: algunos describen estados válidos del sistema».

### Celda 43 — Distribución por entidad [Código, In 20]

Agrupa por `entidad_id`, calcula cantidad y porcentaje y ordena de mayor a menor. Produce `por_entidad`, que se reutiliza para estudiar sesgo. **`faja_1` concentra 3.024.000 filas, el 47,28 %**.

**En tus palabras:** «Casi la mitad del trabajo corresponde a una sola entidad. Eso anticipa un problema si repartimos únicamente por entidad».

### Celda 44 — Reglas de limpieza [Markdown]

Documenta las decisiones antes de aplicarlas: eliminar duplicados exactos, preservar muestras por clave, marcar calidad, conservar nulos estructurales, compatibilizar tipos de alimentador y validar dominios.

**En tus palabras:** «Cada cambio responde a un problema concreto que ya medimos».

### Celda 45 — Aplicar limpieza y comprobarla [Código, In 21]

Construye `limpio` mediante `dropDuplicates()` sobre todas las columnas. Convierte `alimentador_id` a entero y crea `sensor_confiable = (calidad_sensor == 'ok')`. Convierte también `alimentador_afectado` en la verdad de terreno para facilitar una comparación coherente.

Cuenta valores fuera de tres dominios: temperatura entre −40 y 60 °C, humedad entre 0 y 100 % y velocidad no negativa. Estos controles no cubren todos los dominios posibles. Después solicita caché y lo materializa con `count()`, para reutilizar los datos en los experimentos.

Comprueba el conteo esperado, ausencia de valores fuera de esos rangos, ausencia de nulos en cinco columnas obligatorias y que las categorías de calidad pertenezcan al conjunto permitido. El `collect()` trae solo las cuatro categorías distintas, no toda la telemetría. Los nulos se verifican aparte porque una comparación con `NULL` no se comporta como verdadero o falso ordinario.

Resultado: **6.395.323 filas** y **124.219 marcadas como no confiables**. `cache()` permite reutilizar particiones; el nivel observado admite memoria y disco, no promete que todo resida únicamente en RAM.

**En tus palabras:** «Quitamos dos copias exactas, conservamos las lecturas útiles y añadimos una marca de calidad. Además dejamos controles para detectar si una futura ejecución incumple nuestras reglas».

### Celda 46 — Balance de la limpieza [Markdown]

Resume lo que cambió y lo que se preservó, con cifras. Es una buena celda para cerrar oralmente el criterio de calidad: muestra el efecto de cada decisión y no solo el código usado.

**En tus palabras:** «La tabla limpia conserva la historia del proceso y de los sensores. Limpiar no fue borrar todo lo extraño, sino corregir lo demostrablemente redundante y documentar la calidad».

## Recorrido detallado: celdas 47 a 74, distribución y joins

### Celda 47 — Shuffling y operaciones estrechas o anchas [Markdown]

Introduce la redistribución de datos entre particiones. Una operación estrecha como `filter` puede trabajar sobre cada partición por separado. Operaciones como agrupar, ordenar globalmente o ciertos joins necesitan reunir registros de diferentes particiones y suelen provocar shuffle.

El costo puede incluir serialización, archivos intermedios, transferencia y coordinación. No todos los joins requieren mover la tabla grande: el broadcast es precisamente una alternativa. El plan concreto permite comprobarlo.

**En tus palabras:** «Filtrar se puede hacer donde ya está cada fila. Agrupar por una clave obliga a reunir información que estaba repartida».

### Celda 48 — Contar Exchanges de cinco consultas [Código, In 22]

Desactiva temporalmente el broadcast automático para observar un join con shuffle. Construye cinco consultas sobre `limpio`, cuenta sus Exchanges y restaura el parámetro. No cronometra aquí cada consulta; inspecciona sus planes.

| Consulta | Shuffles del plan mostrado |
|---|---:|
| `filter + withColumn` | 0 |
| `groupBy` | 1 |
| `distinct` | 1 |
| `orderBy` | 1 |
| Join de tipo sort-merge | 3 |

Los tres del join incluyen la preparación de la tabla pequeña mediante `distinct`. No son una regla universal de que todo join sort-merge deba tener exactamente tres shuffles. El promedio por entidad de este ejemplo mezcla variables: sirve para observar el plan, no como indicador físico del equipo.

**En tus palabras:** «En vez de adivinar qué operación mueve datos, miramos los Exchanges que Spark planifica para nuestras consultas».

### Celda 49 — Leer el plan de una agregación [Código, In 23]

Imprime el plan de `groupBy('entidad_id').agg(avg('valor'))`. Se interpreta de abajo hacia arriba: lectura del caché, agregación parcial, `Exchange hashpartitioning` y agregación final.

Para calcular un promedio distribuido se pueden combinar suma y cantidad parciales. No se promedian sin más los promedios de particiones de tamaños diferentes. La salida menciona 200 particiones de shuffle y un plan adaptativo todavía no final.

**En tus palabras:** «Spark resume primero dentro de cada partición y después reúne esos resúmenes por entidad. Así puede mover menos información».

### Celda 50 — Problema de las 200 particiones [Markdown]

Explica que un número de particiones excesivo para este volumen y estos cuatro cores crea muchas tareas pequeñas. Doscientas tareas equivalen idealmente a cincuenta tandas con cuatro cores, aunque la ejecución real depende del reparto y de la planificación.

**En tus palabras:** «Más particiones no siempre dan más velocidad. Si el trabajo es pequeño, podemos gastar demasiado en organizarlo».

### Celda 51 — Comparar 200, 8, 16 y AQE [Código, In 24]

Define una función `agregacion` que agrupa por entidad y variable y obtiene promedio, mínimo, máximo y cantidad. Produce **329 grupos** a partir de 6.395.323 filas.

Para cada configuración ajusta particiones y AQE, ejecuta un calentamiento y mide la mediana de tres repeticiones. Consulta las particiones de salida, restaura los parámetros y calcula la mejora de la mejor alternativa manual frente a 200.

| Configuración | Tiempo | Particiones de salida |
|---|---:|---:|
| 200, sin AQE | 4,45 s | 200 |
| 8, sin AQE | 1,08 s | 8 |
| 16, sin AQE | 1,17 s | 16 |
| 200 iniciales, con AQE | 2,59 s | 4 |

Ocho particiones ganan en esta corrida, con aproximadamente **4,1 veces** de mejora respecto de 200. No se demuestra que ocho sea lo óptimo para todos los datos. La medición usa la tabla ya cacheada, por lo que no representa una ingestión completa desde el JSON original.

**En tus palabras:** «Mantuvimos la misma operación y cambiamos cómo se divide el trabajo. Con ocho particiones aprovechamos mejor este clúster pequeño».

### Celda 52 — Gráfico de tiempos [Código, In 25]

Usa matplotlib para representar `res_part` con barras horizontales y tiempos anotados. Guarda `grafico_particiones.png` y muestra el gráfico dentro del notebook. No vuelve a medir las consultas: visualiza resultados calculados antes.

**En tus palabras:** «Cada barra representa la misma agregación con una configuración distinta; una barra más corta significa menos tiempo en esta prueba».

### Celda 53 — Interpretación de las particiones [Markdown]

Relaciona los tiempos con la sobrecarga de muchas tareas diminutas y con el paralelismo disponible. Entre dos y cuatro veces los cores es un punto de prueba de este laboratorio, no una receta universal: también importan tamaño en bytes, complejidad, memoria y distribución.

Explica además que AQE puede combinar particiones pequeñas al leer el shuffle, pero esa adaptación tiene costos y no garantiza ganar a una configuración manual adecuada.

**En tus palabras:** «Buscamos suficientes tareas para ocupar los cores, pero no tantas que coordinarlas cueste más que procesarlas».

### Celda 54 — AQE y transición al sesgo [Markdown]

Define Adaptive Query Execution: adaptación del plan usando estadísticas obtenidas durante la ejecución. En la comparación anterior, la evidencia es la reducción de 200 particiones iniciales a cuatro de salida. Luego introduce el problema distinto del sesgo de claves.

**En tus palabras:** «AQE ajusta algunas decisiones al ver el tamaño real del trabajo, pero eso no significa que resuelva automáticamente cualquier desbalance».

### Celda 55 — Cuantificar la concentración en `faja_1` [Código, In 26]

Lleva al driver solo las tres entidades con más registros y calcula la mediana del número de filas por entidad. Usa `approxQuantile` con error relativo cero para esa estadística. Compara la mayor entidad con la mediana.

`faja_1` tiene **3.024.000 filas**, frente a una mediana de **30.240**: una relación de **100 a 1**. Esto mide concentración por entidad; todavía no mide duración de tareas.

**En tus palabras:** «La faja aporta cien veces más registros que una entidad típica. Si una sola tarea recibe toda la faja, tendrá mucho más trabajo».

### Celda 56 — Ventanas y straggler [Markdown]

Explica que una etapa debe esperar a su tarea más lenta. Presenta una ventana que calcula diferencia con la lectura anterior mediante `lag`. Una agregación con reducción parcial puede sufrir menos que una ventana que necesita ordenar las filas de cada grupo.

La diferencia entre valores no es una tasa de cambio: para eso hay que dividir por el tiempo transcurrido. Además, las muestras de báscula con el mismo timestamp requieren un criterio de desempate si se quiere un orden determinista.

**En tus palabras:** «Para comparar cada lectura con la anterior necesitamos ordenar su serie. Ahí se nota mucho cuando una serie tiene millones de filas».

### Celda 57 — Comparar dos claves de ventana [Código, In 27]

Fija 32 particiones y desactiva la fusión adaptativa de particiones para observar el reparto. La función `diferencia_con_anterior` crea una ventana con `Window.partitionBy(...).orderBy('timestamp_utc')` y calcula `valor - lag(valor)`.

Ejecuta primero con `entidad_id` y luego con `entidad_id, variable`. Recupera las métricas de la etapa de shuffle principal en cada caso y las guarda.

| Métrica | Solo entidad | Entidad y variable |
|---|---:|---:|
| Tiempo total | 10,93 s | 12,09 s |
| Tareas con lectura de shuffle | 31 | 32 |
| Mediana de duración | 371 ms | 561 ms |
| Máxima duración | 5.222 ms | 4.765 ms |
| Máximo / mediana de duración | 14,1 | 8,5 |
| Máximas filas en una tarea | 3.175.200 | 725.760 |

La segunda clave mejora el reparto y evita mezclar variables con unidades diferentes. **No reduce el tiempo total en esta ejecución**. Tampoco es una comparación de dos cálculos semánticamente idénticos: la primera ventana puede restar una corriente a una velocidad; la segunda separa series de una misma variable.

El máximo de filas por tarea puede superar las de `faja_1`, porque una partición hash puede recibir otras claves. Treinta y una tareas con shuffle no significa que solo existieran 31 particiones configuradas.

**En tus palabras:** «Separar por entidad y variable tiene más sentido y reduce la carga máxima por tarea. En esta corrida el total tardó un poco más, así que nuestra evidencia principal es el mejor reparto».

### Celda 58 — Gráfico de duraciones por tarea [Código, In 28]

Ordena las tareas de cada experimento por duración y dibuja una barra por tarea. Guarda `grafico_straggler.png`. El eje horizontal representa tareas ordenadas por duración, no la evolución temporal del job.

**En tus palabras:** «La barra que sobresale muestra una tarea mucho más lenta que el resto. El segundo gráfico permite ver cómo cambia esa desigualdad».

### Celda 59 — Interpretación del experimento de ventanas [Markdown]

Explica la reducción del máximo de filas y del cociente de duraciones. Reconoce que el tiempo total varía entre corridas y que la clave fina no ganó en la ejecución guardada.

Conviene distinguir lo reproducible del reparto para estos datos de las duraciones sensibles a carga, cachés y recursos. El cociente de duraciones también puede variar; no es tan estable como el conteo de filas por tarea.

**En tus palabras:** «Mejorar la distribución es importante, pero para afirmar que algo fue más rápido debo mirar el tiempo medido, no asumirlo».

### Celda 60 — Evidencia del straggler en Spark UI [Markdown]

Incluye una captura histórica de Stages y explica qué mirar: máximo frente a mediana de duración, filas leídas del shuffle y spill. La captura muestra una mediana de 100.800 filas y un máximo de 3.175.200, consistente con el patrón estudiado.

Sus tiempos pertenecen a otra ejecución. `Spill (memory) = 384 MiB` y `Spill (disk) = 39,4 MiB` describen el mismo derrame con representaciones diferentes, no dos volúmenes que deban sumarse. El spill ocurre cuando estructuras de ejecución se vuelcan a disco por presión de memoria.

**En tus palabras:** «En la UI podemos comprobar que una tarea recibió mucho más trabajo y llegó a usar disco. La captura respalda el diagnóstico, pero no mezcla sus tiempos con los de nuestra tabla actual».

### Celda 61 — Introducción al salting [Markdown]

Explica una técnica para dividir una clave dominante: añadir a cada fila grande un número entre cero y siete y replicar la tabla pequeña para cada número. El join usa ahora entidad y sal. No basta con asignar sales aleatorias independientes a ambos lados: se perderían coincidencias.

**En tus palabras:** «Dividimos artificialmente una clave grande en varias subclaves, cuidando que cada fila siga encontrando su correspondencia».

### Celda 62 — Join normal, con sal y con AQE skewJoin [Código, In 29]

Construye `dim_activos` con una fila por combinación de entidad y tipo y una zona: `patio` para reefers y `frente_atraque` para los demás. Desactiva el broadcast automático y el tratamiento adaptativo de skew para medir primero el join normal.

Después crea `sal` con `F.rand(seed=7)`, multiplica por ocho y convierte a entero. Replica la dimensión mediante `crossJoin` con ocho números. Une por entidad y sal y elimina la columna auxiliar.

En el tercer experimento activa `skewJoin` de AQE y baja los umbrales para que el volumen del laboratorio permita observarlo: 4 MB de umbral, factor dos y tamaño orientativo de 8 MB. No deja exactamente la configuración por defecto. Finalmente comprueba el conteo del join normal y del salado, restaura varios parámetros y muestra métricas.

| Variante | Tiempo | Máximas filas por tarea | Máximo / mediana de duración |
|---|---:|---:|---:|
| Normal | 18,30 s | 3.175.206 | 15,3 |
| Salting, ocho sales | 9,47 s | 523.474 | 4,2 |
| AQE skewJoin ajustado | 6,14 s | 413.324 | 3,1 |

La aserción confirma que los joins normal y salado conservan el número de filas. Por sí sola no demuestra igualdad de todos los valores. Ocho sales crean ocho subclaves potenciales por entidad, no garantizan ocho tareas exactas: las subclaves se asignan a las particiones disponibles.

**En tus palabras:** «Con sal y con AQE repartimos la clave pesada entre más trabajo paralelo. En esta prueba mejoraron tanto las filas máximas por tarea como el tiempo total».

### Celda 63 — Costos y límites de salting y AQE [Markdown]

Explica que salting no es gratis: se generan claves y se replica la dimensión. Compensa cuando el sesgo es suficientemente costoso. AQE detecta y divide particiones sesgadas en joins compatibles usando estadísticas y umbrales; no añade literalmente la columna `sal` que creamos a mano ni arregla todas las ventanas.

**En tus palabras:** «Ambas técnicas buscan repartir la carga, pero tienen mecanismos y costos distintos. En nuestro ejemplo comprobamos que el resultado no aumentara de tamaño».

### Celda 64 — Introducción al broadcast join [Markdown]

Presenta otra estrategia: si una tabla es pequeña, distribuir una copia a los executors para que cada uno una localmente sus filas de la tabla grande.

**En tus palabras:** «En lugar de mover millones de lecturas para acercarlas a una tabla pequeña, llevamos la tabla pequeña a donde están las lecturas».

### Celda 65 — Comparar sort-merge y broadcast [Código, In 30]

Desactiva los umbrales de broadcast para medir un sort-merge, cuenta Exchanges y cronometra con `medir()`. Luego restaura parámetros y fuerza broadcast mediante `F.broadcast(dim_activos)` para la segunda consulta.

Resultado: **9,30 s, tres shuffles y cero broadcasts** frente a **3,15 s, un shuffle y un broadcast**. El shuffle que queda se usa para obtener la dimensión distinta; no para redistribuir la telemetría en el join.

No se deben mezclar estos tiempos con los de la celda 62: son experimentos con consultas y condiciones distintas.

**En tus palabras:** «Como la dimensión es pequeña, copiarla a cada executor evitó redistribuir la tabla grande y el join fue aproximadamente tres veces más rápido en esta medición».

### Celda 66 — Cuándo elegir cada join [Markdown]

Interpreta por qué la tabla conserva un shuffle y explica la decisión: broadcast si la tabla pequeña cabe con margen en cada executor; sort-merge es una opción cuando ambas son grandes y hay claves de igualdad adecuadas.

El umbral automático mencionado en el notebook es configurable. `F.broadcast` da una indicación explícita, pero no hace que una tabla grande deje de consumir memoria. Broadcast mueve datos por la red; lo que evita aquí es el shuffle de la tabla grande.

**En tus palabras:** «Broadcast funciona bien porque la tabla de referencia es pequeña. Si no cupiera en cada executor, esa misma estrategia podría ser un problema».

### Celda 67 — Comparación de particionado [Markdown]

Presenta `repartition` y `coalesce`: dos operaciones que pueden cambiar el número de particiones de ejecución, con costos y propósitos diferentes.

**En tus palabras:** «Ahora comparamos dos maneras de terminar con menos particiones».

### Celda 68 — Medir repartition frente a coalesce [Código, In 31]

Construye dos variantes que terminan en dos particiones, cuenta shuffles y mide el consumo de sus resultados.

| Operación | Shuffles | Tiempo | Particiones |
|---|---:|---:|---:|
| `repartition(2)` | 1 | 2,89 s | 2 |
| `coalesce(2)` | 0 | 0,78 s | 2 |

`repartition` redistribuye; `coalesce` reduce agrupando particiones existentes sin introducir un shuffle propio. Puede conservar desbalances. «Sin shuffle» no equivale a que toda la ejecución tenga cero transferencias o lecturas remotas.

**En tus palabras:** «Las dos dejaron dos particiones, pero coalesce fue más barato porque no redistribuyó todas las filas».

### Celda 69 — Criterio de elección [Markdown]

Resume el uso práctico: `coalesce` suele ser conveniente para reducir particiones sin redistribuir; `repartition` permite aumentar o cambiar la distribución. Si se vuelve a particionar únicamente por la misma clave dominante, el sesgo de esa clave puede persistir.

**En tus palabras:** «Elegimos según el objetivo: reducir cantidad de particiones o cambiar cómo quedan repartidos los registros».

### Celda 70 — Introducción al etiquetado y fan-out [Markdown]

Define el propósito del join con verdad de terreno: indicar qué falla estaba activa en cada lectura. Eso permitirá evaluar un detector en la Fase 3. La Fase 2 no está entrenando todavía ese detector.

**En tus palabras:** «Necesitamos una referencia correcta para saber después si un detector acertó o se equivocó».

### Celda 71 — Demostrar el error del join ingenuo [Código, In 32]

Hace un `left join` con broadcast usando solo la igualdad de entidad. Cuenta filas e intenta comprobar que el total se conserve. Captura expresamente el `AssertionError` para mostrar el error del ejemplo y continuar con la solución.

El total sube de **6.395.323 a 9.419.323**, un aumento de **3.024.000 filas**. Cada lectura de la faja encuentra dos fallas asociadas a esa entidad. Además, el 100 % de sus lecturas queda asociado a alguna falla, incluso fuera de los intervalos reales.

El uso de `left` conserva las filas sin coincidencia, pero no garantiza conservar el conteo: una fila puede coincidir con varias de la derecha. Este fallo atrapado es intencional, no una celda que quedó sin funcionar.

**En tus palabras:** «El join no inventó nuevas mediciones del sensor; multiplicó sus representaciones porque cada lectura coincidía con más de una falla».

### Celda 72 — Diseñar la condición correcta [Markdown]

Explica tres problemas del join anterior: multiplicación de filas, etiquetas fuera de horario y falta de propagación de fallas del alimentador a sus reefers. Propone combinar alcance del equipo con intervalo temporal.

La condición temporal es **`t_inicio <= timestamp_utc < t_fin`**. Incluye el comienzo y excluye el final porque esa es la convención del simulador.

**En tus palabras:** «Compartir equipo no basta: la falla debe estar activa en el momento de la lectura. También debemos considerar los equipos conectados a un alimentador afectado».

### Celda 73 — Range join y comprobación del resultado [Código, In 33]

Selecciona las columnas necesarias de la verdad de terreno y construye `cond`. Una lectura coincide si corresponde a la entidad afectada **o** comparte un alimentador afectado no nulo, y además está dentro del intervalo de la falla.

Hace `left join` con `F.broadcast(v)`, quita columnas auxiliares y crea `en_falla` según la presencia de `falla_id`. Verifica que se conserven las **6.395.323 filas**, muestra lecturas por falla, imprime el plan y guarda métricas.

Resultados: **436.218 lecturas etiquetadas en falla**. En `faja_1` se etiquetan **424.390 de 3.024.000**, aproximadamente 14 %, frente al 100 % del join ingenuo. La falla F004 afecta a 26 entidades: un alimentador y 25 reefers.

Las etiquetas indican pertenencia al alcance y a la ventana del evento; no prueban que cada variable haya mostrado una anomalía observable. Si varias fallas se superpusieran para una lectura, la condición podría producir varias coincidencias: la aserción detectaría el aumento, pero no decide por sí sola cómo resolverlo.

**En tus palabras:** «Ahora cada lectura se relaciona con la falla que estaba activa en su equipo o alimentador. Conservamos el total y evitamos etiquetar toda la semana como fallida».

### Celda 74 — Interpretar el plan y la falla F005 [Markdown]

Explica que el plan usa `BroadcastNestedLoopJoin`. La condición completa con `OR` y rangos no ofrece aquí una clave simple para el hash join elegido en un equijoin. Al haber solo nueve fallas, comparar cada lectura con esa referencia pequeña es razonable para este caso.

La tabla de lecturas en falla muestra ocho eventos porque **F005 duró aproximadamente 21 segundos**, mientras los equipos afectados se registran cada 60 segundos. Ninguna de sus lecturas cae dentro del intervalo. La falla sigue existiendo en la verdad de terreno; no hay una muestra que pueda recibir esa etiqueta temporal.

**En tus palabras:** «No perdimos la novena falla en el join. Ocurrió entre muestras, así que no había una lectura de los equipos afectados dentro de ese intervalo».

## Recorrido detallado: celdas 75 a 82, salida y cierre

### Celda 75 — Diseño de almacenamiento de la salida [Markdown]

Justifica guardar Parquet por `fecha`, evitando particionar por un timestamp de alta cardinalidad. Introduce `coalesce(1)` para que una tarea escriba las siete particiones diarias de almacenamiento.

El beneficio es evitar muchos archivos diminutos. El costo es concentrar la escritura en una tarea; se considera razonable para unos 51 MiB de salida en este caso, no para cualquier volumen.

**En tus palabras:** «Organizamos por día porque coincide con las consultas esperadas y mantiene un número manejable de carpetas y archivos».

### Celda 76 — Escribir el Parquet limpio [Código, In 34]

Define la ruta final, cuenta timestamps distintos y ejecuta `coalesce(1).write.mode('overwrite').partitionBy('fecha').parquet(SALIDA)`.

Hay **604.800 instantes distintos**: particionar por cada instante produciría una cantidad excesiva de directorios. La escritura registrada tarda **27,2 s**. `overwrite` reemplaza la salida anterior en esa ruta. `partitionBy('fecha')` organiza carpetas; no es la misma operación que `Window.partitionBy`.

Aunque se usa una sola partición de ejecución para escribir, el resultado no es un único archivo para toda la semana: la partición de almacenamiento separa los días. En esta ejecución queda un archivo por día. La escritura puede volver a ejecutar el etiquetado, porque `etiquetada` no se había cacheado como resultado final.

**En tus palabras:** «Una tarea escribe los datos, pero los separa en carpetas por fecha. Así logramos siete archivos útiles en vez de cientos de miles diminutos».

### Celda 77 — Releer y verificar la salida [Código, In 35]

Relee el Parquet recién escrito. Mediante aserciones compara total de filas, distribución diaria, cantidad en falla y cantidad no confiable. Verifica columnas necesarias y tipos de todas las columnas no particionadas. Revisa `fecha` aparte como `DateType`, porque se reconstruye desde los nombres de carpetas.

El `collect()` se aplica a siete conteos diarios, no a los millones de registros. Después recorre directorios e imprime cantidad de archivos, tamaño y filas por día, y muestra el esquema final.

| Día | Archivos Parquet | Filas |
|---|---:|---:|
| 2026-01-12 | 1 | 926.093 |
| 2026-01-13 | 1 | 942.156 |
| 2026-01-14 | 1 | 897.027 |
| 2026-01-15 | 1 | 942.992 |
| 2026-01-16 | 1 | 912.973 |
| 2026-01-17 | 1 | 887.040 |
| 2026-01-18 | 1 | 887.042 |

La salida guardada dice **«Todas las aserciones pasaron»**. Estas pruebas verifican conteos y esquema, entre otros invariantes; no comparan todos los valores fila por fila.

**En tus palabras:** «No dimos por terminada la escritura porque no apareció un error: volvimos a leer y comprobamos que se conservaran los conteos, las marcas y los tipos».

### Celda 78 — Interpretación de la verificación [Markdown]

Resume la salida de siete carpetas y un archivo por día y conecta esa organización con el costo de abrir archivos. Es el cierre de la implicancia de almacenamiento.

**En tus palabras:** «La salida quedó organizada para la siguiente fase y comprobamos que conserva las propiedades que necesitábamos».

### Celda 79 — Encabezado del resumen [Markdown]

Anuncia la consolidación de mediciones. Sirve de transición para reunir los resultados principales, sin volver a ejecutar los experimentos.

**En tus palabras:** «Ahora reunimos las evidencias principales del trabajo».

### Celda 80 — Exportar métricas y mostrar resumen [Código, In 36]

`fmt()` prepara el diccionario `M`, quitando el identificador interno `etapa` de los subdiccionarios si existe. `json.dump` lo guarda como `salida_fase2/metricas.json`. Construye una tabla con conteos, tiempos y comparaciones y la imprime con pandas.

Esta celda guarda mediciones; no guarda otra copia de la telemetría ni vuelve a demostrar independientemente cada afirmación. Las claves `t_8` y `t_16` corresponden aquí a dos y cuatro veces los cuatro cores.

**En tus palabras:** «Guardamos los resultados medidos para poder revisar y explicar la ejecución sin depender de recordar números».

### Celda 81 — Entrega a Fase 3 y capturas [Markdown]

Indica cuál es el producto final: `telemetria_limpia.parquet`, tipado, deduplicado y con calidad y etiquetas. Advierte que las capturas de la UI del driver deben tomarse antes del cierre. Los eventos registrados permiten consultar una ejecución cerrada con el History Server si está habilitado.

**En tus palabras:** «Entregamos datos preparados para la Fase 3 y conservamos evidencia de cómo los procesamos».

### Celda 82 — Liberar la sesión [Código, In 37]

`spark.stop()` detiene la sesión y el contexto asociado, libera los recursos de la aplicación y cierra la UI del driver. Los archivos ya escritos permanecen. No apaga automáticamente todos los contenedores de Docker.

**En tus palabras:** «Terminamos la aplicación Spark para liberar recursos, pero las salidas quedan guardadas».

## Qué exige exactamente la rúbrica en la presentación

La fuente de esta sección es la **página 1, apartados 1 a 4**, y la **página 2, criterios 7 a 9**, del PDF oficial. Las preguntas de práctica que aparecen más adelante son propuestas de estudio: no son una pauta oficial de preguntas del profesor.

| Parte de la evaluación | Peso | Qué se necesita demostrar |
|---|---:|---|
| Trabajo técnico, criterios 1–6 | 60 % | Clúster, ingesta, calidad, shuffling y sesgo, joins, escritura y verificación |
| Notebook como soporte, criterio 7 | 10 % | Contexto, código con resultados, interpretación, imágenes pertinentes y ejecución completa |
| Implicancias para Big Data, criterio 8 | 20 % | Las ocho implicancias explicadas con palabras propias, cada una conectada con un resultado del proyecto y con el problema de trabajar a mayor escala |
| Respuestas individuales, criterio 9 | 10 % | Cada integrante responde con precisión y se apoya en su notebook |

La presentación con el notebook representa **40 %** de la rúbrica. De ese bloque, **30 %** corresponde directamente a la explicación oral y las respuestas; el 10 % restante evalúa el notebook como soporte.

Las condiciones son:

1. **Quince minutos por grupo, incluidas las preguntas.** El informe completo es para estudiar, no para leerlo durante esos quince minutos.
2. Presentar directamente desde `fase2_pyspark.ipynb`; no se exigen diapositivas.
3. Cada integrante expone al menos una implicancia y responde individualmente.
4. Ejecutar el notebook completo con **Restart & Run All** antes de presentar. Si no corre de principio a fin, los criterios 4 a 6 tienen como máximo nivel 2.
5. Respaldar cada afirmación de rendimiento con tiempos, conteos, planes o capturas.
6. Entregar el notebook con salidas visibles y las imágenes externas si se insertaron mediante rutas.
7. Si se aplicó el ejercicio adicional de defectos inyectados, su detección y tratamiento forman parte del criterio de calidad. No se debe afirmar que se hizo un ejercicio adicional sin evidencia.

El criterio 8 alcanza el nivel excelente cuando se explican **las ocho implicancias** con evidencia propia. La rúbrica baja el nivel si faltan implicancias, si el apoyo en resultados es parcial o si se leen definiciones genéricas sin conectarlas con el trabajo. El criterio 9 evalúa a cada integrante: memorizar una frase sin poder interpretar la salida no alcanza el mismo nivel que comprenderla.

**Diferencias de cifras con los ejemplos de la rúbrica:** el PDF menciona 1,3 GB para un crudo y un ejemplo de fan-out de aproximadamente 12,8 a 18,8 millones de filas. Tus archivos muestran otro volumen: aproximadamente 1,8 GB de crudo y un join de **6.395.323 a 9.419.323**. Debes explicar tus mediciones; no reemplazarlas por las cifras ilustrativas del PDF.

## Las ocho implicancias: definición, evidencia y explicación oral

### Implicancia 1 — Procesamiento distribuido y escalado horizontal

**Definición.** Procesar de forma distribuida significa dividir datos y cálculos entre varios procesos o nodos coordinados. Escalar verticalmente es aumentar recursos de una máquina; escalar horizontalmente es sumar nodos con recursos. Una máquina tiene límites de memoria, CPU y disco. La distribución permite trabajar sobre particiones sin cargar el conjunto entero en el driver.

**Qué debes distinguir.** El driver organiza la aplicación; el master administra recursos; los workers ofrecen recursos y alojan executors; los executors ejecutan tareas. El master no reemplaza al driver en la planificación de consultas. Aquí los contenedores comparten un mismo PC, por lo que muestran el funcionamiento de un clúster sin multiplicar la capacidad física por crear contenedores.

**Evidencia propia.** Celdas 5, 7 y 8: dos executors, cuatro cores, presupuesto de 6 GB frente a 15,6 GB, diagrama, prueba de humo y captura del master.

**Por qué importa con Big Data.** La memoria disponible para el conjunto de executors se aprovecha de manera repartida. `collect()` sobre todo el dataset vuelve a concentrar resultados en el driver y puede hacer fallar la aplicación. No se afirma que cada operación deba mantener todos sus datos simultáneamente en RAM: Spark también usa disco y puede recomputar.

**Ejemplo para decirlo:** «Nuestro driver prepara el trabajo y los executors procesan las particiones. En este laboratorio contamos con dos executors y cuatro cores. Si trajéramos los millones de filas con collect, volveríamos a depender de la memoria de un solo driver. Por eso al notebook llegan principalmente tablas resumidas».

### Implicancia 2 — Evaluación perezosa

**Definición.** Una transformación describe una operación pendiente sobre los datos. Una acción solicita un resultado y dispara el procesamiento necesario. Spark usa el plan acumulado para optimizar qué lee, qué filtra y qué calcula.

**Conceptos asociados.** `filter` selecciona filas; `select` selecciona o construye columnas; `withColumn` añade o reemplaza una columna. `count`, `show`, escrituras y `collect` solicitan resultados. `explain` muestra un plan: no demuestra por sí mismo que se ejecutaron todas las filas. La inferencia de esquema es un ejemplo de trabajo que puede comenzar durante la preparación de una lectura.

**Evidencia propia.** Celdas 16 y 17: 0,204 s para construir transformaciones, 11,02 s para contar y 2.198 alarmas. El plan muestra filtros y las columnas requeridas.

**Por qué importa con Big Data.** Evita ejecutar pasos innecesarios o materializar cada resultado intermedio por separado. Spark puede omitir columnas o cálculos que no afectan el resultado pedido.

**Ejemplo para decirlo:** «Al escribir filter y withColumn estamos construyendo una consulta. El procesamiento se activa cuando pedimos un resultado. Esto permite que Spark vea el conjunto de operaciones y quite trabajo innecesario. En nuestro count, por ejemplo, no necesita calcular la columna convertida: solo identificar y contar las alarmas».

### Implicancia 3 — Esquemas e ingesta a escala

**Definición.** Ingestar es incorporar datos desde su almacenamiento al sistema de procesamiento. El esquema define la estructura: columnas y tipos. Un esquema inferido se descubre a partir del contenido; uno declarado se proporciona explícitamente.

**Conceptos asociados.** `StructType` reúne los campos; `StructField` especifica cada campo. `TimestampType` representa fecha y hora, `DoubleType` números con decimales, `LongType` enteros de 64 bits y `StringType` texto. «Permite nulos» no significa «debe tener nulos» ni valida automáticamente toda la calidad del dato.

**Evidencia propia.** Celdas 12 y 13: 28,67 s con inferencia y 10,93 s con declaración, mismo conteo de 10.000.014 registros. `timestamp` queda como texto con la inferencia usada y como timestamp al declararlo.

**Por qué importa con Big Data.** Un recorrido adicional de archivos grandes consume lectura y tiempo. Además, tipos cambiantes pueden romper comparaciones, agregaciones o joins entre ejecuciones. La declaración debe acompañarse de validación de datos mal formados.

**Ejemplo para decirlo:** «Le dimos a Spark una estructura conocida para evitar que la descubriera leyendo los archivos. Obtuvimos el mismo número de registros en menos tiempo y dejamos la fecha tipada desde el inicio. A gran escala, evitar una pasada adicional significa ahorrar mucha lectura».

### Implicancia 4 — Calidad de datos a escala

**Definición.** Perfilar es medir el estado del conjunto antes de modificarlo: nulos, duplicados, dominios, rangos y distribución. Limpiar es aplicar reglas justificadas para corregir o identificar problemas sin destruir información válida.

**Conceptos asociados.** Un duplicado exacto repite todos los campos. Un duplicado por clave repite solo los campos elegidos como identificador; puede ser legítimo si esa clave no representa una medición única. Un nulo estructural significa «no aplica». Un dato degradado contiene información sobre una medición cuya calidad es limitada.

`asentamiento` describe el periodo de estabilización de la báscula; `deriva`, un desplazamiento gradual del sensor; `pegado`, una lectura que queda atascada. No equivalen automáticamente a errores descartables. `WARN` y `ALARM` del crudo son estados de umbral, no la misma columna de calidad del simulador.

**Evidencia propia.** Celdas 25–29 y 36–46: crudo sin problemas encontrados por esos controles; dos duplicados exactos del simulador eliminados; 124.219 lecturas preservadas con `sensor_confiable = false`; nulos de alimentador conservados.

**Por qué importa con Big Data.** No se pueden inspeccionar millones de registros visualmente. Las reglas automáticas tienen gran impacto: una regla equivocada puede eliminar masivamente datos útiles o enseñar al siguiente análisis una visión sesgada.

**Ejemplo para decirlo:** «Primero medimos y después decidimos. Si hubiéramos deduplicado por fecha, equipo y variable, habríamos borrado muestras válidas de la báscula. Por eso quitamos solo dos copias exactas y marcamos las lecturas de menor calidad para que la siguiente fase pueda decidir cómo usarlas».

### Implicancia 5 — Shuffling

**Definición.** Un shuffle redistribuye datos entre particiones para reunir información necesaria en una operación. Una transformación estrecha puede procesar cada partición sin esa redistribución; una ancha puede requerir datos de varias particiones.

**Conceptos asociados.** `Exchange` es un operador de intercambio en el plan. `Exchange hashpartitioning` distribuye por un hash de las claves; `rangepartitioning` distribuye por rangos. `BroadcastExchange` difunde una tabla y no es lo mismo que un shuffle por clave. AQE adapta algunas decisiones usando estadísticas obtenidas durante la ejecución.

**Evidencia propia.** Celdas 48–54: `filter + withColumn` sin shuffle; `groupBy` con uno; 4,45 s con 200 particiones, 1,08 s con ocho, 1,17 s con dieciséis y 2,59 s con AQE.

**Por qué importa con Big Data.** Serializar, transferir y manejar archivos intermedios puede costar más que la aritmética. Demasiadas particiones generan sobrecarga; muy pocas pueden desaprovechar recursos o concentrar demasiado trabajo. El ajuste depende del volumen y la distribución.

**Ejemplo para decirlo:** «Agrupar requiere reunir datos que estaban separados. Esa redistribución tiene un costo. En nuestro clúster, 200 particiones producían demasiadas tareas pequeñas; ocho fueron más rápidas. AQE también mejoró la configuración inicial al combinar particiones pequeñas».

### Implicancia 6 — Sesgo de datos y stragglers

**Definición.** El data skew es un reparto muy desigual de datos o trabajo. Un straggler es una tarea que termina mucho después que sus compañeras. Una etapa no termina hasta que concluyen las tareas necesarias, aunque otros cores ya estén libres.

**Conceptos asociados.** El skew de claves aparece cuando una clave concentra muchas filas. El salting añade subclaves para repartir esa carga; en el ejemplo de join se replica la dimensión para preservar coincidencias. El spill vuelca estructuras a disco cuando la memoria de ejecución no alcanza. AQE skewJoin puede dividir particiones sesgadas en ciertos joins, según configuración y estadísticas.

**Evidencia propia.** Celdas 55–63: `faja_1` aporta 47,28 %; su cantidad de filas es cien veces la mediana por entidad; la ventana tiene una tarea rezagada visible en gráfico y UI. En el join, salting baja la máxima carga de unos 3,2 millones a 523.474 registros leídos por una tarea.

**Por qué importa con Big Data.** Agregar workers puede no resolver una operación que obliga a procesar toda una clave en una tarea. A veces hay que cambiar la clave con sentido, aplicar salting o adaptar el join. No conviene salar indiscriminadamente una ventana temporal: se rompería la continuidad de la serie.

**Ejemplo para decirlo:** «No basta con repartir por cantidad de entidades, porque una de ellas concentra casi la mitad de las filas. Esa clave genera una tarea muy pesada. Mostramos el problema en la UI y probamos formas de dividir el trabajo. En el join salting redujo la carga máxima y también el tiempo; en la ventana mejoró el reparto, pero no el tiempo total de esta corrida».

### Implicancia 7 — Joins distribuidos y etiquetado

**Definición.** Un join relaciona filas de dos tablas según una condición. En un sistema distribuido importa tanto el significado de esa condición como la estrategia física para ejecutarla.

**Conceptos asociados.** Sort-merge reúne y ordena por claves compatibles antes de combinar. Broadcast distribuye una tabla pequeña para unir junto a los datos grandes. Fan-out es la multiplicación de filas por varias coincidencias. Un range join incorpora una condición de intervalo; aquí relaciona lecturas con fallas activas en el tiempo. Un left join conserva las lecturas sin falla dejando nulos en las columnas de la tabla derecha.

**Evidencia propia.** Celdas 65 y 71–74: 9,30 s frente a 3,15 s para estrategias de join; el ingenuo aumenta a 9.419.323 filas; el temporal conserva 6.395.323 y marca 436.218 lecturas en falla.

**Por qué importa con Big Data.** Un join mal definido puede multiplicar millones de registros, aumentar costos y producir etiquetas falsas. Uno correcto pero con una estrategia inadecuada puede transferir demasiados datos. Rendimiento y corrección son comprobaciones distintas.

**Ejemplo para decirlo:** «Usar broadcast hizo eficiente la unión con una referencia pequeña, pero no arreglaba una condición incorrecta. Primero mostramos que unir solo por equipo duplicaba filas. Luego exigimos además que la falla estuviera activa en ese instante y comprobamos que el conteo se conservara».

### Implicancia 8 — Almacenamiento columnar y particionado

**Definición.** Un formato columnar como Parquet organiza datos por columnas dentro de sus archivos, facilitando leer solo las necesarias y comprimir valores similares. Particionar el almacenamiento separa los archivos según valores de una columna, por ejemplo una carpeta por día.

**Conceptos asociados.** Column pruning es descartar columnas no necesarias. Partition pruning es descartar particiones de almacenamiento incompatibles con un filtro. Cardinalidad es la cantidad de valores distintos de una columna. Muchos archivos pequeños generan costos fijos de listado, apertura y planificación. `coalesce` reduce particiones de ejecución sin un nuevo shuffle; `repartition` redistribuye para cambiar su cantidad o composición.

**Evidencia propia.** Celdas 22, 33, 68 y 75–78: Parquet reduce tamaño; `PartitionFilters` evita seis días; `coalesce(2)` no añade shuffle; la salida queda en siete carpetas con un Parquet por día, verificada mediante relectura.

**Por qué importa con Big Data.** Evitar bytes innecesarios es tan importante como repartir cálculos. Una organización por fecha puede ahorrar años de lectura al consultar un día. Particionar por 604.800 timestamps generaría demasiadas carpetas para este caso.

**Ejemplo para decirlo:** «Parquet ayuda a leer las columnas necesarias y las carpetas por día permiten saltarnos fechas completas. Elegimos fecha en vez de timestamp porque queríamos siete particiones útiles, no cientos de miles diminutas. Después releímos la salida para comprobar filas y tipos».

## Preguntas de práctica con respuestas razonadas

**1. ¿Spark es lo mismo que pandas?** No. En este proyecto Spark procesa DataFrames distribuidos. Pandas se usa en el driver para tablas pequeñas de mediciones o resúmenes. Convertir toda la telemetría a pandas volvería a concentrarla en el driver.

**2. ¿Cuántos equipos físicos tenemos?** El laboratorio corre en un PC con contenedores que cumplen distintos roles. Tenemos dos workers y dos executors en esta configuración, pero no dos computadores físicos adicionales.

**3. ¿El driver no procesa nada?** Sí procesa el programa, planes y resultados pequeños. Las tareas que trabajan sobre las particiones distribuidas se ejecutan en los executors.

**4. ¿Por qué aparece collect si dijimos que era un error?** El problema es traer un resultado demasiado grande. Aquí se usa para cuatro categorías de calidad o siete conteos por día. No trae millones de lecturas.

**5. ¿Por qué inferir el esquema cuesta si Spark es perezoso?** Para construir esa lectura JSON con tipos inferidos necesita inspeccionar los datos. La ejecución perezosa no significa que ningún acceso o trabajo pueda suceder antes de un count.

**6. ¿El esquema declarado hace que todos los datos sean correctos?** No. Fija tipos esperados. Después hay que detectar valores mal formados, nulos o fuera de dominio; el notebook realiza controles específicos.

**7. ¿Por qué medir con noop en vez de collect?** Porque interesa el procesamiento distribuido sin añadir el costo de reunir todo el resultado en el driver. `noop` consume el resultado sin generar un dataset final útil.

**8. ¿La mediana elimina toda variación de los tiempos?** No. Reduce la influencia de valores extremos en pocas repeticiones, pero siguen influyendo carga del equipo, cachés y otras condiciones. Por eso se presentan como mediciones de esta ejecución.

**9. ¿Por qué no borrar las alarmas?** Porque describen condiciones que interesa detectar. Borrarlas eliminaría justo parte de los eventos de interés.

**10. ¿Por qué no rellenar alimentador_id con cero?** En esas entidades significa «no aplica». Cero inventaría una asociación que el modelo no tiene.

**11. ¿Por qué 109.982 repeticiones por clave no son 109.982 errores?** La clave elegida no identifica de forma única las muestras de alta frecuencia. De las filas que esa deduplicación eliminaría, 109.980 son muestras válidas y dos son copias exactas.

**12. ¿Sensor confiable significa que el equipo no está fallando?** No. Es calidad de medición. `en_falla` indica que la lectura corresponde al alcance y periodo de una falla conocida. Son dimensiones distintas.

**13. ¿Por qué el caché se activa con count?** `cache()` solicita persistencia. Una acción materializa las particiones que se procesan; aquí `count()` recorre el conjunto y prepara su reutilización.

**14. ¿Dos variables llamadas partitionBy hacen lo mismo?** No. `Window.partitionBy` define grupos para una operación de ventana. `write.partitionBy` organiza directorios de salida según una columna.

**15. ¿Más particiones siempre es mejor?** No. Debe haber suficientes para aprovechar recursos, pero demasiadas generan coordinación excesiva. En esta agregación 200 tardaron 4,45 s y ocho 1,08 s.

**16. ¿AQE siempre será lo más rápido?** No. En la agregación perdió frente a la mejor configuración manual; en el experimento de skewJoin ajustado obtuvo el menor tiempo. El resultado depende del caso.

**17. ¿Por qué el skew se ve menos en un promedio?** Una agregación parcial puede resumir muchas filas en suma y cantidad antes del intercambio. Una ventana necesita conservar y ordenar la serie de filas del grupo, por lo que la concentración puede pesar mucho más.

**18. ¿La ventana por entidad y variable fue más rápida?** No en la ejecución guardada: 12,09 s frente a 10,93 s. Mejoró la carga máxima por tarea y separó variables de forma coherente. Esas son las conclusiones respaldadas.

**19. ¿Salting sirve igual para cualquier operación?** No. En este join funciona replicando la dimensión. Una agregación puede necesitar combinar resultados parciales; una ventana temporal necesita preservar relaciones entre lecturas. Hay que mantener la semántica.

**20. ¿Broadcast significa cero red y cero shuffles en todo el plan?** No. Copia la tabla pequeña por la red. En nuestra comparación queda un shuffle para construir la dimensión con distinct, aunque se evita redistribuir la tabla grande para unirla.

**21. ¿Un left join conserva siempre el número de filas?** Conserva las filas de la izquierda, pero puede multiplicarlas si hay varias coincidencias a la derecha. Nuestro ejemplo ingenuo lo demuestra.

**22. ¿Por qué el fin de la falla no se incluye?** Porque el simulador usa intervalos semiabiertos: la falla está activa desde el inicio y deja de estarlo al llegar al final. El etiquetado debe respetar la misma convención.

**23. ¿Qué pasa con fallas superpuestas?** Una lectura podría coincidir con varias. La aserción detectaría el aumento, pero habría que definir una política: varias etiquetas, prioridad o consolidación. El notebook actual no implementa esa resolución.

**24. ¿Por qué aparece una falla de sensor con más lecturas en falla que lecturas degradadas?** El etiquetado temporal se aplica a las variables de la entidad durante el evento, mientras la marca de calidad puede afectar solo la variable del sensor degradado. No deben esperarse conteos iguales entre esas columnas.

**25. ¿Por qué F005 no tiene registros etiquetados?** Su duración fue menor que el intervalo entre muestras y no coincidió con una muestra de los equipos afectados. No implica que cualquier falla de menos de 60 segundos sea siempre invisible: depende de cuándo ocurra y de posibles efectos posteriores.

**26. ¿La aserción de conteo demuestra que el join es totalmente correcto?** No. Detecta pérdida o multiplicación de filas, pero etiquetas incorrectas podrían conservar el total. La condición debe justificarse con la lógica del simulador y verificarse con más evidencia.

**27. ¿Por qué no coalesce(1) para cualquier Big Data?** Porque deja la escritura en una tarea y puede crear un cuello de botella. Aquí se usa por el tamaño final reducido; con más volumen habría que conservar más paralelismo y controlar tamaños de archivo.

**28. ¿Por qué siete carpetas y no una por segundo?** Fecha tiene siete valores; el timestamp tiene 604.800. La segunda opción produciría demasiados directorios y archivos pequeños para las consultas previstas.

**29. ¿Por qué fecha se verifica aparte al releer?** Al particionar por fecha, Spark reconstruye esa columna desde nombres como `fecha=2026-01-12`; el notebook comprueba específicamente que vuelva como tipo date.

**30. ¿Qué falta para la Fase 3?** El notebook entrega datos y etiquetas de referencia. La construcción del detector, sus variables definitivas y su evaluación corresponden a la siguiente fase. Este notebook no demuestra que un modelo ya detecte fallas.

## Términos adicionales que pueden aparecer en las preguntas

| Término | Definición y relación con el notebook |
|---|---|
| Plan lógico | Descripción de las operaciones y relaciones necesarias para una consulta |
| Plan físico | Estrategia concreta de ejecución: lecturas, agregaciones, Exchanges y tipos de join |
| `InMemoryTableScan` | Lectura de datos persistidos reutilizables; su presencia ayuda a ver que el experimento parte del caché |
| `HashAggregate` | Operador de agregación por claves con estructura hash |
| `Project` | Selección y cálculo de columnas |
| `Filter` | Selección de filas según una condición |
| Predicate pushdown | Llevar filtros hacia la lectura para reducir trabajo; el beneficio exacto depende del formato y de la fuente |
| API REST de Spark | Interfaz HTTP para consultar datos de aplicaciones, jobs, etapas y tareas |
| UUID | Identificador usado para separar ejecuciones y no mezclar métricas al repetir una celda |
| Mediana | Valor central de un conjunto ordenado; aquí se usa para tiempos y cargas típicas |
| Ratio máximo/mediana | Cuánto supera el máximo al valor típico; útil para describir tareas rezagadas, pero sensible también al cambio de la mediana |
| Hash | Función que asigna una clave a un valor usado para distribuirla; distintas claves pueden terminar en la misma partición |
| `lag` | Obtiene el valor de una fila anterior dentro de la ventana ordenada |
| Intervalo semiabierto | Incluye un extremo y excluye el otro; aquí `[inicio, fin)` |
| Precisión del detector | De las lecturas que predijo como positivas, qué proporción era realmente positiva: VP / (VP + FP) |
| Recall o exhaustividad | De las lecturas realmente positivas, qué proporción detectó: VP / (VP + FN) |
| VP, FP y FN | Verdaderos positivos, falsos positivos y falsos negativos; se definirán respecto de las etiquetas y la unidad de evaluación elegida |

Precisión y recall solo están motivados como objetivo de la Fase 3: **no se calculan en este notebook**. Evaluar por lectura y evaluar por evento de falla no es lo mismo; esa decisión deberá definirse al diseñar la evaluación.

## Recorrido recomendado para exponer en quince minutos

Una opción es reservar unos diez minutos para explicar y cinco para preguntas. Es una propuesta de organización; la rúbrica solo fija quince minutos totales. El reparto entre personas debe asegurar que cada integrante presente al menos una implicancia.

| Tiempo orientativo | Qué mostrar | Idea que debe quedar clara |
|---|---|---|
| 0:00–0:30 | Celda 1 | Objetivo y distinción entre los dos datasets |
| 0:30–1:30 | Celdas 5, 7 y 8 | Roles y recursos del clúster; límite de collect |
| 1:30–2:15 | Celdas 16 y 17 | Transformaciones, acción y optimización |
| 2:15–3:00 | Celdas 12 y 13 | Costo de inferir y estabilidad de tipos |
| 3:00–4:15 | Celdas 39 y 45 | Calidad: qué se elimina, qué se conserva y por qué |
| 4:15–5:30 | Celdas 48, 49 y 51 | Exchange, costo del shuffle y particiones |
| 5:30–7:00 | Celdas 55, 57, 60 y 62 | Skew, evidencia de tarea lenta y mitigación |
| 7:00–8:30 | Celdas 65, 71 y 73 | Estrategia del join y corrección del etiquetado |
| 8:30–9:45 | Celdas 22, 33, 76 y 77 | Parquet, pruning, salida diaria y verificación |
| 9:45–10:00 | Celda 80 | Producto final y dos resultados destacados |
| 10:00–15:00 | Celdas solicitadas | Respuestas individuales apoyadas en evidencia |

No intentes abrir y explicar en detalle todas las celdas de cada fila. Ten localizadas las evidencias y muestra las que permitan sostener tu explicación. Usa las tablas guardadas para los experimentos largos; confirma de antemano la ejecución completa exigida.

Un ejercicio útil es tapar las frases sugeridas y responder para cada bloque: **¿qué dato entra?, ¿qué operación hacemos?, ¿qué sale?, ¿cómo sabemos que está bien?, ¿qué cambia cuando crece el volumen?**

## Hoja rápida de resultados que conviene tener ubicados

| Tema | Dato de la ejecución guardada | Celdas |
|---|---|---|
| Clúster | Dos executors, cuatro cores; presupuesto 6 GB frente a 15,6 GB | 5, 7 |
| Crudo | 10.000.014 registros | 12 |
| Esquema | 28,67 s inferido; 10,93 s declarado | 12 |
| Evaluación perezosa | 0,204 s construcción; 11,02 s count | 16 |
| JSON y Parquet | 1.791 frente a 22 en el rótulo MB; consulta 13,7 frente a 1,4 s | 22 |
| Limpieza | 6.395.325 → 6.395.323; solo dos filas eliminadas | 45 |
| Calidad | 124.219 lecturas marcadas no confiables | 45 |
| Agregación | 200: 4,45 s; 8: 1,08 s; 16: 1,17 s; AQE: 2,59 s | 51 |
| Sesgo | faja_1 = 47,28 % y cien veces la mediana por entidad | 55 |
| Ventana | Menor carga máxima, pero 10,93 → 12,09 s totales | 57 |
| Salting | Máximas filas por tarea: 3.175.206 → 523.474 | 62 |
| Broadcast | 9,30 → 3,15 s; tres → un shuffle en esos planes | 65 |
| Join ingenuo | 6.395.323 → 9.419.323 filas | 71 |
| Range join | Conserva 6.395.323; 436.218 lecturas en falla | 73 |
| Salida | Siete directorios diarios; un Parquet por día | 77 |

## Anexo: las nueve celdas de primer_contacto.ipynb

Este archivo es introductorio. El soporte principal de la entrega y de este informe es `fase2_pyspark.ipynb`.

| Celda | Tipo | Qué hace y cómo explicarla |
|---|---|---|
| 1 | Markdown | Portada del primer contacto con PySpark. Presenta un ejercicio corto, no toda la Fase 2 |
| 2 | Markdown | Encabezado de la sesión; prepara el contexto de la conexión |
| 3 | Código | Importa Spark y funciones, crea una sesión contra el master, fija la comunicación del driver, espera tres segundos y muestra versión, executors y paralelismo. Es una comprobación más simple que la espera y las aserciones del notebook principal |
| 4 | Markdown | Encabezado de evaluación perezosa; anuncia el concepto a demostrar |
| 5 | Código | Declara diez campos, lee los JSONL y prepara un filtro `value > -18`. Cronometra preparación y luego count. Aquí timestamp se declara como texto. El filtro es didáctico: no constituye una regla general de limpieza para métricas con unidades diferentes |
| 6 | Markdown | Presenta la comparación de esquema inferido frente a declarado |
| 7 | Código | Mide lectura más conteo con ambos esquemas e imprime tiempos y registros. No usa el filtro anterior en esa comparación y no incluye la aserción de igualdad que sí aparece en el notebook principal |
| 8 | Código | Muestra el esquema y cinco filas completas con `show(5, truncate=False)`. Es una inspección inicial de estructura, no un perfilado exhaustivo |
| 9 | Código | `spark.stop()` cierra la sesión y libera recursos de esa aplicación |

**Cómo explicarlo:** «Este notebook pequeño nos sirvió para entender la conexión y la ejecución perezosa. El principal amplía esa base con validaciones, perfilado, mediciones, corrección de joins y entrega verificada».

## Archivos de referencia

- `fase2_pyspark.ipynb`: fuente principal del código, celdas y resultados explicados.
- `Rubrica_Fase2_PySpark (2).pdf`: requisitos oficiales; página 1 para consigna y condiciones, página 2 para criterios y ponderaciones.
- `salida_fase2/metricas.json`: cifras guardadas de los experimentos.
- `primer_contacto.ipynb`: fuente del anexo introductorio.
- `README.md`, `REVISION_RUBRICA.md` y `CAMBIOS_NOTEBOOK_explicados.md`: contexto complementario; ante diferencias de cifras se priorizaron el código y las salidas actuales del notebook principal.
