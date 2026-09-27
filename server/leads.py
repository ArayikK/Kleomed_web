#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КЛЕОМЕД — приём заявок с сайта.

Зачем отдельный сервис, а не «форма шлёт письмо»:

1. Заявка обязана попасть в CRM и не потеряться, если та в этот момент
   недоступна. Поэтому порядок такой: сначала запись в свою базу, ответ
   пациенту — и только потом отправка в Битрикс24. Не принял (лежит портал,
   моргнула сеть, упёрлись в лимит запросов) — дошлём фоновым повтором.
   «Форма шлёт письмо» так не умеет: не дошло — и никто не узнал.

   Рядом остались точки GET /GetTickets и /GetOngoingCalls: их опрашивает
   IDENT, если клиника когда-нибудь к нему вернётся. Пока ключ не задан,
   они отвечают 503 и никому не мешают.

2. Данные пациентов по 152-ФЗ ст. 18 ч. 5 должны попадать в базу на территории
   РФ. Поэтому первичное хранилище — SQLite прямо на российском сервере, и
   только оттуда данные расходятся дальше.

3. В MAX уходит ПОЛНЫЙ состав заявки: имя, телефон, услуга, пожелание по
   времени и страница. Так владелец клиники перезванивает прямо из
   мессенджера, не открывая ни CRM, ни /admin.

   Раньше сигнал был обезличенным — из-за Telegram: его серверы за рубежом,
   а в карточке клиники в реестре РКН трансграничная передача помечена
   «Нет». У MAX серверы в России, и этот довод отпал.

   Что остаётся помнить: сам факт обращения к стоматологу — врачебная тайна
   (323-ФЗ ст. 13). Значит, чат с ботом должен быть личным чатом владельца,
   а не общей группой, и доступ к телефону с этим чатом — тоже под замком.
   Вернуть обезличенный сигнал можно настройкой KLEOMED_MAX_DETAILS=0.

