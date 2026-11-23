#!/usr/bin/env bash
set -e

echo "==> Aguardando PostgreSQL (${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432})..."
python - <<'PY'
import os, socket, time, sys

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))

for i in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print("==> PostgreSQL disponível!")
            sys.exit(0)
    except OSError:
        time.sleep(1)

print("==> ERRO: Não foi possível conectar ao PostgreSQL a tempo.", file=sys.stderr)
sys.exit(1)
PY

echo "==> Executando migrations..."
python manage.py migrate --noinput

echo "==> Coletando arquivos estáticos (WhiteNoise)..."
python manage.py collectstatic --noinput

if [ "${RUN_SEED_DATA:-false}" = "true" ]; then
    echo "==> Executando seed_data.py..."
    python seed_data.py
fi

echo "==> Iniciando Gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-2}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
