#!/usr/bin/env bash
# ==============================================================================
# Script de Provisionamento Inicial da VPS (Ubuntu 22.04+ / HostGator)
# Stack: Docker + Traefik + PostgreSQL + Django (WhiteNoise) + Portainer + Dozzle
# ==============================================================================
set -euo pipefail

APP_DIR="/opt/organizzado"
REPO_URL="https://github.com/ciceroregis/organizzado.git"
SSH_PORT="22022"
DEPLOY_USER="${SUDO_USER:-zurc}"

echo "============================================================"
echo " 1/6 - Corrigindo hostname em /etc/hosts (evita aviso sudo) "
echo "============================================================"
CURRENT_HOSTNAME="$(hostname)"
if ! grep -q "$CURRENT_HOSTNAME" /etc/hosts; then
    echo "127.0.1.1 $CURRENT_HOSTNAME" | sudo tee -a /etc/hosts >/dev/null
    echo "Hostname '$CURRENT_HOSTNAME' adicionado ao /etc/hosts."
fi

echo "============================================================"
echo " 2/6 - Atualizando pacotes básicos e instalando utilitários "
echo "============================================================"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg ufw git fail2ban openssl

echo "============================================================"
echo " 3/6 - Instalando Docker Engine & Docker Compose Plugin     "
echo "============================================================"
if ! command -v docker >/dev/null 2>&1; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable --now docker
else
    echo "Docker já está instalado: $(docker --version)"
fi

sudo usermod -aG docker "$DEPLOY_USER"

echo "============================================================"
echo " 4/6 - Configurando Firewall (UFW) com Segurança            "
echo "============================================================"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow "${SSH_PORT}/tcp" comment 'SSH Custom Port'
sudo ufw allow 80/tcp comment 'HTTP Traefik'
sudo ufw allow 443/tcp comment 'HTTPS Traefik'
sudo ufw --force enable
sudo ufw status verbose

echo "============================================================"
echo " 5/6 - Preparando Diretório da Aplicação (${APP_DIR})       "
echo "============================================================"
sudo mkdir -p "$APP_DIR"
sudo chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
    sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$APP_DIR"
else
    sudo -u "$DEPLOY_USER" git -C "$APP_DIR" pull origin main
fi

if [ ! -f "$APP_DIR/.env" ]; then
    DJANGO_SECRET="$(openssl rand -hex 32)"
    DB_PASS="$(openssl rand -hex 24)"
    DOZZLE_PASS="$(openssl rand -hex 12)"

    cat <<EOF | sudo -u "$DEPLOY_USER" tee "$APP_DIR/.env" >/dev/null
DJANGO_SECRET_KEY=${DJANGO_SECRET}
DJANGO_DEBUG=False
DJANGO_SECURE_COOKIES=True
DJANGO_ALLOWED_HOSTS=organizzado.com.br,www.organizzado.com.br,143.95.185.216,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://organizzado.com.br,https://www.organizzado.com.br,http://organizzado.com.br,http://www.organizzado.com.br,http://143.95.185.216

DOMAIN_NAME=organizzado.com.br
ACME_EMAIL=ciceroregis25@gmail.com

POSTGRES_DB=organizzado
POSTGRES_USER=organizzado_user
POSTGRES_PASSWORD=${DB_PASS}
POSTGRES_HOST=db
POSTGRES_PORT=5432

GUNICORN_WORKERS=3
GUNICORN_THREADS=2
RUN_SEED_DATA=true

DOZZLE_USERNAME=admin
DOZZLE_PASSWORD=${DOZZLE_PASS}
EOF
    chmod 600 "$APP_DIR/.env"
    echo "Arquivo $APP_DIR/.env gerado automaticamente com senhas criptográficas fortes!"
else
    echo "Arquivo $APP_DIR/.env já existe, mantendo configurações atuais."
fi

echo "============================================================"
echo " 6/6 - Subindo Containers (Traefik, DB, Web, Portainer, Dozzle)"
echo "============================================================"
cd "$APP_DIR"
sudo docker compose up -d --build --remove-orphans

# Desativa RUN_SEED_DATA após o primeiro boot para não sobrescrever dados em futuros deploys
sed -i 's/^RUN_SEED_DATA=true/RUN_SEED_DATA=false/' "$APP_DIR/.env" || true

echo "============================================================"
echo " SETUP CONCLUÍDO COM SUCESSO!                               "
echo "============================================================"
sudo docker compose ps
