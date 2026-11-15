'use strict';

/* ===================== Настройки API ===================== */

const API_BASE = 'https://jsonplaceholder.typicode.com';
const POSTS_URL = `${API_BASE}/posts`;
// Для проверки ошибки 404 временно замените на `${API_BASE}/postz`
const GET_POSTS_URL = `${POSTS_URL}?_limit=5`;
const REQUEST_TIMEOUT_MS = 10000;
const USER_ID = 1;

const HTTP_STATUS_TEXT = {
  400: 'неверный запрос',
  401: 'требуется авторизация',
  403: 'доступ запрещён',
  404: 'ресурс не найден',
  429: 'слишком много запросов',
  500: 'внутренняя ошибка сервера',
  502: 'ошибка шлюза',
  503: 'сервис недоступен',
};

/* ===================== Состояние ===================== */

const state = {
  loadedPosts: [],   // публикации, полученные GET-запросом
  createdPosts: [],  // публикации, созданные POST-запросом в этой сессии
};

/* ===================== Элементы DOM ===================== */

const dom = {
  loadBtn: document.getElementById('load-btn'),
  list: document.getElementById('posts-list'),
  empty: document.getElementById('posts-empty'),

  form: document.getElementById('post-form'),
  title: document.getElementById('post-title'),
  body: document.getElementById('post-body'),
  createBtn: document.getElementById('create-btn'),

  message: document.getElementById('message'),
  messageText: document.getElementById('message-text'),

  createdResult: document.getElementById('created-result'),
  createdStatus: document.getElementById('created-status'),
  createdId: document.getElementById('created-id'),
  createdTitle: document.getElementById('created-title'),
};

/* ===================== Ошибки запросов ===================== */

class HttpError extends Error {
  constructor(status) {
    super(`HTTP ${status}`);
    this.name = 'HttpError';
    this.status = status;
  }
}

class TimeoutError extends Error {
  constructor() {
    super('Request timeout');
    this.name = 'TimeoutError';
  }
}

/** Понятный текст ошибки для пользователя. */
function getErrorMessage(error, action) {
  if (error instanceof HttpError) {
    const description = HTTP_STATUS_TEXT[error.status] || 'неуспешный ответ сервера';
    return `Не удалось ${action}: HTTP ${error.status} (${description}). Попробуйте ещё раз.`;
  }
  if (error instanceof TimeoutError) {
    return `Не удалось ${action}: сервер не ответил за ${REQUEST_TIMEOUT_MS / 1000} с. Попробуйте ещё раз.`;
  }
  if (error instanceof SyntaxError) {
    return `Не удалось ${action}: сервер вернул некорректный JSON.`;
  }
  // fetch выбрасывает TypeError при сетевом сбое (нет интернета, CORS, DNS)
  return `Не удалось ${action}: нет соединения с сервером. Проверьте интернет и попробуйте ещё раз.`;
}

/* ===================== Работа с сетью ===================== */

/**
 * Выполняет запрос и возвращает { status, data }.
 * Бросает HttpError при !response.ok, TimeoutError при превышении времени ожидания.
 */
async function requestJson(url, options = {}) {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) {
      throw new HttpError(response.status);
    }
    const data = await response.json();
    return { status: response.status, data };
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new TimeoutError();
    }
    throw error;
  } finally {
    clearTimeout(timerId);
  }
}

function fetchPosts() {
  return requestJson(GET_POSTS_URL);
}

function sendPost(post) {
  return requestJson(POSTS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=UTF-8' },
    body: JSON.stringify(post),
  });
}

/* ===================== Сообщения ===================== */

/** type: info | loading | success | error */
function showMessage(text, type) {
  dom.message.className = `message message-${type}`;
  dom.messageText.textContent = text;
}

