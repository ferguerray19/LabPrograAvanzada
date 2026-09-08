"""Resumen agregado de bench/mediciones.csv.

`mediciones.csv` es el registro CRUDO: una fila por ejecucion del simulador,
incluidas las corridas de calentamiento. La guia pide conservarlo asi, porque
los datos crudos de todas las corridas son parte del entregable.

Este script no lo modifica: lee ese registro y produce la vista agregada que
va al informe, con la MEDIANA de cada configuracion y no la mejor corrida, y
con el speedup y la eficiencia calculados contra la mediana de un solo worker.
Las corridas marcadas como calentamiento quedan fuera del calculo.

    python -m bench.resumen
    python -m bench.resumen --etiqueta escalabilidad --salida bench/resumen.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

COLUMNAS = (
    "etiqueta", "arch", "esquema", "workers", "corridas",
    "mediana_s", "min_s", "max_s", "desviacion_s",
    "speedup", "eficiencia", "eventos_por_segundo", "mb_por_segundo",
    "total_eventos", "bytes_por_evento", "desbalance_puntos",
)


def cargar(ruta: Path, etiqueta: str | None) -> list[dict]:
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}. Ejecute primero el simulador.")
    with open(ruta, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    filas = [r for r in filas if r.get("fase") == "medida"]
    if etiqueta is not None:
        filas = [r for r in filas if r["etiqueta"] == etiqueta]
    if not filas:
        raise SystemExit("No hay corridas medidas que resumir con ese filtro.")
    return filas


def agregar(filas: list[dict]) -> list[dict]:
    grupos: dict[tuple, list[dict]] = {}
    for r in filas:
        clave = (r["etiqueta"], r["arch"], r["esquema"], int(r["workers"]))
        grupos.setdefault(clave, []).append(r)

    # Base del speedup: la mediana con un solo worker DE LA MISMA serie.
    # Comparar contra otra etiqueta o contra otro esquema daria un speedup
    # que no significa nada.
    bases: dict[tuple, float] = {}
    for (etq, arch, esq, w), rs in grupos.items():
        if w == 1:
            bases[(etq, arch, esq)] = statistics.median(
                float(r["duracion_s"]) for r in rs
            )

    salida = []
    for (etq, arch, esq, w), rs in sorted(grupos.items(), key=lambda kv: kv[0]):
        t = [float(r["duracion_s"]) for r in rs]
        mediana = statistics.median(t)
        base = bases.get((etq, arch, esq))
        s = base / mediana if base else None
        salida.append({
            "etiqueta": etq, "arch": arch, "esquema": esq, "workers": w,
            "corridas": len(t),
            "mediana_s": round(mediana, 3),
            "min_s": round(min(t), 3),
            "max_s": round(max(t), 3),
            "desviacion_s": round(statistics.stdev(t), 3) if len(t) > 1 else 0.0,
            "speedup": round(s, 4) if s else "",
            "eficiencia": round(s / w, 4) if s else "",
            "eventos_por_segundo": round(
                statistics.median(float(r["eventos_por_segundo"]) for r in rs), 1),
            "mb_por_segundo": round(
                statistics.median(float(r["mb_por_segundo"]) for r in rs), 2),
            "total_eventos": rs[0]["total_eventos"],
            "bytes_por_evento": rs[0]["bytes_por_evento"],
            "desbalance_puntos": rs[0]["desbalance_puntos"],
        })
    return salida


def imprimir(filas: list[dict]) -> None:
    cab = ("workers", "corridas", "mediana_s", "desviacion_s", "speedup",
           "eficiencia", "eventos_por_segundo", "mb_por_segundo")
    anchos = {c: max(len(c), 12) for c in cab}
    print("  ".join(c.rjust(anchos[c]) for c in cab))
    print("  ".join("-" * anchos[c] for c in cab))
    for r in filas:
        print("  ".join(str(r[c]).rjust(anchos[c]) for c in cab))
    if any(r["speedup"] == "" for r in filas):
        print("\nAviso: falta la corrida con 1 worker de alguna serie, asi que "
              "no se pudo calcular su speedup.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Resumen de la campana")
    ap.add_argument("--csv", default="bench/mediciones.csv")
    ap.add_argument("--etiqueta", default=None,
                    help="resume solo un experimento; por defecto, todos")
    ap.add_argument("--salida", default="bench/resumen.csv")
    args = ap.parse_args(argv)

    filas = agregar(cargar(Path(args.csv), args.etiqueta))
    imprimir(filas)

    ruta = Path(args.salida)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)
    print(f"\nEscrito {ruta} ({len(filas)} configuraciones).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
