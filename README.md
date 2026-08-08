# Adapty Daily Report Bot

Telegram-бот для ежедневной отчётности по метрикам Adapty (MRR, Installs). Хостинг: Railway.

## Репозиторий на GitHub

Локально уже выполнены `git init`, первый коммит и все файлы готовы к push.

**Если установлен GitHub CLI:**
```bash
cd "Adapty stats"
gh repo create adapty-stats --private --source=. --remote=origin --push
```
(Или `--public`, имя репозитория по желанию.)

**Если репозиторий создаёте вручную на GitHub:**
1. На [github.com/new](https://github.com/new) создайте репозиторий (например `adapty-stats`), без README.
2. Выполните в каталоге проекта:
   ```bash
   git remote add origin https://github.com/<ВАШ_USERNAME>/adapty-stats.git
   git push -u origin main
   ```

## Локальный запуск

1. Клонировать репозиторий и перейти в каталог:
   ```bash
   git clone <repo-url> && cd "Adapty stats"
   ```

2. Создать виртуальное окружение и установить зависимости:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Скопировать `.env.example` в `.env` и заполнить переменные (токен бота, Chat ID, ключи Adapty, имена приложений).

4. Проверка конфига и тестовая отправка:
   ```bash
   python main.py --health
   python main.py --test-send
   ```

5. Запуск планировщика (ежедневный отчёт в 09:00 Europe/Minsk):
   ```bash
   python main.py
   ```

## A/B-отчёт: Secret API, preview и единичная отправка

Путь A/B-отчёта использует только Adapty Export Analytics API с заголовком
`Authorization: Api-Key <Secret API Key>`. Для него не используются Dashboard,
WebView-сессия, `ADAPTY_DASHBOARD_TOKEN`, `ADAPTY_DASHBOARD_COMPANY_ID` или
`ADAPTY_DASHBOARD_APP_ID`: эти переменные относятся исключительно к Apple Ads.

Production A/B-отчёт намеренно pinned к одному согласованному эксперименту.
При включённом отчёте код принимает только эту точную identity-конфигурацию:

- `AB_TEST_APP_INDEX=1`, `ADAPTY_APP_NAME_1=Unfollowers: Follow & Unfollow`;
- `AB_TEST_ID=1db6e378-026f-4634-9522-ec4fa95deb99`;
- `AB_TEST_NAME=Test paywall prices. 4.99/29.99 vs 5.99/39.99`;
- `AB_TEST_START_DATE=2026-07-10`;
- A / Old Prices: paywall `d6d24875-e330-4ad9-8ee0-841d3452a911`,
  имя `New Paywall Old Prices`;
- B / New Prices: paywall `d6765d7f-eb06-42db-8d0d-ee21e2b41fe8`,
  имя `New Paywall New Prices`.

Для сбора используется только `ADAPTY_API_KEY_APP1`. Любое отклонение test ID,
даты, имени теста, приложения, label, paywall ID или paywall name завершает A/B
путь до создания API-клиента и до форматирования сообщения.

Каждый запрос метрик фильтруется по датам, `paywall_id` и
`placement_audience_version_id` (ID эксперимента). В сообщении Telegram
`Unique paywall views` означает уникальные просмотры paywall, а
`CR unique view→purchase` — конверсию уникальный просмотр → покупка. В нём
остаются только согласованные метрики вариантов и строка лидера; при любой
неполной или некорректной выборке сообщение не форматируется и не отправляется.

По умолчанию `AB_TEST_REPORT_ENABLED=false`. Оставляйте persisted-флаг false в
`.env` и Railway, пока деплой не проверен и не принята live parity. Поэтому для
безопасной локальной проверки нужен разовый ephemeral override; он собирает
ровно один отчёт, печатает его и никогда не вызывает Telegram или планировщик:

```bash
AB_TEST_REPORT_ENABLED=true python main.py --preview-ab-report
```

В Railway тот же preview запускается без изменения persisted Railway variable:

```bash
railway run env AB_TEST_REPORT_ENABLED=true python main.py --preview-ab-report
```

Обе команды ничего не отправляют в Telegram. При persisted `false` команда
`python main.py --preview-ab-report` без override завершается с кодом 1, не
печатает отчёт и не выполняет отправку. `--preview-ab-report` имеет приоритет
даже вместе с `--send-ab-report`.
После принятия preview и явного включения `AB_TEST_REPORT_ENABLED=true` одна
ручная отправка выполняется командой:

```bash
python main.py --send-ab-report
```

Она отправляет один готовый A/B-отчёт либо завершается ошибкой без частичной
отправки. В ежедневном режиме A/B-отчёт доставляется отдельным сообщением после
основной ежедневной сводки, только когда enable-флаг включён.

## Ручной сбор данных (кнопка в боте)

Пока работает планировщик, бот слушает чат. В том же чате, куда приходит ежедневный отчёт:

- **Команды:** `/start` — приветствие и кнопка; `/collect` или `/data` — сразу собрать актуальные данные с Adapty и отправить отчёт.
- **Кнопка:** при `/start` появляется inline-кнопка **📊 Collect Data**. Нажатие запускает сбор данных с Adapty и отправку отчёта в чат.

Ответы бота приходят только в чат с `TELEGRAM_CHAT_ID` (другие пользователи не могут запускать сбор).

### Управление из лички (без команд в группе)

Если задать в `.env` переменную **`TELEGRAM_ADMIN_ID`** (ваш Telegram user ID), бот будет принимать команды **только в личном чате** с вами. Отчёты по-прежнему уходят в группу (и в топик, если задан `TELEGRAM_TOPIC_ID`), но в группе никто не видит ваших команд и кнопок. Как получить свой user ID: напишите боту в личку, затем откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` — в `message.from.id` будет ваш id.

## Деплой на Railway

1. Создайте проект на [Railway](https://railway.app) и подключите этот репозиторий (GitHub).

2. В настройках сервиса задайте **переменные окружения** (Variables) — те же, что в `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `ADAPTY_API_KEY_APP1`, `ADAPTY_API_KEY_APP1_SHA256`, `ADAPTY_APP_NAME_1`
   - `ADAPTY_API_KEY_APP2`, `ADAPTY_API_KEY_APP2_SHA256`, `ADAPTY_APP_NAME_2`
   - `ADAPTY_API_KEY_APP3`, `ADAPTY_API_KEY_APP3_SHA256`, `ADAPTY_APP_NAME_3`
   - При необходимости: `REPORT_TIME`, `ADAPTY_API_BASE_URL`, `ADAPTY_ANALYTICS_PATH`
   - Для Apple Ads-only отчёта при его использовании: `ADAPTY_DASHBOARD_TOKEN`,
     `ADAPTY_DASHBOARD_COMPANY_ID`, `ADAPTY_DASHBOARD_APP_ID`

3. **Procfile** уже настроен: `worker: python main.py`. Railway запустит процесс как worker (без HTTP). Отчёт будет уходить раз в сутки в заданное время.

4. Деплой: при каждом push в ветку по умолчанию Railway соберёт образ и перезапустит worker.

### Health check (опционально)

Сервис не поднимает HTTP-сервер. Проверка конфига локально: `python main.py --health`. На Railway можно не настраивать health check или использовать встроенные проверки процесса.

### Состав приложений production-отчёта

Production использует неизменяемый контракт из трёх последовательных слотов,
и все они всегда видны в отчёте:

- `APP1` — `Unfollowers: Follow & Unfollow`;
- `APP2` — `Granny Photos`;
- `APP3` — `Otty: Couples&Relationships`.

`APP4+` и `ADAPTY_APP_VISIBLE_N` не участвуют в расчётах и отмечаются как
ошибка конфигурации. Неверное точное имя, отсутствующий Secret API key или
несовпадение его SHA-256 fingerprint блокирует запрос этого слота и превращает
его метрики в `N/A`. Fingerprint привязывает валидный ключ к правильному слоту,
но ни ключ, ни fingerprint не выводятся в отчёт или audit log. Поэтому каждый
доллар в `Total` всегда воспроизводится из трёх строк над ним.

## Определения метрик и сверка с Adapty

Сравнивайте Telegram и Dashboard только на одном снимке и с одинаковыми
фильтрами: timezone `Europe/Minsk` (`GMT+3`), тот же диапазон дат, три приложения
выше и настройка installs `Count installs as new device_ids`.

- **MRR** и **ARR** берутся из gross-серии `data.revenue`. Значение — последняя
  дневная точка на дату отчёта, дельта — разность последних двух дневных точек.
  Значение и дельта публикуются только вместе, когда ответ содержит точные точки
  и за предыдущую дату, и за дату отчёта.
  ARR приходит из Adapty, но принимается только если согласуется с `MRR × 12`
  с допуском `$0.05`; несогласованный ARR отдельно становится `N/A`.
- **Revenue** — `data.revenue.value` с первого дня месяца по дату отчёта;
  значение в скобках — последняя дневная точка того же ответа.
- **Installs** — `data.common.value` за месяц; значение в скобках — последняя
  дневная точка того же ответа.
- **Install→Paid** — процент Adapty за месяц. Итоговая конверсия считается как
  `sum(value_to) / sum(value_from) × 100` по трём приложениям, а не как среднее
  или средневзвешенное округлённых процентов строк. В каждой строке рядом с
  процентом показываются исходные `paid/installs`, чтобы расчёт можно было
  проверить вручную.

Денежные итоги складываются из показанных значений, предварительно округлённых
до цента по правилу `ROUND_HALF_UP`. Поэтому `Total` всегда в точности равен
сумме трёх видимых строк без скрытого расхождения из-за дробных центов.

Если у видимого приложения отсутствует значение или raw counts конверсии,
соответствующий итог показывает `N/A`, а не неполную сумму. Числовой ноль
остаётся валидным значением.

Перед форматированием каждое поле проходит независимую проверку: число должно
быть конечным; MRR и ARR — неотрицательными; Revenue может быть отрицательным
из-за refund/reversal в gross-серии; counts — целыми; дневные Installs не могут
превышать MTD; conversion должен
совпадать с `value_to / value_from` с допуском `0.01` процентного пункта.
Ошибка изолирует только зависимое поле или семейство и его Total — остальные
проверенные значения продолжают отображаться.

Внизу каждого сообщения есть один из двух статусов:

- `✅ Проверка данных: пройдена` — все показанные числа и Totals прошли проверки;
- `⚠️ Проверка данных: обнаружено N проблем…` — недостоверные поля уже заменены
  на `N/A`, а безопасные детали отправлены администратору. `N` считает
  карантинные семейства MRR/ARR/Revenue/Installs/Conversion по приложениям и
  отдельные ошибки конфигурации, а не количество технических полей.

Scheduled delivery, `--test-send` и ручная кнопка используют одну и ту же
политику. Частичный основной отчёт всё равно отправляется, A/B и Apple Ads
остаются независимыми. В журнал пишутся структурированные статусы каждого поля
и Total без значений метрик, API keys, authorization headers и Telegram token.
Даже debug-команды выводят только HTTP status, тип payload и имена ключей —
сырые response bodies никогда не печатаются.

Adapty может позднее дозаполнять установки и конверсии пользователей. Поэтому
старое Telegram-сообщение является снимком на момент отправки, а сегодняшний
Dashboard может показывать другое значение для той же исторической даты.
Расхождение считается объяснённым backfill только когда текущие Export API и
Dashboard совпадают между собой на одном снимке.

Таким образом, числовой отчёт — проверенный timestamped snapshot, а не
неизменяемый исторический ledger: поздний backfill может изменить последующую
сверку старой даты, но не происхождение уже отправленных цифр.

## Формат отчёта

- Заголовок: 📊 Отчёт на ДД.ММ.ГГГГ
- По каждому приложению: жирное название, MRR, ARR, Revenue, Installs и
  Install→Paid с исходными `paid/installs`.
- В `Total`: MRR, ARR, Revenue, дневные Downloads и raw-count Install→Paid по
  ровно тем же трём приложениям; неполные суммы никогда не показываются числом.
- Последняя строка — явный результат проверки целостности данных.
- Сообщения отправляются с Telegram parse mode `HTML`; A/B-заголовки используют `<b>…</b>`.

## Adapty API

Используется официальный [Export Analytics API](https://adapty.io/docs/export-analytics-api):
- **Retrieve analytics data** — MRR и Installs
- URL: `https://api-admin.adapty.io/api/v1/client-api/metrics/analytics/`

При необходимости переопределите в env:
- `ADAPTY_API_BASE_URL` — по умолчанию `https://api-admin.adapty.io`
- `ADAPTY_ANALYTICS_PATH` — по умолчанию `api/v1/client-api/metrics/analytics/`

Таймзона в проекте зафиксирована как `Europe/Minsk` для планировщика и запросов к Adapty (`Adapty-Tz`).
