"""Verificación independiente de los Parquet guardados, sin iniciar otra sesión Spark."""
from collections import Counter
from pathlib import Path
import json
import pyarrow.parquet as pq
import pyarrow.compute as pc


def validar(base=Path(__file__).resolve().parent):
    metricas = json.loads((base / 'salida_fase2/metricas.json').read_text())
    ruta = base / 'salida_fase2/telemetria_limpia.parquet'
    filas, fallas, degradadas = 0, 0, 0
    por_dia = {}
    esquema = None
    calidades = Counter()
    for archivo in sorted(ruta.glob('fecha=*/*.parquet')):
        parquet = pq.ParquetFile(archivo)
        actual = parquet.schema_arrow.remove_metadata()
        if esquema is None:
            esquema = actual
        assert actual == esquema, f'Esquema inconsistente: {archivo}'
        n = parquet.metadata.num_rows
        por_dia[archivo.parent.name] = por_dia.get(archivo.parent.name, 0) + n
        filas += n
        for lote in parquet.iter_batches(columns=['timestamp_utc', 'entidad_id', 'variable', 'valor',
                                                   'sensor_confiable', 'en_falla', 'calidad_sensor']):
            for columna in lote.columns:
                assert columna.null_count == 0, f'Nulo obligatorio en {archivo}'
            fallas += pc.sum(lote.column('en_falla')).as_py()
            degradadas += pc.sum(pc.invert(lote.column('sensor_confiable'))).as_py()
            for registro in pc.value_counts(lote.column('calidad_sensor')).to_pylist():
                calidades[registro['values']] += registro['counts']
    assert len(por_dia) == 7
    assert filas == metricas['limpio_filas']
    assert fallas == metricas['lecturas_en_falla']
    assert degradadas == metricas['no_confiables']
    assert set(calidades) <= {'ok', 'asentamiento', 'deriva', 'pegado'}
    bronze = sum(pq.ParquetFile(p).metadata.num_rows
                 for p in (base / 'salida_fase2/bronze_raw.parquet').glob('*.parquet'))
    assert bronze == metricas['raw_registros']
    telemetria = sum(pq.ParquetFile(p).metadata.num_rows
                    for p in (base / 'salida_sitio3/telemetria.parquet').glob('fecha=*/*.parquet'))
    assert telemetria == metricas['tele_filas']
    resultado = dict(filas_silver=filas, filas_bronze=bronze, filas_simulador=telemetria,
                     en_falla=fallas, no_confiables=degradadas, por_dia=por_dia,
                     calidad=dict(calidades), esquema=str(esquema))
    destino = base / 'verificaciones'
    destino.mkdir(exist_ok=True)
    (destino / 'parquet_verificado.json').write_text(json.dumps(resultado, indent=2), encoding='utf-8')
    print(json.dumps(resultado, indent=2))


if __name__ == '__main__':
    validar()
