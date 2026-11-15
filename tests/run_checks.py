"""Автоматическая проверка ЛР3.

Страница открывается через локальный HTTP-сервер. Запросы к JSONPlaceholder
перехватываются Playwright и пересылаются на настоящий сервер (через requests),
поэтому данные и HTTP-статусы реальные. Режимы перехвата позволяют:
  hold   — задержать ответ, чтобы снять состояние загрузки;
  postz  — отправить GET на /postz (реальный 404), как требует задание;
  offline — оборвать запрос (имитация сетевого сбоя).
Запуск: python run_checks.py <папка_приложения> <папка_скриншотов>
"""
import os
import sys
import threading
import functools
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

APP = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)

CA = os.path.expanduser('~/.ccr/ca-bundle.crt')
VERIFY = CA if os.path.exists(CA) else True
SKIP_HEADERS = {'content-encoding', 'content-length', 'transfer-encoding', 'connection'}

results = []
mode = {'value': 'pass'}
held = []
log = []  # (method, url, status)


def check(name, cond):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def forward(route):
    req = route.request
    url = req.url
    if mode['value'] == 'postz' and req.method == 'GET':
        url = 'https://jsonplaceholder.typicode.com/postz'
    resp = requests.request(req.method, url, headers={k: v for k, v in req.headers.items()
                                                      if k.lower() not in ('host', 'origin', 'referer')},
                            data=req.post_data_buffer, verify=VERIFY, timeout=20)
    log.append((req.method, url, resp.status_code))
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in SKIP_HEADERS}
    headers['access-control-allow-origin'] = '*'
    route.fulfill(status=resp.status_code, headers=headers, body=resp.content)


def handler(route):
    if route.request.method == 'OPTIONS':
        route.fulfill(status=204, headers={
            'access-control-allow-origin': '*',
            'access-control-allow-methods': 'GET,POST,OPTIONS',
            'access-control-allow-headers': 'content-type',
        })
        return
    if mode['value'] == 'offline':
        log.append((route.request.method, route.request.url, 'aborted'))
        route.abort('internetdisconnected')
    elif mode['value'] == 'hold':
        held.append(route)
    else:
        forward(route)


