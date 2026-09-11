#!/usr/bin/env bash
# Подключение уведомлений MAX. Запускать от root:
#     bash /opt/kleomed/max-setup.sh <ТОКЕН_БОТА>
#
# Скрипт вписывает токен, ждёт вашего сообщения боту, сам определяет chat_id,
# сохраняет его и отправляет пробное уведомление. Токен нигде не печатается.
set -u
ENV_FILE=/etc/kleomed/leads.env

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo "Укажите токен бота:  bash /opt/kleomed/max-setup.sh <ТОКЕН>" >&2
  exit 1
fi
TOKEN="$1"

# Правим через python: sed споткнётся о символы вроде / и & внутри токена.
python3 - "$ENV_FILE" "$TOKEN" <<'PY'
import io, sys
path, token = sys.argv[1], sys.argv[2]
out = []
for line in io.open(path, encoding='utf-8'):
    if line.startswith('KLEOMED_MAX_TOKEN='):
        line = 'KLEOMED_MAX_TOKEN=%s\n' % token
    out.append(line)
io.open(path, 'w', encoding='utf-8', newline='\n').writelines(out)
PY
chmod 600 "$ENV_FILE"
echo "Токен сохранён."
echo
echo "Теперь откройте MAX и напишите своему боту любое сообщение."
echo "Жду..."

set -a; . "$ENV_FILE"; set +a
CHATS="$(python3 /opt/kleomed/leads.py --chats)"
echo "$CHATS"

CHAT_ID="$(printf '%s\n' "$CHATS" | sed -n 's/.*chat_id=\([-0-9]\{1,\}\).*/\1/p' | head -1)"
if [ -z "$CHAT_ID" ]; then
  echo
  echo "chat_id не определился. Напишите боту и запустите команду ещё раз." >&2
  exit 1
fi

python3 - "$ENV_FILE" "$CHAT_ID" <<'PY'
import io, sys
path, chat = sys.argv[1], sys.argv[2]
out = []
for line in io.open(path, encoding='utf-8'):
    if line.startswith('KLEOMED_MAX_CHAT='):
        line = 'KLEOMED_MAX_CHAT=%s\n' % chat
    out.append(line)
io.open(path, 'w', encoding='utf-8', newline='\n').writelines(out)
PY
echo
echo "Адрес получателя сохранён: chat_id=$CHAT_ID"

systemctl restart kleomed-leads
sleep 2
systemctl is-active kleomed-leads >/dev/null || { echo "Сервис не поднялся" >&2; exit 1; }

echo "Отправляю пробную заявку..."
curl -s -X POST http://127.0.0.1/api/lead -H 'Content-Type: application/json' -d '{
 "name":"Пробная заявка","phone":"+79119377727","service":"Имплантация",
 "time_pref":"Вечер","page":"/implantaciya.html","consent":true}' >/dev/null
sleep 3
sqlite3 /var/lib/kleomed/leads.db "DELETE FROM leads WHERE name='Пробная заявка';"

echo
journalctl -u kleomed-leads --no-pager -n 6 | grep -i "max\|заявка" | tail -3
echo
echo "Готово. Проверьте MAX — там должно быть сообщение с именем и телефоном."
echo "Если сообщения нет, покажите строки журнала выше."