Зависимостей нет — только стандартная библиотека. На потоке в десятки заявок
в месяц этого с запасом хватает, а разворачивается такой сервис на любом VPS
без pip, venv и сюрпризов при обновлении.
"""

import contextlib
import hmac
import json
import logging
import os
import re
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------- настройки

HOST = os.environ.get('KLEOMED_HOST', '127.0.0.1')
PORT = int(os.environ.get('KLEOMED_PORT', '8081'))
DB_PATH = os.environ.get('KLEOMED_DB', '/var/lib/kleomed/leads.db')

# Ключ, которым IDENT подписывает свои запросы. Задаётся в настройках IDENT
# и здесь — строки должны совпадать. Пустой ключ = интеграция выключена.
IDENT_KEY = os.environ.get('KLEOMED_IDENT_KEY', '')

# Токен для страницы со списком заявок. Нужен, пока IDENT не подключён:
# администратору где-то надо видеть телефон, чтобы перезвонить.
ADMIN_TOKEN = os.environ.get('KLEOMED_ADMIN_TOKEN', '')

# MAX — российский мессенджер. Токен выдаёт @MasterBot по команде /create,
# chat_id узнаётся запуском:  python3 leads.py --chats
MAX_TOKEN = os.environ.get('KLEOMED_MAX_TOKEN', '')
MAX_CHAT = os.environ.get('KLEOMED_MAX_CHAT', '')
# Слать ли в мессенджер имя, телефон и услугу. Решение владельца клиники —
# см. шапку файла. '0' возвращает обезличенный сигнал «пришла заявка №N».
MAX_DETAILS = os.environ.get('KLEOMED_MAX_DETAILS', '1') != '0'
# Домен вынесен в настройку: в документации MAX встречаются оба варианта,
# и если один перестанет отвечать, правка займёт одну строку в env-файле.
MAX_API = os.environ.get('KLEOMED_MAX_API', 'https://platform-api2.max.ru')
# Сертификат *.max.ru выпущен УЦ Минцифры («Russian Trusted Root CA»), которого
# нет в стандартном хранилище Ubuntu, — без него проверка TLS падает с
# «unable to get local issuer certificate». Корень держим отдельным файлом и
# применяем ТОЛЬКО к запросам в MAX: положить его в системный trust-store
# значит доверить этому УЦ любой домен на всей машине, чего для сервера
# с данными пациентов делать не стоит. Битрикс ходит по системному хранилищу.
MAX_CA = os.environ.get('KLEOMED_MAX_CA', '')

# Битрикс24. Входящий вебхук: Приложения → Разработчикам → Другое →
# «Входящий вебхук», право crm. Адрес вида
#     https://ваш-портал.bitrix24.ru/rest/1/xxxxxxxxxxxxxxxx/
# В самом адресе и пользователь, и секрет — он равносилен паролю, поэтому
# живёт только в /etc/kleomed/leads.env и никогда в git. Пусто = выключено:
# заявки продолжают приниматься и копиться в базе.
B24_HOOK = os.environ.get('KLEOMED_B24_HOOK', '')
# Что заводить в CRM. 'lead' — лид, 'deal' — контакт и сделка. Новые порталы
# Битрикса по умолчанию идут в «простом режиме», где лидов нет вовсе, и там
# crm.lead.add вернёт ошибку — для таких порталов и сделан режим 'deal'.
B24_ENTITY = os.environ.get('KLEOMED_B24_ENTITY', 'lead').strip().lower()
# Ответственный. Пусто — Битрикс назначит сам по правилам распределения.
B24_ASSIGNED = os.environ.get('KLEOMED_B24_ASSIGNED', '').strip()
# Источник из справочника CRM. WEB («Сайт») есть на любом портале.
B24_SOURCE = os.environ.get('KLEOMED_B24_SOURCE', 'WEB').strip()

# amoCRM — CRM клиники (с сентября 2026). Нужны адрес аккаунта и
# долгосрочный токен: Настройки → Интеграции → «Создать интеграцию» →
# вкладка «Ключи и доступы» → «Долгосрочный токен». Токен равносилен
# паролю — живёт только в /etc/kleomed/leads.env. Пусто = выключено.
#     KLEOMED_AMO_DOMAIN=kleomed.amocrm.ru
AMO_DOMAIN = os.environ.get('KLEOMED_AMO_DOMAIN', '').strip()
AMO_TOKEN = os.environ.get('KLEOMED_AMO_TOKEN', '').strip()
# Воронка и этап. Пусто — первый этап основной воронки. id печатает
#     python3 leads.py --amo-pipelines
AMO_PIPELINE = os.environ.get('KLEOMED_AMO_PIPELINE', '').strip()
AMO_STATUS = os.environ.get('KLEOMED_AMO_STATUS', '').strip()
# Ответственный (id пользователя amoCRM). Пусто — владелец токена.
AMO_RESPONSIBLE = os.environ.get('KLEOMED_AMO_RESPONSIBLE', '').strip()
AMO_TAG = os.environ.get('KLEOMED_AMO_TAG', 'Сайт').strip()


def crm_enabled():
    """Включена ли хоть одна CRM. amoCRM главнее: если заданы обе,
    заявки идут в amo."""
    return bool((AMO_DOMAIN and AMO_TOKEN) or B24_HOOK)


CRM_RETRY_EVERY = 300        # как часто пробовать дослать, секунд
CRM_RETRY_MAX = 24           # сколько попыток, дальше — только руками
CRM_RETRY_AGE = 7 * 86400    # заявки старше уже не дёргаем

# Москва круглый год +03:00, перевода часов в России нет — фиксированный
# сдвиг здесь точнее, чем zoneinfo, которого может не оказаться на сервере.
MSK = timezone(timedelta(hours=3))

MAX_BODY = 8 * 1024          # заявка не может быть большой
RATE_WINDOW = 600            # окно антифлуда, секунд
RATE_SAVED = 5               # сохранённых заявок с одного адреса за окно
RATE_TRIES = 25              # всего обращений к /api/lead за окно

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger('kleomed')

# ------------------------------------------------------------------ хранилище

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts  REAL    NOT NULL,
  name        TEXT    NOT NULL,
  phone       TEXT    NOT NULL,
  service     TEXT    NOT NULL DEFAULT '',
  time_pref   TEXT    NOT NULL DEFAULT '',
  form_name   TEXT    NOT NULL DEFAULT '',
  page        TEXT    NOT NULL DEFAULT '',
  referer     TEXT    NOT NULL DEFAULT '',
  utm_source  TEXT    NOT NULL DEFAULT '',
  utm_medium  TEXT    NOT NULL DEFAULT '',
  utm_campaign TEXT   NOT NULL DEFAULT '',
  utm_term    TEXT    NOT NULL DEFAULT '',
  utm_content TEXT    NOT NULL DEFAULT '',
  ip_hash     TEXT    NOT NULL DEFAULT '',
  -- Доставка в CRM: id заведённой карточки и число попыток. Пустой crm_id
  -- при ненулевых попытках — заявка, которую Битрикс пока не принял.
  crm_id      TEXT    NOT NULL DEFAULT '',
  crm_tries   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS leads_created ON leads(created_ts);
"""


