"""Genera las figuras del informe a partir de los CSV de mediciones.

matplotlib solo esta permitido AQUI, en /bench/, y no forma parte del
simulador. El generador se escribe exclusivamente con la biblioteca estandar.

Todas las figuras salen con ejes rotulados y unidades (Trampa N.o 8: la
evidencia de un informe de ingenieria son graficos, no capturas del
terminal). Este script no calcula nada que no este ya en los CSV: si un
numero no esta medido, no aparece en la figura.

    python -m bench.graficos --salida docs/figuras
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def leer(ruta: Path) -> list[dict]:
    if not ruta.exists():
        print(f"  (falta {ruta}, se omite la figura correspondiente)")
        return []
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fig_speedup(filas: list[dict], salida: Path) -> None:
    filas = sorted(filas, key=lambda r: int(r["workers"]))
    n = [int(r["workers"]) for r in filas]
    s = [float(r["speedup"]) for r in filas]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.plot(n, n, "--", color="0.6", label="Speedup ideal S(n) = n")
    ax.plot(n, s, "o-", color="#1f4e79", label="Speedup medido")
    ax.set_xlabel("Numero de procesos trabajadores n")
    ax.set_ylabel("Speedup S(n) = T(1) / T(n)  [adimensional]")
    ax.set_title("Curva de escalabilidad del generador")
    ax.set_xticks(n)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(salida / "fig1_speedup.png", dpi=160)
    plt.close(fig)


def fig_eficiencia(filas: list[dict], salida: Path) -> None:
    filas = sorted(filas, key=lambda r: int(r["workers"]))
    n = [int(r["workers"]) for r in filas]
    e = [float(r["eficiencia"]) for r in filas]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.axhline(1.0, ls="--", color="0.6", label="Eficiencia ideal = 1")
    ax.bar([str(x) for x in n], e, color="#1f4e79")
    ax.set_xlabel("Numero de procesos trabajadores n")
    ax.set_ylabel("Eficiencia E(n) = S(n) / n  [adimensional]")
    ax.set_title("Eficiencia paralela por configuracion")
    ax.set_ylim(0, 1.15)
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(salida / "fig2_eficiencia.png", dpi=160)
    plt.close(fig)


def fig_throughput(filas: list[dict], salida: Path) -> None:
    """Eventos/s y MB/s efectivos por configuracion. Los MB/s salen de
    bench/mediciones.csv, que escribe el propio simulador al terminar."""
    filas = sorted(filas, key=lambda r: int(r["workers"]))
    n = [int(r["workers"]) for r in filas]
    ev = [float(r["eventos_por_segundo"]) / 1e6 for r in filas]
    mb = [float(r["mb_por_segundo"]) for r in filas]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.plot(n, ev, "o-", color="#1f4e79", label="Rendimiento")
    ax.set_xlabel("Numero de procesos trabajadores n")
    ax.set_ylabel("Eventos generados [millones/s]")
    ax.set_xticks(n)
    ax.grid(alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(n, mb, "s--", color="#a33", label="Escritura efectiva")
    ax2.set_ylabel("Escritura efectiva [MB/s]")
    ax.set_title("Rendimiento de generacion y de entrada/salida")
    lineas = ax.get_lines() + ax2.get_lines()
    ax.legend(lineas, [l.get_label() for l in lineas], loc="lower right")
    fig.tight_layout()
    fig.savefig(salida / "fig3_throughput.png", dpi=160)
    plt.close(fig)


def fig_pickle(filas: list[dict], salida: Path) -> None:
    filas = sorted(filas, key=lambda r: int(r["lote"]))
    lotes = [int(r["lote"]) for r in filas]
    ev = [float(r["eventos_por_segundo"]) for r in filas]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.plot(lotes, ev, "o-", color="#1f4e79")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Eventos por put() [eventos/mensaje, escala log]")
    ax.set_ylabel("Rendimiento a traves de la cola [eventos/s, escala log]")
    ax.set_title("Costo de serializacion IPC segun tamano de lote")
    ax.grid(which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(salida / "fig4_pickle.png", dpi=160)
    plt.close(fig)


def fig_hilos(filas: list[dict], salida: Path) -> None:
    etiquetas = [f"{r['modo']}\nn={r['n']}" for r in filas]
    tiempos = [float(r["mediana_s"]) for r in filas]
    colores = {"secuencial": "0.5", "hilos": "#a33", "procesos": "#1f4e79"}
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(etiquetas, tiempos, color=[colores[r["modo"]] for r in filas])
    base = next((float(r["mediana_s"]) for r in filas if r["modo"] == "secuencial"), None)
    if base:
        ax.axhline(base, ls="--", color="0.4", label="Baseline secuencial")
        ax.legend()
    ax.set_ylabel("Tiempo de ejecucion [s]")
    ax.set_title("Hilos contra procesos sobre la misma carga CPU-bound")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(salida / "fig5_hilos_vs_procesos.png", dpi=160)
    plt.close(fig)


def fig_arquitecturas(filas: list[dict], salida: Path) -> None:
    """Opcion A contra Opcion B con la misma carga y los mismos workers."""
    etiquetas = {"shard": "Opcion B\n(N archivos)", "queue": "Opcion A\n(escritor unico)"}
    nombres = [etiquetas.get(r["arch"], r["arch"]) for r in filas]
    t = [float(r["mediana_s"]) for r in filas]
    fig, ax = plt.subplots(figsize=(5.5, 4.2))
    ax.bar(nombres, t, color=["#1f4e79", "#a33"][: len(t)])
    ax.set_ylabel("Tiempo de ejecucion [s]  (mediana de las corridas medidas)")
    ax.set_title("Comparacion arquitectonica, misma carga")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(salida / "fig6_arquitecturas.png", dpi=160)
    plt.close(fig)


def fig_lotes(filas: list[dict], salida: Path) -> None:
    """Costo de pickle medido sobre el simulador completo con --arch queue.
    Complementa fig4, que aisla el canal IPC sin fisica ni disco."""
    filas = sorted(filas, key=lambda r: int(r["batch_size"]))
    lotes = [int(r["batch_size"]) for r in filas]
    ev = [float(r["eventos_por_segundo"]) for r in filas]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.plot(lotes, ev, "o-", color="#1f4e79")
    ax.set_xscale("log")
    ax.set_xlabel("Eventos por put() [eventos/mensaje, escala log]")
    ax.set_ylabel("Rendimiento del simulador [eventos/s]")
    ax.set_title("Efecto del tamano de lote sobre la corrida completa (--arch queue)")
    ax.grid(which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(salida / "fig7_lotes_simulador.png", dpi=160)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Figuras del informe")
    ap.add_argument("--salida", default="docs/figuras")
    args = ap.parse_args(argv)
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    esc = leer(Path("bench/escalabilidad.csv"))
    if esc:
        fig_speedup(esc, salida)
        fig_eficiencia(esc, salida)

    med = leer(Path("bench/mediciones.csv"))
    if med:
        # una fila por corrida: se queda con la mediana por numero de workers
        por_w: dict[int, list[dict]] = {}
        for r in med:
            if r.get("fase") != "medida":  # se descarta el calentamiento
                continue
            por_w.setdefault(int(r["workers"]), []).append(r)
        agregado = []
        for w, rs in por_w.items():
            rs = sorted(rs, key=lambda r: float(r["duracion_s"]))
            agregado.append(rs[len(rs) // 2] | {"workers": w})
        if agregado:
            fig_throughput(agregado, salida)

    pk = leer(Path("bench/mediciones_pickle.csv"))
    if pk:
        fig_pickle(pk, salida)

    arq = leer(Path("bench/comparacion_arquitecturas.csv"))
    if arq:
        fig_arquitecturas(arq, salida)

    lot = leer(Path("bench/comparacion_lotes.csv"))
    if lot:
        fig_lotes(lot, salida)

    hp = leer(Path("bench/hilos_vs_procesos.csv"))
    if hp:
        fig_hilos(hp, salida)

    print(f"Figuras en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
