#!/usr/bin/env bash
# Funciones compartidas por los scripts de evidencia del laboratorio.
# No se ejecuta solo: lo cargan lab/parte1.sh, lab/parte2.sh y lab/parte3.sh.

set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVID="$RAIZ/lab/evidencias"
mkdir -p "$EVID"
cd "$RAIZ"

# Algunos comandos (readlink de /proc de otro usuario, lsns, dmesg, chown)
# necesitan root en el host y se escriben con `sudo`, igual que en la guia.
# Si el script ya corre como root, o no hay sudo, `sudo` ejecuta tal cual.
if [ "$(id -u)" -eq 0 ] || ! command -v sudo >/dev/null 2>&1; then
    sudo() { "$@"; }
fi

# Todo lo que se ve en la terminal queda ademas en lab/evidencias/<archivo>.
registrar() {
    exec > >(tee "$EVID/$1") 2>&1
    echo "# $(date '+%Y-%m-%d %H:%M:%S')  $(uname -srm)  $(docker --version 2>/dev/null || echo 'sin docker')"
}

titulo() {
    printf '\n==================================================================\n'
    printf '  %s\n' "$*"
    printf '==================================================================\n'
}

# Muestra el comando tal como se escribiria en la terminal y lo ejecuta.
# Se usa con un heredoc de delimitador entre comillas, asi el texto que se
# muestra es EXACTAMENTE el que corre, sin problemas de comillas:
#     ejecutar <<'CMD'
#     docker exec lab-ns sh -c 'cat /proc/1/cmdline | tr "\0" " "'
#     CMD
ejecutar() {
    local c
    c="$(cat)"
    printf '\n$ %s\n' "$c"
    eval "$c"
}

# Segundos transcurridos con decimales, para la tabla comparativa.
ahora() { date +%s.%N; }
dif() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

requiere_linux() {
    if [ "$(uname -s)" != "Linux" ]; then
        echo "AVISO: '$1' inspecciona el host desde fuera del contenedor y en"
        echo "Docker Desktop hay que correrlo dentro de la VM o en WSL2."
    fi
}