@contextlib.contextmanager
def db():
    """Соединение на запрос. Дешевле, чем разбираться с потокобезопасностью
    одного общего соединения ради нагрузки в пару заявок в день.

    Именно контекстный менеджер, а не голый connect(): у sqlite3 `with conn`
    фиксирует транзакцию, но соединение НЕ закрывает — на долгоживущем сервисе
    дескрипторы копились бы до упора."""
    d = os.path.dirname(DB_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        # База, созданная до появления CRM, полей доставки не знает.
        # CREATE TABLE IF NOT EXISTS её не тронет, поэтому добавляем руками:
        # пересоздавать базу с настоящими заявками — не вариант.
        have = {r['name'] for r in conn.execute('PRAGMA table_info(leads)')}
        for col, decl in (('crm_id', "TEXT NOT NULL DEFAULT ''"),
                          ('crm_tries', 'INTEGER NOT NULL DEFAULT 0')):
            if col not in have:
                conn.execute('ALTER TABLE leads ADD COLUMN %s %s' % (col, decl))
                log.info('в базу добавлено поле %s', col)
    log.info('база готова: %s', DB_PATH)


# ------------------------------------------------------------------ проверки

DIGITS = re.compile(r'\D')


def clean_phone(raw):
    """Возвращает телефон в виде +7XXXXXXXXXX либо None."""
    d = DIGITS.sub('', raw or '')
    if len(d) == 11 and d[0] == '8':
        d = '7' + d[1:]
    if len(d) == 11 and d[0] == '7':
        return '+' + d
    return None


def clip(value, limit):
    return (value or '').strip()[:limit]


class RateLimiter:
    """Примитивный антифлуд в памяти. Перезапуск сервиса его обнуляет — и это
    нормально: цель не защита от атаки, а страховка от случайного двойного
    нажатия и от скрипта, который решит забить базу мусором.

    Счётчиков два, и это важно. Если считать все обращения подряд, человек,
    трижды опечатавшийся в телефоне, упрётся в лимит и не сможет записаться —
    мы своими руками потеряем пациента. Поэтому жёсткий лимит стоит только на
    успешно сохранённых заявках, а на попытки — мягкий и с большим запасом."""

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, bucket, limit):
        now = time.time()
        full = (bucket, key)
        with self._lock:
            hits = [t for t in self._hits.get(full, []) if now - t < RATE_WINDOW]
            if len(hits) >= limit:
                self._hits[full] = hits
                return False
            hits.append(now)
            self._hits[full] = hits
            if len(self._hits) > 5000:      # чтобы словарь не рос вечно
                self._hits = {k: v for k, v in self._hits.items()
                              if v and now - v[-1] < RATE_WINDOW}
            return True


limiter = RateLimiter()


# ------------------------------------------------------------------ MAX

def max_call(method, path, payload=None, timeout=8, params=None):
    """Один запрос к API MAX.

    Две тонкости, на которых легко обжечься, — обе из документации:
    токен передаётся ТОЛЬКО заголовком (query-параметр объявлен устаревшим),
    а адресат сообщения (chat_id) — наоборот, ТОЛЬКО query-параметром.
    Положить chat_id в тело, как напрашивается, значит отправить сообщение
    в никуда: разработчик видит успешный ответ, а получателя нет."""
    url = MAX_API.rstrip('/') + path
    if params:
        url += '?' + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, '')})
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': MAX_TOKEN,
        'Content-Type': 'application/json; charset=utf-8',
    })
    # cafile не дополняет системный набор, а заменяет его: для MAX доверенным
    # остаётся ровно один УЦ — тот, что выпустил сертификат *.max.ru.
    ctx = ssl.create_default_context(cafile=MAX_CA) if MAX_CA         else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        body = r.read().decode('utf-8')
        return r.status, (json.loads(body) if body.strip() else {})


def notify(row):
    """Уведомление администратору о новой заявке.

    По умолчанию уходит полный состав: имя, телефон, услуга, пожелание по
    времени и страница, с которой человек писал. Так администратор может
    перезвонить прямо из мессенджера, не открывая ни CRM, ни /admin —
    ради этого всё и делалось.

    Обратная сторона: переписка бота становится ещё одним местом, где лежат
    данные пациентов. Поэтому чат должен быть личным чатом владельца, а не
    общей группой. Вернуть обезличенный сигнал можно одной настройкой,
    KLEOMED_MAX_DETAILS=0, ничего не переписывая."""
    if not MAX_TOKEN or not MAX_CHAT:
        return

    lead_id = row['id']
    created_ts, name, phone = row['created_ts'], row['name'], row['phone']
    service, time_pref = row['service'], row['time_pref']
    page, referer = row['page'], row['referer']
    utm_source, utm_medium = row['utm_source'], row['utm_medium']

    when = datetime.fromtimestamp(created_ts, MSK).strftime('%d.%m в %H:%M')

    if not MAX_DETAILS:
        lines = ['Новая заявка № {} · {}'.format(lead_id, when)]
        if time_pref:
            lines[0] += ' · пожелание: {}'.format(time_pref)
        lines.append('Данные — в CRM или в списке заявок.')
    else:
        lines = ['Новая заявка № {} · {}'.format(lead_id, when), '']
        lines.append('Имя: {}'.format(name))
        # Телефон отдельной строкой и без лишних знаков — так его удобно
        # выделить и набрать прямо из мессенджера.
        lines.append('Телефон: {}'.format(phone))
        if service:
            lines.append('Услуга: {}'.format(service))
        if time_pref:
            lines.append('Удобное время: {}'.format(time_pref))

        tail = []
        if page:
            tail.append('Страница: {}'.format(page))
        if utm_source:
            tail.append('Источник: {}'.format(
                ' / '.join(x for x in (utm_source, utm_medium) if x)))
        elif referer:
            tail.append('Пришёл с: {}'.format(referer))
        if tail:
            lines.append('')
            lines.extend(tail)

    text = chr(10).join(lines)

    try:
        # chat_id — именно параметр адреса, не поле тела. См. max_call().
        code, data = max_call('POST', '/messages', {'text': text},
                              params={'chat_id': MAX_CHAT})
        if code >= 300:
            log.warning('MAX ответил кодом %s: %s', code, data)
    except Exception as e:                      # noqa: BLE001
        # Заявка уже сохранена — молчащий мессенджер не повод её терять.
        log.warning('MAX не ответил: %s', e)


