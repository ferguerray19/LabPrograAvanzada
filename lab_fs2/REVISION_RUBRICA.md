**Revisión actualizada según la rúbrica — Fase 2 PySpark**

Fecha: 18 de octubre de 2026. Archivo evaluado: fase2_pyspark.ipynb. Referencia: Rubrica_Fase2_PySpark (2).pdf.

**Resultado:** el notebook actual presenta evidencia consistente de ejecución completa y cumple los requisitos documentales de los criterios 1–7. Las correcciones están aplicadas y las salidas corresponden al código vigente. La exposición y las respuestas individuales todavía deben evaluarse oralmente.

**Evaluación por criterio**

Los niveles son una estimación de esta revisión, no una calificación oficial del docente.

| Criterio | Peso | Nivel estimado | Evidencia actual |
|---|---:|---|---|
| 1. Clúster operativo | 10 % | 4/4 | La sesión muestra dos executors, dos workers vivos y cuatro tareas simultáneas. Se justifica la memoria: 2 × 2 GB + 2 GB = 6 GB < 15,6 GB. Incluye diagrama y capturas de la prueba de humo y del master, identificadas como históricas. |
| 2. Ingesta con esquema | 5 % | 4/4 | Lee 10.000.014 registros con StructType y tipos adecuados. Compara esquema inferido y declarado, y explica transformaciones, acciones y el plan específico que necesita count(). |
| 3. Perfilado y limpieza | 10 % | 4/4 | Perfila ambos datasets antes de limpiar. Elimina solo dos duplicados exactos, conserva las muestras válidas de la báscula y marca 124.219 lecturas degradadas. Comprueba nulos obligatorios y dominios de calidad, con interpretación final. |
| 4. Shuffling y sesgo | 15 % | 4/4 | Identifica Exchange y compara 200, 8 y 16 particiones y AQE. Muestra el sesgo de faja_1, captura Stages, gráficos y salting. Las explicaciones reflejan los resultados de la corrida actual. |
| 5. Joins y etiquetado | 10 % | 4/4 | Explica el aumento de filas del join ingenuo. Usa range join con broadcast e intervalo t_inicio <= t < t_fin. Verifica mediante assert que se conservan 6.395.323 filas. |
| 6. Escritura y verificación | 10 % | 4/4 | Escribe Parquet por fecha con coalesce(1), justifica esa elección y relee la salida. Pasan las aserciones de filas, distribución diaria, etiquetas, calidad y tipos, incluido DateType para fecha. |
| 7. Notebook como soporte | 10 % | 4/4 | Incluye contexto, interpretación, tablas, gráficos y capturas. Tiene 82 celdas, de las cuales 37 son de código, con ejecución consecutiva 1–37 y sin salidas de error. |
| 8. Implicancias para Big Data | 20 % | Pendiente de evaluación oral | Las ocho implicancias tienen contenido y evidencia en el notebook. El grupo debe explicarlas con sus propias palabras y relacionarlas con datos que no caben en una sola máquina. |
| 9. Respuestas individuales | 10 % | Pendiente de evaluación oral | Cada integrante debe responder con precisión y apoyarse en resultados de su notebook. |

La estimación para los criterios 1–7 es **70 de los 70 puntos porcentuales disponibles en ese tramo**, sujeta a la valoración docente de la evidencia. El **30 % restante** depende de la exposición y las respuestas individuales. No corresponde asignar una nota final sin esas evaluaciones.

**Resultados vigentes para la presentación**

| Medición | Resultado |
|---|---|
| Esquema inferido / declarado | 28,67 s / 10,93 s |
| Agregación con 200 / 8 / 16 particiones / AQE | 4,45 s / 1,08 s / 1,17 s / 2,59 s |
| Mejor configuración de esa comparación | 8 particiones; 4,1× más rápida que 200 |
| Filas del simulador antes / después de limpiar | 6.395.325 / 6.395.323 |
| Lecturas conservadas y marcadas como no confiables | 124.219 |
| Participación de faja_1 | 47,28 % de las filas |
| Join ingenuo: filas antes / después | 6.395.323 / 9.419.323 |
| Range join: filas antes / después | 6.395.323 / 6.395.323 |
| Lecturas etiquetadas en falla | 436.218 |
| Sort-merge / broadcast | 9,30 s / 3,15 s |
| Salida limpia | Siete carpetas diarias, con un Parquet por día |

Al explicar el sesgo, distinguir reparto y tiempo total: la clave más fina reduce las filas de la tarea más cargada de 3.175.200 a 725.760, pero en esta corrida la ventana tarda 12,09 s frente a 10,93 s. La evidencia demuestra mejor reparto; no demuestra una reducción del tiempo total en esa comparación. El notebook ya reconoce esa diferencia.

**Preparación de la exposición**

- Usar el notebook como soporte y recorrer las ocho implicancias apoyándose en sus resultados.
- Respetar los 15 minutos por grupo, incluidas las preguntas. Cada integrante expone al menos una implicancia y responde individualmente.
- Usar las cifras de esta corrida. Las capturas antiguas están identificadas y sus tiempos no deben presentarse como mediciones de la ejecución actual.

**Alcance de la revisión**

Se revisaron el código, las explicaciones, las salidas guardadas, las capturas, la configuración y la consistencia con salida_fase2/metricas.json. La sintaxis de las 37 celdas de código es válida y la relectura guardada confirma que pasaron todas las aserciones. Esta revisión no volvió a ejecutar el clúster ni recontó de forma independiente los Parquet. No queda pendiente repetir la ejecución por los puntos revisados.