def release_held():
    while held:
        forward(held.pop(0))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = HTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(APP)))
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f'http://127.0.0.1:{server.server_port}/index.html'

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--lang=ru-RU'],
                                env={'LANG': 'ru_RU.UTF-8', 'LANGUAGE': 'ru'})
    page = browser.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=1.5, locale='ru-RU')
    js_errors = []
    page.on('pageerror', lambda e: js_errors.append(str(e)))
    page.route('**/jsonplaceholder.typicode.com/**', handler)
    page.goto(URL)

    def msg():
        return page.text_content('#message-text')

    def msg_type():
        return page.get_attribute('#message', 'class')

    # Начальное состояние
    check('initial: no posts', page.locator('.post').count() == 0)
    check('initial: empty text', page.is_visible('#posts-empty'))
    page.screenshot(path=OUT / '01_initial.png', full_page=True)

    # GET: состояние загрузки
    mode['value'] = 'hold'
    page.click('#load-btn')
    page.wait_for_selector('#message.message-loading')
    check('GET loading: message', 'Загрузка' in msg())
    check('GET loading: button disabled', page.is_disabled('#load-btn'))
    page.screenshot(path=OUT / '02_get_loading.png', full_page=True)
    mode['value'] = 'pass'
    release_held()

    # GET: 5 публикаций
    page.wait_for_selector('#message.message-success')
    check('GET: 5 posts rendered', page.locator('.post').count() == 5)
    check('GET: titles and bodies present',
          all(t.strip() for t in page.locator('.post-title').all_text_contents())
          and all(b.strip() for b in page.locator('.post-body').all_text_contents()))
    check('GET: real status 200', log[-1][2] == 200 and '_limit=5' in log[-1][1])
    check('GET: button enabled again', page.is_enabled('#load-btn'))
    page.screenshot(path=OUT / '03_get_success.png', full_page=True)

    # POST: валидация — пустые поля и пробелы
    before = len(log)
    page.click('#create-btn')
    check('validation empty: title error', page.text_content('#post-title-error') != '')
    check('validation empty: body error', page.text_content('#post-body-error') != '')
    page.fill('#post-title', '     ')
    page.fill('#post-body', '   \n   ')
    page.click('#create-btn')
    page.wait_for_timeout(300)
    check('validation spaces: errors shown', page.text_content('#post-title-error') != ''
          and page.text_content('#post-body-error') != '')
    check('validation: message error', 'message-error' in msg_type())
    check('validation: no request sent', len(log) == before and not held)
    page.screenshot(path=OUT / '04_validation_error.png', full_page=True)

    # POST: состояние отправки
    page.fill('#post-title', '  Итоги лабораторной работы №3  ')
    page.fill('#post-body', 'Освоены fetch, async/await, обработка JSON и ошибок HTTP.')
    mode['value'] = 'hold'
    page.click('#create-btn')
    page.wait_for_selector('#message.message-loading')
    check('POST sending: message', 'Отправка' in msg())
    check('POST sending: button disabled', page.is_disabled('#create-btn'))
    post_req = held[0].request
    check('POST: method and content-type', post_req.method == 'POST'
          and 'application/json' in post_req.headers.get('content-type', ''))
    payload = post_req.post_data_json
    check('POST: body {title, body, userId:1} trimmed',
          payload == {'title': 'Итоги лабораторной работы №3',
                      'body': 'Освоены fetch, async/await, обработка JSON и ошибок HTTP.', 'userId': 1})
    page.screenshot(path=OUT / '05_post_sending.png', full_page=True)
    mode['value'] = 'pass'
    release_held()

    # POST: успех
    page.wait_for_selector('#message.message-success')
    check('POST: real status 201', log[-1][2] == 201)
    check('POST: success message', 'успешно создана' in msg())
    check('POST: status shown', page.text_content('#created-status') == '201')
    check('POST: id shown', page.text_content('#created-id') == '101')
    check('POST: title shown', page.text_content('#created-title') == 'Итоги лабораторной работы №3')
    check('POST: new post on top', page.locator('.post').first.get_attribute('class') == 'post post-new')
    check('POST: form cleared', page.input_value('#post-title') == '')
    page.screenshot(path=OUT / '06_post_success.png', full_page=True)

    # Ошибка 404 (GET на /postz)
    mode['value'] = 'postz'
    page.click('#load-btn')
    page.wait_for_selector('#message.message-error')
    check('404: real status 404', log[-1][2] == 404 and log[-1][1].endswith('/postz'))
    check('404: message', 'HTTP 404' in msg())
    check('404: button enabled for retry', page.is_enabled('#load-btn'))
    page.screenshot(path=OUT / '07_get_404.png', full_page=True)

    # Повторная попытка после восстановления адреса
    mode['value'] = 'pass'
    page.click('#load-btn')
    page.wait_for_selector('#message.message-success')
    check('retry: 5 posts + created', page.locator('.post').count() == 6)
    page.screenshot(path=OUT / '08_retry_success.png', full_page=True)

    # Сетевой сбой
    mode['value'] = 'offline'
    page.click('#load-btn')
    page.wait_for_selector('#message.message-error')
    check('offline GET: message', 'нет соединения' in msg())
    check('offline GET: button enabled', page.is_enabled('#load-btn'))
    page.fill('#post-title', 'Публикация без сети')
    page.fill('#post-body', 'Проверка обработки сетевой ошибки при POST.')
    page.click('#create-btn')
    page.wait_for_selector('#message.message-error')
    check('offline POST: message', 'создать публикацию' in msg() and 'нет соединения' in msg())
    check('offline POST: button enabled', page.is_enabled('#create-btn'))
    check('offline POST: form data kept', page.input_value('#post-title') == 'Публикация без сети')
    page.screenshot(path=OUT / '09_network_error.png', full_page=True)

    check('no JS errors', not js_errors)
    browser.close()

server.shutdown()
failed = [n for n, ok in results if not ok]
print(f'\n{len(results) - len(failed)}/{len(results)} passed')
sys.exit(1 if failed else 0)
