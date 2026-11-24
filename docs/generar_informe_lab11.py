from pathlib import Path
import json
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4

root=Path(__file__).resolve().parent.parent; lab=root/'lab_fs2'
r=json.loads((lab/'salida_fase3/resultados_lab11.json').read_text('utf-8'))
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodySmall',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=8))
styles.add(ParagraphStyle(name='CellSmall',fontName='Helvetica',fontSize=8.5,leading=11,spaceAfter=0))
styles['Title'].fontName='Helvetica-Bold';styles['Title'].fontSize=21;styles['Title'].leading=25
styles['Heading1'].fontSize=15;styles['Heading1'].leading=19;styles['Heading1'].textColor=colors.black
styles['Heading2'].fontSize=11.5;styles['Heading2'].textColor=colors.black
story=[]
def p(s):story.append(Paragraph(s,styles['BodySmall']))
def h(s):story.append(Paragraph(s,styles['Heading1']))
def table(rows,widths):
 data=[[Paragraph(escape(str(c)),styles['CellSmall']) for c in row] for row in rows]
 t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce8f2')),('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#c9cfd5')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
 story.extend([t,Spacer(1,12)])
fmt=lambda x:f'{x:,}'.replace(',','.')
story.append(Paragraph('Informe del laboratorio 11',styles['Title']))
p('Preparación de datos e ingeniería de características con PySpark MLlib<br/>Programación Avanzada · Terminal Puerto Coquimbo, Sitio 3<br/>Verificación del 24 de noviembre de 2026')
h('Ejecución y unidad de observación')
p(f'La capa limpia contiene {fmt(r["lecturas"])} lecturas. El procesamiento agrupa cada serie entidad-variable en ventanas de cinco minutos y obtiene {fmt(r["ventanas"])} ejemplos. El vector final tiene {r["features"]} posiciones. Se verificaron todos los vectores: {r["vectores_invalidos"]} con nulos, NaN o infinitos y ninguna dimensión incorrecta. Se conservan todas las ventanas.')
p('El entorno usa Spark 4.0.1 y Python 3.10.12 con dos executors y cuatro tareas simultáneas. Se adaptó la etiqueta a en_falla, que es el nombre de la salida real de Fase 2. La persistencia se dirige a salida_fase3. No se entrenó ni evaluó un modelo predictivo.')
h('Ejercicio 1 y elección de ventana')
rows=[['Minutos','Ventanas','Nulos desv','Fallas %','Correlación']]
for x in r['ejercicio_1']:rows.append([x['minutos'],fmt(x['ventanas']),fmt(x['nulos_desv']),f'{x["porcentaje_falla"]:.3f}',f'{x["correlacion_desv_rango"]:.4f}'])
table(rows,[55,108,102,90,135])
p('La correlación compara desv_z y rango_z después de la imputación por mediana; los nulos de desv se cuentan antes del tratamiento semántico. Se mantiene la misma telemetría y línea base al comparar los tamaños.')
p('Se eligen cinco minutos como compromiso entre resolución temporal y estabilidad de los estadísticos. Un minuto genera más ejemplos y puede dejar ventanas con una única lectura; quince minutos mezcla durante más tiempo periodos normales y anómalos. Una ventana se etiqueta si contiene al menos una lectura en falla, por lo que aumentar su duración cambia también el desbalance. Esta comparación no prueba una superioridad predictiva: eso requiere evaluar modelos posteriormente.')
story.append(PageBreak())
h('Respuestas a las preguntas de control')
answers=[
('Paso 2','pyspark.ml trabaja con DataFrames y columnas vectoriales. El esquema y las optimizaciones de Spark SQL permiten integrar preparación y aprendizaje sin cambiar a la antigua API de RDD.'),
('Paso 3','La tabla larga representa una lectura por fila. El ejemplo elegido resume una serie durante una ventana y proporciona un vector numérico de características coherentes con esa unidad.'),
('Paso 4','cache evita recalcular el groupBy en consultas sucesivas. La agregación produce shuffle y la faja aporta más lecturas; cache no elimina el skew. Una ventana por serie reduce el predominio del ritmo de muestreo en la tabla de ejemplos.'),
('Paso 5','Un promedio de 380 mezcla unidades y escalas de sensores. Un z_prom de 3 expresa tres desviaciones respecto de la referencia de su propia serie; requiere una base válida y disponible al predecir.'),
('Paso 6','Una característica debe estar disponible al predecir y no revelar la respuesta ni usar información futura. Se excluyen etiqueta, en_falla, falla_id, tipo_falla, severidad, identificador de equipo y fecha absoluta de las entradas del pipeline.'),
('Paso 7','handleInvalid="skip" elimina ejemplos y puede sesgar las clases. La mediana es menos sensible a extremos que la media. Se distinguen ausencia estructural de alimentador, dispersión no observable con una lectura y características relativas nulas.'),
('Paso 8','Pasar un índice categórico como continuo inventaría distancias entre categorías. StringIndexer con keep reserva un índice desconocido; OneHotEncoder con dropLast=True lo representa con un vector de ceros en esta configuración.'),
('Paso 9','One-hot y delta_faltante ya son indicadores binarios y no entran en StandardScaler. Las siete continuas se escalan aparte; así se conserva la interpretación de los indicadores y la dispersidad de las categorías.'),
('Paso 10','Imputer, StringIndexer, OneHotEncoder y StandardScaler son Estimators. Los dos VectorAssembler son Transformers. El Imputer dentro del Pipeline aprende sus medianas durante fit, permitiendo ajustarlas solo con entrenamiento.'),
('Paso 11','Si el 98 % es normal, predecir siempre normal logra 98 % de accuracy y 0 % de detección de anomalías. Deben estudiarse métricas de la clase positiva; accuracy sola es insuficiente.'),
('Paso 12','Se guarda el Pipeline sin ajustar para reutilizar la receta y aprender sus parámetros solo con entrenamiento en semana 12. También hay que controlar la base usada antes del Pipeline; guardar la receta no corrige una fuga previa.')]
for title,body in answers:p(f'<b>{title}.</b> {body}')
story.append(PageBreak())
h('Características finales y prevención de fuga')
p('La tabla enumera las entradas efectivas del vector. prom, desv, minimo, maximo y n_lecturas son auxiliares para construir o describir ejemplos; no se ensamblan directamente como características finales en este notebook.')
table([['Característica','Tipo','Cálculo y condición de uso'],
['z_prom_imp','Continua','(prom - base_prom) / base_desv; nulos con mediana. Base aprendida sin consultar prueba.'],
['desv_z_imp','Continua','desv / base_desv; cero si hay una lectura; resto nulo se imputa.'],
['rango_z_imp','Continua','(maximo - minimo) / base_desv; mediana si no hay base válida.'],
['delta_z_imp','Continua','(prom - prom anterior) / base_desv; lag solo del pasado; mediana si falta.'],
['frac_confiable','Continua','Proporción de lecturas confiables en la ventana; dato operativo disponible.'],
['hora_sin, hora_cos','Continuas','sin y cos de 2*pi * hora/24; codifican periodicidad sin la fecha absoluta.'],
['delta_faltante','Binaria','1 si delta_z era nulo antes de imputar; no utiliza etiqueta.'],
['variable, entidad_tipo','Categóricas a binarias','StringIndexer y OneHotEncoder; categorías observables, sin identificador de equipo.'],
['peor_calidad, alimentador_id','Categóricas a binarias','Peor calidad de sensor y alimentador operativo; nulo estructural se convierte en ninguno.']], [130,88,272])
p('Las siete continuas se ensamblan y escalan con StandardScaler(withMean=True, withStd=True). Luego se añaden delta_faltante y las cuatro codificaciones one-hot. El mapa completo de posiciones se guarda en salida_fase3/mapa_features.csv.')
h('Desbalance observado')
table([['Etiqueta','Ventanas','Porcentaje']]+[[int(x['etiqueta']),fmt(int(x['count'])),f'{x["%"]:.3f} %'] for x in r['clases']],[130,180,180])
p('La aserción de columnas prohibidas comprueba las entradas del Pipeline. No demuestra por sí sola ausencia de fuga temporal en cálculos anteriores: la línea base del recorrido principal usa toda la semana como demostración y debe recalcularse antes de una evaluación temporal.')
story.append(PageBreak())
h('Ejercicio 3 y persistencia')
e=r['ejercicio_3']
p(f'Se aprende una segunda línea base únicamente con lecturas confiables del {r["primer_dia_base"]}. Se compara el z-score de {fmt(e["ventanas_posteriores"])} ventanas de días posteriores y se verifica que el join conserva su conteo.')
table([['Medición','Resultado'],['Comparaciones con ambas bases válidas',fmt(e['comparaciones_validas'])],['Z-score nulo con base del primer día',fmt(e['z_dia1_nulos'])],['Cambio absoluto medio',f'{e["cambio_absoluto_medio"]:.6f}'],['Cambio absoluto máximo',f'{e["cambio_absoluto_maximo"]:.6f}']],[330,160])
p('Los cambios muestran que el periodo de referencia afecta las características de los días siguientes. Una serie constante o sin referencia válida mantiene nulos. El primer día no se presupone libre de fallas: esta comparación demuestra el efecto de restringir la información temporal, no la existencia de una base perfecta.')
p(f'Se guardaron caracteristicas.parquet, particionado por fecha, y pipeline_preparacion como Pipeline sin ajustar de {r["etapas"]} etapas. La relectura conserva {fmt(r["ventanas"])} filas y la receta cargada genera vectores de {r["features"]} posiciones. La tabla persistida conserva características previas al ajuste, identificadores y etiqueta; el vector features se produce al aplicar la receta.')
shot=lab/'capturas/lab11_salida_fase3.png'
if shot.exists():
 from PIL import Image as PILImage
 w,hh=PILImage.open(shot).size
 factor=min(490/w,170/hh)
 story.append(Image(str(shot),width=w*factor,height=hh*factor))
 p('Evidencia del listado de salida_fase3 en el host después de la ejecución.')
else:
 p('El listado de salida_fase3 se conserva en la última sección ejecutada del notebook y en la evidencia de la carpeta entregada.')
p('Fuentes: guía de laboratorio 11, notebook ejecutado, resultados_lab11.json y mapa_features.csv. Los informes y capturas anteriores se conservan identificados como históricos. Antes de evaluar modelos, separar temporalmente los datos, recalcular la línea base con entrenamiento y ajustar el Pipeline exclusivamente con entrenamiento.')
def footer(canvas,doc):
 canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#555555'))
 canvas.drawString(52,28,'Programación Avanzada · Laboratorio 11 · 24 noviembre 2026')
 canvas.drawRightString(A4[0]-52,28,str(doc.page))
doc=SimpleDocTemplate(str(root/'docs/Informe_Lab11.pdf'),pagesize=A4,rightMargin=52,leftMargin=52,topMargin=42,bottomMargin=43)
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(root/'docs/Informe_Lab11.pdf')
