#!/usr/bin/env bash
#
# КЛЕОМЕД — развёртывание на чистой Ubuntu (проверено на 22.04 / 24.04 / 26.04).
#
# Запускать от root на новом сервере:
#     bash deploy.sh
#
# Скрипт идемпотентный: повторный запуск ничего не ломает и не затирает
# ни базу заявок, ни уже заданные ключи в /etc/kleomed/leads.env.
#
# Что делает:
#   1. Обновляет систему, ставит nginx, python3, certbot, sqlite3
#   2. Настраивает firewall: наружу открыты только 22, 80, 443
#   3. Заводит системного пользователя kleomed без права входа
#   4. Ставит сервис заявок и запускает его через systemd
#   5. Кладёт сайт и конфиг nginx
#
# Сертификат выпускается ОТДЕЛЬНО и только после того, как домен уже
# показывает на этот сервер — иначе Let's Encrypt не сможет подтвердить
# владение и выдаст ошибку. Команда напечатана в конце.

set -euo pipefail

DOMAIN_PUNY="xn--d1abasfhn.xn--p1ai"      # клеомед.рф
SITE_DIR="/var/www/kleomed/site"
APP_DIR="/opt/kleomed"
ENV_FILE="/etc/kleomed/leads.env"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Запускать от root: sudo bash deploy.sh" >&2
  exit 1
fi

# Каталог, где лежит сам скрипт — рядом с ним ожидаются leads.py и остальное.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say "Обновляю систему и ставлю пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# rsync и openssl обычно уже стоят, но на минимальных образах их может не быть,
# а без них скрипт упадёт на середине — дешевле указать явно.
apt-get install -y -qq nginx python3 sqlite3 certbot python3-certbot-nginx ufw rsync openssl curl

say "Проверяю подкачку"
# На сервере с 1 ГБ памяти обновление пакетов может упереться в потолок, и
# система убьёт что подвернётся — обычно nginx. Гигабайт подкачки стоит
# копейки на диске и снимает этот риск.
if [ "$(free -m | awk '/Swap:/ {print $2}')" -lt 256 ] && [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "подкачка 1 ГБ включена"
else
  echo "подкачка уже есть"
fi

say "Настраиваю firewall"
# Сервис заявок слушает только localhost, наружу его порт не открываем.
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null
ufw status numbered

say "Завожу пользователя kleomed"
if ! id kleomed >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin kleomed
  echo "пользователь создан"
else
  echo "пользователь уже есть"
fi

say "Ставлю сервис заявок"
install -d -m 755 "$APP_DIR"
install -m 644 "$HERE/leads.py" "$APP_DIR/leads.py"

install -d -m 750 /etc/kleomed
if [ -f "$ENV_FILE" ]; then
  echo "$ENV_FILE уже есть — не трогаю, ключи внутри сохранены"
else
  install -m 600 "$HERE/leads.env.example" "$ENV_FILE"
  # Ключи генерим сразу: пустые поля — самая частая причина, по которой
  # сервис потом молча не работает.
  IDENT_KEY="$(openssl rand -hex 32)"
  ADMIN_TOKEN="$(openssl rand -hex 24)"
  sed -i "s|^KLEOMED_IDENT_KEY=.*|KLEOMED_IDENT_KEY=$IDENT_KEY|"     "$ENV_FILE"
  sed -i "s|^KLEOMED_ADMIN_TOKEN=.*|KLEOMED_ADMIN_TOKEN=$ADMIN_TOKEN|" "$ENV_FILE"
  echo "ключи сгенерированы"
fi

install -m 644 "$HERE/kleomed-leads.service" /etc/systemd/system/kleomed-leads.service
systemctl daemon-reload
systemctl enable --now kleomed-leads
sleep 1
systemctl --no-pager --lines=0 status kleomed-leads | head -4

say "Кладу сайт"
install -d -m 755 /var/www/kleomed
if [ -d "$HERE/../site" ]; then
  rsync -a --delete "$HERE/../site/" "$SITE_DIR/"
  chown -R www-data:www-data /var/www/kleomed
  echo "страниц: $(find "$SITE_DIR" -maxdepth 1 -name '*.html' | wc -l)"
else
  echo "каталог site/ рядом не найден — залейте его в $SITE_DIR отдельно"
fi

say "Настраиваю nginx"
# До выпуска сертификата боевой конфиг с ssl_certificate не поднимется —
# файлов сертификата ещё нет. Поэтому сначала временный конфиг на 80 порту,
# он же нужен certbot для подтверждения владения доменом.
if [ -f "/etc/letsencrypt/live/$DOMAIN_PUNY/fullchain.pem" ]; then
  install -m 644 "$HERE/nginx.conf.sample" /etc/nginx/sites-available/kleomed
  echo "сертификат на месте — ставлю боевой конфиг"
else
  cat > /etc/nginx/sites-available/kleomed <<NGINX
# Временный конфиг: только 80 порт, до выпуска сертификата.
server {
    listen 80 default_server;
    server_name $DOMAIN_PUNY www.$DOMAIN_PUNY _;

    root $SITE_DIR;
    index index.html;
    charset utf-8;

    location /api/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }
    location ~ ^/(GetTickets|GetOngoingCalls|GetFinishedCalls|PostTimeTable)\$ {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }
    location /admin {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }
    location = /health {
        proxy_pass http://127.0.0.1:8081;
        access_log off;
    }
    location / {
        try_files \$uri \$uri.html \$uri/ =404;
    }
    error_page 404 /404.html;
}
NGINX
  echo "поставлен временный конфиг (без HTTPS)"
fi

ln -sf /etc/nginx/sites-available/kleomed /etc/nginx/sites-enabled/kleomed
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

say "Проверяю"
# reload у nginx асинхронный: старые рабочие процессы ещё доживают запросы,
# и проверка сразу после команды успевает получить ответ от прежнего конфига.
# Отсюда ложное «не отвечает» на совершенно здоровом сервисе.
check() {
  local url="$1" name="$2" i
  for i in 1 2 3 4 5; do
    if curl -sf -o /dev/null "$url"; then echo "  $name — отвечает"; return 0; fi
    sleep 1
  done
  echo "  ВНИМАНИЕ: $name не отвечает"
  return 1
}
check http://127.0.0.1/health "сервис заявок"
check http://127.0.0.1/       "сайт"

IP="$(curl -s4 --max-time 5 ifconfig.me || echo '<ip сервера>')"

cat <<FINAL

────────────────────────────────────────────────────────────────
 Готово. Сайт уже открывается по адресу:  http://$IP/

 Ключи (сохраните, второй раз показаны не будут):
FINAL
grep -E '^KLEOMED_(IDENT_KEY|ADMIN_TOKEN)=' "$ENV_FILE" | sed 's/^/   /'
cat <<FINAL

   Список заявок:  http://$IP/admin?token=<KLEOMED_ADMIN_TOKEN>
   Ключ IDENT     вписать в настройки IDENT, там же указать адрес
                  https://клеомед.рф/GetTickets

 ДАЛЬШЕ, когда домен будет показывать на этот сервер:

   certbot --nginx -d $DOMAIN_PUNY -d www.$DOMAIN_PUNY
   install -m 644 $HERE/nginx.conf.sample /etc/nginx/sites-available/kleomed
   nginx -t && systemctl reload nginx

 Telegram настраивается в $ENV_FILE,
 после правки:  systemctl restart kleomed-leads
────────────────────────────────────────────────────────────────
FINAL
