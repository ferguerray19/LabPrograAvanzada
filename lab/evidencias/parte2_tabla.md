| Version | Estrategia | Tamano final | Build en frio (mediana) | Rebuild tras 1 linea (mediana) | Capa pip install en el rebuild |
|---|---|---|---|---|---|
| v0 | python:3.12 + COPY . . + root | 1.61GB | 2.0 s | 2.0 s | se ejecuta (1.1 s) |
| v1 | python:3.12-slim, una etapa, requirements primero | 178MB | 1.5 s | 0.6 s | CACHED |
| v2 | Multi-etapa + venv + tini + usuario 10001 | 179MB | 60.2 s | 1.6 s | CACHED |
| Δ v0→v2 | Reduccion obtenida | -89 % | — | -20 % | — |

Repeticiones (s): frio v0 2.0 / 2.0 / 2.0, v1 1.7 / 1.5 / 1.5, v2 77.8 / 14.1 / 60.2;
rebuild v0 2.0 / 2.0 / 2.0, v1 0.6 / 0.6 / 0.6, v2 2.3 / 1.5 / 1.6.

| Prueba de docker stop | StopTimeout | Tiempo | ExitCode |
|---|---|---|---|
| sin-init (v0, PID 1 = /bin/sh) | por defecto (<nil>) | 3.4 s | 137 |
| con-init (v2, PID 1 = tini) | por defecto (<nil>) | 0.4 s | 143 |
| sin-init-10 (v0) | 10 | 10.4 s | 137 |
| con-init-10 (v2) | 10 | 0.4 s | 143 |
