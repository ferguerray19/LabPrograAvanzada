"""Parte 1.4 del laboratorio: agota la memoria de su cgroup a proposito.

Reserva bloques de 10 MB y los mantiene vivos en una lista. `bytearray(n)`
pide la memoria rellena con ceros, asi que el kernel tiene que entregar
paginas reales (RSS), no solo reservar espacio de direcciones.

    docker run --name lab-oom -m 100m --memory-swap 100m \\
      -v "$PWD/lab/memory_bomb.py:/app/memory_bomb.py:ro" \\
      python:3.12-slim python /app/memory_bomb.py

No hay try/except que valga: cuando el cgroup agota su presupuesto, el OOM
killer envia SIGKILL, que no se puede capturar. Por eso la ultima linea del
log es un "Reservados" y no un traceback.
"""
import time

bloques = []
mb = 0
while True:
    bloques.append(bytearray(10 * 1024 * 1024))  # 10 MB residentes reales
    mb += 10
    print(f"Reservados: {mb} MB", flush=True)
    time.sleep(0.2)