def list_chats():
    """Печатает chat_id, куда бот может писать.

    Раньше здесь был GET /chats, но с июня 2026 этот метод в API отключён.
    Теперь единственный способ узнать адрес — прочитать события: человек
    пишет боту, а в событии приходит chat_id. Поэтому команда просит
    написать боту и ждёт сообщения, а не спрашивает готовый список."""
    if not MAX_TOKEN:
        print('Не задан KLEOMED_MAX_TOKEN. Впишите его в /etc/kleomed/leads.env')
        return 1

    print('Напишите боту в MAX любое сообщение — жду до 60 секунд...')
    seen = {}
    try:
        # Два круга long polling по 30 секунд: столько занимает «сейчас открою
        # мессенджер и напишу». Один круг слишком часто истекает раньше.
        for _ in range(2):
            code, data = max_call('GET', '/updates', timeout=40,
                                  params={'timeout': 30, 'limit': 100})
            if code >= 300:
                print('API MAX ответил кодом %s: %s' % (code, data))
                return 1
            for upd in (data.get('updates') or []):
                msg = upd.get('message') or {}
                rec = msg.get('recipient') or {}
                chat_id = rec.get('chat_id') or upd.get('chat_id')
                if not chat_id:
                    continue
                who = (msg.get('sender') or {}).get('name') or rec.get('chat_type') or ''
                seen[chat_id] = who
            if seen:
                break
    except Exception as e:                      # noqa: BLE001
        print('Не удалось обратиться к API MAX: %s' % e)
        return 1

    if not seen:
        print('Сообщений не пришло. Проверьте, что бот запущен у @MasterBot')
        print('(команда /start в настройках бота) и что вы написали именно ему.')
        return 1

    print('Впишите нужный chat_id в KLEOMED_MAX_CHAT:')
    for chat_id, who in seen.items():
        print('  chat_id=%-18s %s' % (chat_id, who))
    return 0


# ------------------------------------------------------------- Битрикс24

def flatten(value, prefix=''):
    """Разворачивает вложенные словари и списки в плоские ключи вида
    `fields[PHONE][0][VALUE]`.

    REST Битрикса разбирает структуры именно в таком виде — это его формат
    входа, а не наша прихоть. Отправить те же данные красивым JSON нельзя:
    часть методов его просто не читает."""
    out = {}
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, (list, tuple)):
        items = enumerate(value)
    else:
        return {} if value is None else {prefix: value}
    for k, v in items:
        out.update(flatten(v, '%s[%s]' % (prefix, k) if prefix else str(k)))
    return out


def b24_call(method, payload, timeout=15):
    """Один вызов REST-метода Битрикс24 через входящий вебхук.

    Авторизации сверху нет: пользователь и секрет уже вшиты в сам адрес
    вебхука — он и есть ключ.

    На ошибку Битрикс отвечает кодом 400 и телом с описанием, и описание
    там куда полезнее кода («лидов нет в этом режиме CRM» против голого
    400). Поэтому тело читаем в обоих случаях."""
    url = B24_HOOK.rstrip('/') + '/' + method + '.json'
    data = urllib.parse.urlencode(flatten(payload)).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
    try:
        out = json.loads(body) if body.strip() else {}
    except ValueError:
        raise RuntimeError('ответ не разобрать: %s' % body[:200])
    if out.get('error'):
        raise RuntimeError('%s %s' % (out.get('error'),
                                      out.get('error_description', '')))
    return out.get('result')


def crm_comment(row):
    """Тело карточки. Всё, что человек указал, плюс откуда он пришёл —
    администратору этого хватает, чтобы перезвонить осмысленно."""
    lines = []
    if row['service']:
        lines.append('Услуга: ' + row['service'])
    # Точное время не выдумываем: форма спрашивает часть дня («утро», «день»,
    # «вечер»). Ставить из этого час в расписании — значит записать пациента
    # на то, о чём он не договаривался. Час назначает администратор.
    if row['time_pref']:
        lines.append('Удобное время: ' + row['time_pref'])
    if row['form_name']:
        lines.append('Форма: ' + row['form_name'])
    if row['page']:
        lines.append('Страница: ' + row['page'])
    if row['referer']:
        lines.append('Пришёл с: ' + row['referer'])
    lines.append('Заявка с сайта № {} от {}'.format(
        row['id'], datetime.fromtimestamp(row['created_ts'], MSK)
        .strftime('%d.%m.%Y %H:%M')))
    return chr(10).join(lines)


