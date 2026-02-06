# Чек-лист данных для запуска бота

Подготовьте данные ниже **до** этапа реализации. Без них код не сможет корректно подключиться к Adapty и Telegram.

---

## 1. Токены и ключи

### 1.1 Telegram Bot Token

- **Что нужно:** один токен бота в формате `123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
- **Где взять:**
  1. Откройте Telegram, найдите [@BotFather](https://t.me/BotFather).
  2. Отправьте команду `/newbot` (или для существующего бота — `/mybots` → выбрать бота → API Token).
  3. Укажите имя и username бота (например: `Adapty Stats Bot`, `adapty_stats_bot`).
  4. BotFather пришлёт **токен** — скопируйте его и храните как `TELEGRAM_BOT_TOKEN`.

### 1.2 Adapty Secret API Key (для каждого приложения)

- **Что нужно:** по одному **Secret API Key** на каждое из 3 (или больше) приложений в Adapty.
- **Где взять:**
  1. Войдите в [Adapty Dashboard](https://app.adapty.io).
  2. Выберите нужное приложение (или переключитесь между приложениями).
  3. Откройте **Settings** → **App settings** (или [app.adapty.io/settings/general](https://app.adapty.io/settings/general)).
  4. В блоке **Secret key** скопируйте ключ. Формат обычно: `secret_live_...` или `secret_sandbox_...`.
  5. Повторите для второго и третьего приложений.

Итого: 3 ключа — например, `ADAPTY_API_KEY_APP1`, `ADAPTY_API_KEY_APP2`, `ADAPTY_API_KEY_APP3` (имена переменных задаём в конфиге).

---

## 2. Telegram Chat ID

- **Что нужно:** числовой **Chat ID** чата (или канала), куда бот будет слать отчёт.
- **Как получить:**
  1. Добавьте вашего бота в нужный чат (или создайте личный чат с ботом).
  2. Напишите в этот чат любое сообщение (например: `Hello`).
  3. Откройте в браузере (подставьте ваш токен):
     ```
     https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
     ```
  4. В ответе JSON найдите `"chat":{"id": -123456789}` — число `id` и есть **Chat ID** (может быть отрицательным для групп/каналов).
  5. Сохраните его как `TELEGRAM_CHAT_ID`.

Альтернатива: использовать ботов вроде [@userinfobot](https://t.me/userinfobot) в личке — он покажет ваш ID; для групп/каналов по-прежнему удобен `getUpdates` после сообщения в чат.

---

## 3. Adapty API: эндпоинты и формат

### 3.1 Базовые сведения (подтвердите по актуальной документации)

- **Документация:** [Exporting analytics with API](https://adapty.io/docs/export-analytics-api), [Authorization](https://adapty.io/docs/export-analytics-api-authorization), [Requests](https://adapty.io/docs/export-analytics-api-requests).
- **Авторизация:** заголовок `Authorization: Api-Key <SECRET_API_KEY>`.
- **Заголовки:** `Content-Type: application/json`, по желанию `Adapty-Tz: Europe/Minsk`.
- **Метод:** POST. Базовый URL и путь к эндпоинту — см. официальную API-документацию или Postman-коллекцию.

### 3.2 Какой эндпоинт использовать

- Для **MRR** и общих метрик выручки используется операция **Retrieve analytics data** (в доке — [Retrieve analytics data](https://adapty.io/docs/api-export-analytics#/operations/retrieveAnalyticsData)).
- Точный **URL** (например, `https://api.adapty.io/...` или другой), **тело запроса** (app_id, даты, группировки и т.д.) и **формат ответа** (CSV/JSON, названия полей) нужно взять из:
  - актуальной страницы API Reference на сайте Adapty, или
  - [Postman-коллекции](https://adapty.io/docs/export-analytics-api-requests) (переменные и примеры запросов).

В чек-листе ниже укажите то, что вы выпишете из документации.

### 3.3 Сведения из документации (реализовано)

| Пункт | Значение |
|-------|----------|
| Базовый URL API | `https://api-admin.adapty.io` |
| Путь "Retrieve analytics data" | `api/v1/client-api/metrics/analytics/` |
| Тело запроса | `chart_id` (mrr/installs), `filters: { date: ["YYYY-MM-DD", "YYYY-MM-DD"] }`, `period_unit: "day"` |
| Приложение | Определяется по Secret API Key (ключ привязан к приложению в Adapty) |
| Формат ответа | JSON: `data[chart_id].value` (MRR — число, Installs — число) |
| MRR и Installs | Один эндпоинт, два запроса: `chart_id: "mrr"` и `chart_id: "installs"` |

### 3.4 Формат данных на выходе (для кода)

После того как вы проверите ответ API в Postman или в доке, зафиксируйте:

- Названия полей, по которым мы берём **MRR** (total и за выбранный период для дельты за 24ч).
- Названия полей или источник для **Installs** (total и за последние 24ч).
- В какой валюте приходит MRR (доллары/евро и т.д.) — для отображения в отчёте ($ по ТЗ).

Это нужно, чтобы в коде правильно парсить ответ и считать дельты.

---

## 4. Имена приложений для отчёта

Подготовьте **отображаемые названия** для каждого приложения (как в примере: "App Name 1", "App Name 2", "App Name 3"). Они будут использоваться в заголовках блоков отчёта в Telegram.

---

## 5. Итоговый чек-лист перед этапом 2

- [ ] `TELEGRAM_BOT_TOKEN` — получен от BotFather.
- [ ] `TELEGRAM_CHAT_ID` — получен через getUpdates или бота.
- [ ] Три (или больше) Adapty Secret API Key — скопированы из App Settings для каждого приложения.
- [ ] Из документации/Postman выписаны: базовый URL, путь эндпоинта, тело запроса, структура ответа для MRR и Installs.
- [ ] Решено, откуда брать Installs (какой эндпоинт/поля).
- [ ] Подготовлены названия приложений для отчёта.

Когда всё отмечено и данные готовы — можно переходить к **Этапу 2 (реализация)**.