function setButtonBusy(button, isBusy, busyText) {
  if (isBusy) {
    button.dataset.label = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

/* ===================== Отрисовка ===================== */

function createPostElement(post, isNew) {
  const li = document.createElement('li');
  li.className = isNew ? 'post post-new' : 'post';

  const meta = document.createElement('p');
  meta.className = 'post-meta';
  meta.textContent = `Публикация #${post.id} · пользователь ${post.userId}`;
  if (isNew) {
    const badge = document.createElement('span');
    badge.className = 'post-badge';
    badge.textContent = 'Создана';
    meta.append(badge);
  }

  const title = document.createElement('h3');
  title.className = 'post-title';
  title.textContent = post.title;

  const body = document.createElement('p');
  body.className = 'post-body';
  body.textContent = post.body;

  li.append(meta, title, body);
  return li;
}

function renderPosts() {
  const created = state.createdPosts.map((post) => createPostElement(post, true));
  const loaded = state.loadedPosts.map((post) => createPostElement(post, false));
  dom.list.replaceChildren(...created, ...loaded);
  dom.empty.hidden = created.length + loaded.length > 0;
}

function renderCreatedResult(status, post) {
  dom.createdStatus.textContent = String(status);
  dom.createdId.textContent = String(post.id);
  dom.createdTitle.textContent = post.title;
  dom.createdResult.hidden = false;
}

/* ===================== Валидация ===================== */

function validatePostForm() {
  const title = dom.title.value.trim();
  const body = dom.body.value.trim();
  const errors = {};

  if (title === '') {
    errors.title = 'Заголовок не может быть пустым.';
  }
  if (body === '') {
    errors.body = 'Текст публикации не может быть пустым.';
  }

  return { isValid: Object.keys(errors).length === 0, errors, data: { title, body } };
}

function setFieldError(input, message) {
  const errorEl = document.getElementById(`${input.id}-error`);
  errorEl.textContent = message;
  if (message) {
    input.setAttribute('aria-invalid', 'true');
  } else {
    input.removeAttribute('aria-invalid');
  }
}

function clearFormErrors() {
  setFieldError(dom.title, '');
  setFieldError(dom.body, '');
}

/* ===================== Обработчики ===================== */

async function handleLoadPosts() {
  setButtonBusy(dom.loadBtn, true, 'Загрузка...');
  showMessage('Загрузка публикаций с сервера...', 'loading');

  try {
    const { data } = await fetchPosts();
    if (!Array.isArray(data)) {
      throw new SyntaxError('Unexpected response format');
    }
    state.loadedPosts = data;
    renderPosts();
    showMessage(`Загружено публикаций: ${data.length}.`, 'success');
  } catch (error) {
    showMessage(getErrorMessage(error, 'загрузить публикации'), 'error');
  } finally {
    setButtonBusy(dom.loadBtn, false); // кнопка снова доступна для повторной попытки
  }
}

async function handleCreatePost(event) {
  event.preventDefault(); // без перезагрузки страницы

  clearFormErrors();
  const { isValid, errors, data } = validatePostForm();

  if (!isValid) {
    if (errors.title) setFieldError(dom.title, errors.title);
    if (errors.body) setFieldError(dom.body, errors.body);
    showMessage('Публикация не отправлена: заполните заголовок и текст.', 'error');
    (errors.title ? dom.title : dom.body).focus();
    return; // запрос не выполняется
  }

  setButtonBusy(dom.createBtn, true, 'Отправка...');
  showMessage('Отправка публикации на сервер...', 'loading');

  try {
    const { status, data: created } = await sendPost({ ...data, userId: USER_ID });
    state.createdPosts.unshift(created);
    renderPosts();
    renderCreatedResult(status, created);
    showMessage(`Публикация «${created.title}» успешно создана (ID ${created.id}).`, 'success');
    dom.form.reset();
  } catch (error) {
    showMessage(getErrorMessage(error, 'создать публикацию'), 'error');
  } finally {
    setButtonBusy(dom.createBtn, false);
  }
}

/** Убирает ошибку поля, как только пользователь начинает вводить текст. */
function handleFieldInput(event) {
  if (event.target.hasAttribute('aria-invalid') && event.target.value.trim() !== '') {
    setFieldError(event.target, '');
  }
}

/* ===================== Инициализация ===================== */

function init() {
  dom.loadBtn.addEventListener('click', handleLoadPosts);
  dom.form.addEventListener('submit', handleCreatePost);
  dom.form.addEventListener('input', handleFieldInput);
  renderPosts();
}

document.addEventListener('DOMContentLoaded', init);