def crm_common(row):
    """Поля, одинаковые для лида и для сделки."""
    fields = {
        'SOURCE_ID': B24_SOURCE,
        'SOURCE_DESCRIPTION': row['form_name'] or 'Форма записи на сайте',
        'COMMENTS': crm_comment(row),
        'OPENED': 'Y',
    }
    for key in ('utm_source', 'utm_medium', 'utm_campaign',
                'utm_term', 'utm_content'):
        if row[key]:
            fields[key.upper()] = row[key]
    if B24_ASSIGNED:
        fields['ASSIGNED_BY_ID'] = B24_ASSIGNED
    return fields


def crm_create(row):
    """Заводит карточку и возвращает её id.

    Две ветки — не перестраховка. В «простом режиме», с которым Битрикс
    создаёт новые порталы, лидов не существует, и crm.lead.add там падает.
    Тогда нужен контакт со сделкой: телефон живёт на контакте, а сама
    заявка — на сделке."""
    title = 'Заявка с сайта № {}'.format(row['id'])
    if row['service']:
        title += ' — ' + row['service']
    phone = [{'VALUE': row['phone'], 'VALUE_TYPE': 'MOBILE'}]

    if B24_ENTITY == 'deal':
        contact = b24_call('crm.contact.add', {'fields': dict(
            crm_common(row), NAME=row['name'], PHONE=phone,
            TYPE_ID='CLIENT')})
        deal = b24_call('crm.deal.add', {'fields': dict(
            crm_common(row), TITLE=title[:250], CONTACT_ID=contact)})
        return 'сделка %s' % deal

    return b24_call('crm.lead.add', {'fields': dict(
        crm_common(row), TITLE=title[:250], NAME=row['name'], PHONE=phone)})


# ------------------------------------------------------------------ amoCRM

def amo_call(method, path, payload=None, timeout=15):
    """Один запрос к API amoCRM v4 с долгосрочным токеном.

    Как и у Битрикса, на ошибку amo отвечает телом с описанием (поле
    validation-errors подсказывает, какое именно поле не понравилось) —
    его и поднимаем в исключение, голый код 400 ничего не объясняет."""
    host = AMO_DOMAIN.replace('https://', '').replace('http://', '').strip('/')
    url = 'https://' + host + path
    data = (json.dumps(payload, ensure_ascii=False).encode('utf-8')
            if payload is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + AMO_TOKEN,
        'Content-Type': 'application/json; charset=utf-8'})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        raise RuntimeError('amoCRM %s: %s' % (e.code, body[:600]))
    return json.loads(body) if body.strip() else {}


def amo_note(row):
    """Примечание к сделке: всё из заявки плюс метки рекламы. Метки кладём
    текстом, а не в поля UTM: если в аккаунте этих полей нет, amo отклонил
    бы всю сделку целиком, и заявка не дошла бы вовсе."""
    lines = [crm_comment(row)]
    utm = ['%s=%s' % (k, row[k]) for k in ('utm_source', 'utm_medium',
           'utm_campaign', 'utm_term', 'utm_content') if row[k]]
    if utm:
        lines.append('Метки: ' + ', '.join(utm))
    return chr(10).join(lines)


def amo_create(row):
    """Сделка с контактом одним запросом (leads/complex) и примечание к ней.

    complex сам склеивает контакт с уже существующим по телефону, если в
    аккаунте включён контроль дублей, — повторный пациент не плодит
    карточки-близнецы."""
    title = 'Заявка с сайта № {}'.format(row['id'])
    if row['service']:
        title += ' — ' + row['service']
    lead = {
        'name': title[:250],
        '_embedded': {
            'contacts': [{
                'first_name': row['name'],
                'custom_fields_values': [{
                    'field_code': 'PHONE',
                    'values': [{'value': row['phone'], 'enum_code': 'MOB'}],
                }],
            }],
        },
    }
    if AMO_TAG:
        lead['_embedded']['tags'] = [{'name': AMO_TAG}]
    if AMO_PIPELINE:
        lead['pipeline_id'] = int(AMO_PIPELINE)
    if AMO_STATUS:
        lead['status_id'] = int(AMO_STATUS)
    if AMO_RESPONSIBLE:
        lead['responsible_user_id'] = int(AMO_RESPONSIBLE)

    out = amo_call('POST', '/api/v4/leads/complex', [lead])
    first = out[0] if isinstance(out, list) and out else {}
    lead_id = first.get('id')
    if not lead_id:
        raise RuntimeError('amoCRM не вернул id сделки: %s' % str(out)[:300])
    try:
        amo_call('POST', '/api/v4/leads/%s/notes' % lead_id, [{
            'note_type': 'common', 'params': {'text': amo_note(row)}}])
    except Exception as e:                      # noqa: BLE001
        # Сделка с телефоном уже есть — без примечания перезвонить можно.
        # Повторять всю отправку ради него значит завести дубль.
        log.warning('примечание к сделке %s не добавилось: %s', lead_id, e)
    return 'amo %s' % lead_id


def amo_pipelines():
    """Печатает воронки и этапы с их id — для KLEOMED_AMO_PIPELINE/STATUS.
    Заодно это проверка токена: ответил — значит, доступ есть."""
    if not (AMO_DOMAIN and AMO_TOKEN):
        print('Не заданы KLEOMED_AMO_DOMAIN и KLEOMED_AMO_TOKEN в /etc/kleomed/leads.env')
        return 1
    try:
        data = amo_call('GET', '/api/v4/leads/pipelines')
    except Exception as e:                      # noqa: BLE001
        print('Не удалось обратиться к amoCRM: %s' % e)
        return 1
    for p in (data.get('_embedded') or {}).get('pipelines', []):
        print('воронка %-10s %s%s' % (p['id'], p['name'],
                                     '  (основная)' if p.get('is_main') else ''))
        for st in (p.get('_embedded') or {}).get('statuses', []):
            print('    этап %-10s %s' % (st['id'], st['name']))
    return 0


def push_to_crm(row):
    """Отправляет заявку в CRM (amoCRM или Битрикс24) и запоминает исход.

    Заявка к этому моменту уже в SQLite и пациенту уже сказано «спасибо».
    Поэтому любая ошибка CRM — повод дослать позже, а не потерять человека:
    crm_id остаётся пустым, и фоновый повтор вернётся к этой строке."""
    if not crm_enabled():
        return False
    use_amo = bool(AMO_DOMAIN and AMO_TOKEN)
    crm_name = 'amoCRM' if use_amo else 'Битрикс24'
    lead_id = row['id']
    try:
        crm_id = amo_create(row) if use_amo else crm_create(row)
    except Exception as e:                      # noqa: BLE001
        with db() as conn:
            conn.execute(
                'UPDATE leads SET crm_tries = crm_tries + 1 WHERE id = ?',
                (lead_id,))
        log.warning('%s не принял заявку №%s: %s', crm_name, lead_id, e)
        return False
    with db() as conn:
        conn.execute(
            'UPDATE leads SET crm_id = ?, crm_tries = crm_tries + 1 '
            'WHERE id = ?', (str(crm_id), lead_id))
    log.info('заявка №%s заведена в %s: %s', lead_id, crm_name, crm_id)
    return True


def crm_retry_loop():
    """Фоновый дослальщик недоставленных заявок.

    Берём только свежие и только пока попытки не исчерпаны: заявка недельной
    давности, которую CRM так и не приняла, — это разговор с администратором,
    а не вечный стук в чужой API."""
    while True:
        time.sleep(CRM_RETRY_EVERY)
        if not crm_enabled():
            continue
        try:
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM leads WHERE crm_id = '' AND crm_tries < ? "
                    "AND created_ts > ? ORDER BY id LIMIT 20",
                    (CRM_RETRY_MAX, time.time() - CRM_RETRY_AGE)).fetchall()
            for row in rows:
                push_to_crm(row)
        except Exception as e:                  # noqa: BLE001
            log.warning('повтор отправки в CRM сорвался: %s', e)


def deliver(lead_id):
    """Что происходит после того, как заявка сохранена: сигнал в мессенджер
    и карточка в CRM. Выполняется в отдельном потоке — ответ пациенту не
    должен ждать ни MAX, ни Битрикс."""
    with db() as conn:
        row = conn.execute('SELECT * FROM leads WHERE id = ?',
                           (lead_id,)).fetchone()
    if row is None:
        return
    notify(row)
    push_to_crm(row)


# ------------------------------------------------------------------ формат дат

def iso(ts):
    """ISO 8601 со сдвигом через двоеточие — как требует документация IDENT."""
    return datetime.fromtimestamp(ts, MSK).isoformat(timespec='seconds')


def parse_dt(raw):
    """Разбирает дату из запроса IDENT. Формат по документации — ISO 8601,
    но сдвиг там может быть и с двоеточием, и без, а иногда его нет вовсе."""
    if not raw:
        return None
    s = raw.strip().replace(' ', 'T')
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    m = re.search(r'([+-]\d{2})(\d{2})$', s)
    if m:
        s = s[:m.start()] + m.group(1) + ':' + m.group(2)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.timestamp()


# ------------------------------------------------------------------ IDENT

def ticket(row):
    """Один объект «Заявка» в структуре, которую ждёт IDENT.

    PlanStart не заполняем: форма спрашивает не точное время, а часть дня
    («утро», «день», «вечер»). Подставлять сюда выдуманный час — значит
    занять слот в расписании тем, о чём пациент не договаривался. Пожелание
    уходит в Comment, а время назначает администратор."""
    comment = []
    if row['service']:
        comment.append('Услуга: ' + row['service'])
    if row['time_pref']:
        comment.append('Удобное время: ' + row['time_pref'])
    if row['page']:
        comment.append('Страница: ' + row['page'])

    return {
        'Id': 'kleomed-site-{}'.format(row['id']),
        'DateAndTime': iso(row['created_ts']),
        'ClientPhone': row['phone'],
        'ClientEmail': '',
        'FormName': row['form_name'] or 'Форма записи на сайте',
        'ClientFullName': row['name'],
        'Comment': '; '.join(comment),
        'UtmSource': row['utm_source'],
        'UtmMedium': row['utm_medium'],
        'UtmCampaign': row['utm_campaign'],
        'UtmTerm': row['utm_term'],
        'UtmContent': row['utm_content'],
        'HttpReferer': row['referer'],
    }


# ------------------------------------------------------------------ страницы

ADMIN_HTML = u"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="robots" content="noindex, nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Заявки — Клеомед</title><style>
body{{font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px;
background:#0d1512;color:#e8f3ee}}
h1{{font-size:20px;margin:0 0 4px}}
p.sub{{color:#8aa79a;margin:0 0 20px;font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th{{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
color:#8aa79a;font-weight:400;padding:8px 12px;border-bottom:1px solid #24352e}}
td{{padding:11px 12px;border-bottom:1px solid #1a2620;vertical-align:top}}
td.n{{color:#8aa79a;font-variant-numeric:tabular-nums;white-space:nowrap}}
a{{color:#5cd9a4}}
td.crm{{font-size:13px;color:#8aa79a;white-space:nowrap}}
td.crm.bad{{color:#ff9a6c}}
.empty{{color:#8aa79a;padding:30px 0}}
</style></head><body>
<h1>Заявки с сайта</h1>
<p class="sub">Всего: {total}. Страница закрыта от индексации; не пересылайте
её адрес — в нём токен доступа.</p>
{table}
</body></html>"""


def crm_cell(row):
    """Что показать в колонке «в CRM».

    Различаем три случая: карточка заведена, отправка ещё будет повторена,
    попытки исчерпаны. Последнее — сигнал администратору позвонить самому,
    не дожидаясь CRM."""
    if row['crm_id']:
        return '', esc(row['crm_id'])
    if not crm_enabled():
        return '', '—'
    if row['crm_tries'] < CRM_RETRY_MAX:
        return '', 'ждёт'
    return ' bad', 'не ушла'


def admin_page(rows):
    if not rows:
        return ADMIN_HTML.format(total=0, table='<p class="empty">Заявок пока нет.</p>')
    cells = []
    for r in rows:
        crm_class, crm_text = crm_cell(r)
        cells.append(
            '<tr><td class="n">{id}</td><td class="n">{when}</td><td>{name}</td>'
            '<td><a href="tel:{phone}">{phone}</a></td><td>{service}</td>'
            '<td>{time_pref}</td><td class="crm{crm_class}">{crm}</td></tr>'.format(
                id=r['id'],
                when=datetime.fromtimestamp(r['created_ts'], MSK).strftime('%d.%m %H:%M'),
                name=esc(r['name']), phone=esc(r['phone']),
                service=esc(r['service']) or '—',
                time_pref=esc(r['time_pref']) or 'любое',
                crm_class=crm_class, crm=crm_text,
            ))
    table = ('<table><tr><th>№</th><th>Когда</th><th>Имя</th><th>Телефон</th>'
             '<th>Услуга</th><th>Время</th><th>в CRM</th></tr>'
             + ''.join(cells) + '</table>')
    return ADMIN_HTML.format(total=len(rows), table=table)


def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = 'kleomed'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    # -------------------------------------------------------- утилиты ответа
    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, code, html):
        body = html.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Robots-Tag', 'noindex, nofollow')
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code, text):
        body = text.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def client_ip(self):
        # За nginx настоящий адрес приходит заголовком.
        fwd = self.headers.get('X-Forwarded-For', '')
        if fwd:
            return fwd.split(',')[0].strip()
        return self.client_address[0]

    def log_message(self, fmt, *args):
        log.info('%s %s', self.client_ip(), fmt % args)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/health':
            return self.send_text(200, 'ok')
        if path == '/GetTickets':
            return self.get_tickets(query)
        if path in ('/GetFinishedCalls', '/GetOngoingCalls'):
            # Телефонию через этот сервис не ведём, но IDENT может опросить
            # адрес — пустой список честнее, чем 404 в его журнале ошибок.
            if not self.check_ident_key():
                return
            return self.send_json(200, [])
        if path == '/admin':
            return self.get_admin(query)
        return self.send_json(404, {'error': 'not found'})

    def check_ident_key(self):
        if not IDENT_KEY:
            self.send_json(503, {'error': 'ident integration disabled'})
            return False
        given = self.headers.get('IDENT-Integration-Key', '')
        if not hmac.compare_digest(given, IDENT_KEY):
            self.send_json(401, {'error': 'bad integration key'})
            return False
        return True

    def get_tickets(self, query):
        if not self.check_ident_key():
            return

        ts_from = parse_dt((query.get('dateTimeFrom') or [''])[0])
        ts_to = parse_dt((query.get('dateTimeTo') or [''])[0])
        if ts_from is None or ts_to is None:
            return self.send_json(400, {'error': 'dateTimeFrom and dateTimeTo required'})

        try:
            limit = int((query.get('limit') or ['500'])[0])
            offset = int((query.get('offset') or ['0'])[0])
        except ValueError:
            return self.send_json(400, {'error': 'limit and offset must be integers'})
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)

        with db() as conn:
            rows = conn.execute(
                'SELECT * FROM leads WHERE created_ts >= ? AND created_ts <= ? '
                'ORDER BY created_ts, id LIMIT ? OFFSET ?',
                (ts_from, ts_to, limit, offset)).fetchall()
        self.send_json(200, [ticket(r) for r in rows])

    def get_admin(self, query):
        token = (query.get('token') or [''])[0]
        if not ADMIN_TOKEN or not hmac.compare_digest(token, ADMIN_TOKEN):
            return self.send_text(403, 'Нет доступа')
        with db() as conn:
            rows = conn.execute(
                'SELECT * FROM leads ORDER BY created_ts DESC LIMIT 300').fetchall()
        self.send_html(200, admin_page(rows))

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip('/') or '/'
        if path != '/api/lead':
            return self.send_json(404, {'error': 'not found'})

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send_json(400, {'ok': False, 'error': 'bad length'})
        if length <= 0 or length > MAX_BODY:
            return self.send_json(413, {'ok': False, 'error': 'too large'})

        try:
            data = json.loads(self.rfile.read(length).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {'ok': False, 'error': 'bad json'})
        if not isinstance(data, dict):
            return self.send_json(400, {'ok': False, 'error': 'bad json'})

        ip = self.client_ip()
        if not limiter.allow(ip, 'try', RATE_TRIES):
            return self.send_json(429, {
                'ok': False,
                'error': 'Слишком много попыток. Позвоните нам: +7 (911) 937-77-27',
            })

        # Согласие обязательно: без него у нас нет основания записывать
        # данные, а сама заявка о лечении — специальная категория ПДн.
        if not data.get('consent'):
            return self.send_json(400, {
                'ok': False,
                'error': 'Нужно согласие на обработку персональных данных',
            })

        name = clip(data.get('name'), 120)
        if not name:
            return self.send_json(400, {'ok': False, 'error': 'Укажите имя'})

        phone = clean_phone(data.get('phone'))
        if not phone:
            return self.send_json(400, {'ok': False, 'error': 'Введите номер полностью'})

        # Данные в порядке — вот теперь проверяем лимит на сами заявки.
        if not limiter.allow(ip, 'saved', RATE_SAVED):
            return self.send_json(429, {
                'ok': False,
                'error': 'Заявка уже принята. Если это ошибка, позвоните: +7 (911) 937-77-27',
            })

        row = (
            time.time(), name, phone,
            clip(data.get('service'), 120),
            clip(data.get('time'), 60),
            clip(data.get('form'), 60) or 'Форма записи на сайте',
            clip(data.get('page'), 200),
            clip(data.get('referer'), 300),
            clip(data.get('utm_source'), 120),
            clip(data.get('utm_medium'), 120),
            clip(data.get('utm_campaign'), 120),
            clip(data.get('utm_term'), 120),
            clip(data.get('utm_content'), 120),
            # Полный IP не храним: для антифлуда достаточно отпечатка, а лишние
            # данные о человеке — лишняя ответственность.
            hmac.new(b'kleomed-ip', ip.encode('utf-8'), 'sha256').hexdigest()[:16],
        )

        with db() as conn:
            cur = conn.execute(
                'INSERT INTO leads (created_ts,name,phone,service,time_pref,form_name,'
                'page,referer,utm_source,utm_medium,utm_campaign,utm_term,utm_content,'
                'ip_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', row)
            lead_id = cur.lastrowid

        log.info('заявка №%s сохранена', lead_id)

        # Ответ пациенту не должен ждать ни мессенджер, ни CRM: если они
        # тормозят, человек всё равно видит «спасибо» сразу.
        threading.Thread(target=deliver, args=(lead_id,), daemon=True).start()

        self.send_json(200, {'ok': True, 'id': lead_id})


def main():
    init_db()
    if not IDENT_KEY:
        log.warning('KLEOMED_IDENT_KEY не задан — /GetTickets отвечает 503')
    if not MAX_TOKEN or not MAX_CHAT:
        log.warning('MAX не настроен — уведомления не отправляются')
    if not ADMIN_TOKEN:
        log.warning('KLEOMED_ADMIN_TOKEN не задан — /admin закрыт')
    if AMO_DOMAIN and AMO_TOKEN:
        log.info('заявки уходят в amoCRM: %s', AMO_DOMAIN)
    elif not B24_HOOK:
        log.warning('CRM не настроена — заявки в CRM не уходят')
    elif B24_ENTITY not in ('lead', 'deal'):
        log.warning('KLEOMED_B24_ENTITY=%s — ожидается lead или deal',
                    B24_ENTITY)
    threading.Thread(target=crm_retry_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info('слушаю http://%s:%s', HOST, PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info('остановлен')


if __name__ == '__main__':
    if '--chats' in sys.argv:
        sys.exit(list_chats())
    if '--amo-pipelines' in sys.argv:
        sys.exit(amo_pipelines())
    main()
