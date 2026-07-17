# Архитектура решения — Adapty Daily Report Bot

## Потоки выполнения

```
main.py
  ├─ --preview-ab-report → build_ab_test_report() → stdout → exit
  ├─ --send-ab-report    → send_ab_report_once() → Telegram → exit
  └─ обычный режим       → APScheduler → daily delivery
                                      ├─ ежедневная сводка
                                      ├─ A/B-отчёт (если включён)
                                      └─ Apple Ads-отчёт (если включён)
```

`--preview-ab-report` разбирается раньше любого debug-, send- или scheduler-
пути. Он строит один полный A/B-отчёт, печатает его ровно один раз и завершает
процесс. Этот путь не импортирует отправку Telegram и не запускает планировщик;
он сохраняет это свойство даже в комбинации с `--send-ab-report`. Пустой либо
отключённый отчёт завершает процесс с кодом 1 без печати и без отправки.

Поскольку persisted `AB_TEST_REPORT_ENABLED` в `.env` и Railway остаётся
`false` до принятия parity, операционный preview использует только разовый
process-level override:

```bash
AB_TEST_REPORT_ENABLED=true python main.py --preview-ab-report
railway run env AB_TEST_REPORT_ENABLED=true python main.py --preview-ab-report
```

Вторая команда не меняет persisted Railway variable. Ни одна команда preview не
отправляет Telegram; preview без override при persisted `false` корректно
завершается с кодом 1.

## A/B: изолированный Secret API путь

`ab_test_report.py` использует `ADAPTY_API_KEY_APP1` и создаёт
`AdaptyAbExportClient`. Production A/B-путь pinned к app index `1`, приложению
`Unfollowers: Follow & Unfollow`, эксперименту
`1db6e378-026f-4634-9522-ec4fa95deb99` со стартом `2026-07-10` и mapping:

- A: `d6d24875-e330-4ad9-8ee0-841d3452a911` — `New Paywall Old Prices`;
- B: `d6765d7f-eb06-42db-8d0d-ee21e2b41fe8` — `New Paywall New Prices`.

Любое отклонение identity-конфигурации отклоняется до создания клиента и
форматирования. Клиент выполняет только
Adapty Analytics Export API запросы с `Authorization: Api-Key <Secret API Key>`.
Каждый запрос ограничен датами теста, `paywall_id` и
`placement_audience_version_id` (experiment ID).

Конфигурация A/B требует точного совпадения pinned identity-полей. Вариант A —
Old Prices, вариант B — New Prices. После
успешного получения и строгой проверки обоих вариантов формируется единственное
HTML-сообщение Telegram с разрешёнными метриками: revenue, ARPAS, `Unique
paywall views`, purchases, `CR unique view→purchase` и строкой лидера. Views и
CR всегда имеют семантику уникального просмотра.

Путь fail-closed атомарен: любая ошибка конфигурации, API или валидации отменяет
всё форматирование и доставку — частичный A/B-отчёт невозможен. A/B-код не
создаёт Dashboard/WebView-сессию и не читает Dashboard credentials.

В ежедневной доставке планировщик сначала формирует основную сводку, затем при
`AB_TEST_REPORT_ENABLED=true` доставляет отдельный A/B-отчёт. В Railway флаг
остается `false`, пока проверка preview, здоровый деплой и live parity не
приняты.

## Apple Ads: отдельная Dashboard-зона

Apple Ads Manager может использовать `ADAPTY_DASHBOARD_TOKEN`,
`ADAPTY_DASHBOARD_COMPANY_ID` и `ADAPTY_DASHBOARD_APP_ID` для рекламного
отчёта. Эти переменные Apple Ads-only: они сохранены для Apple Ads и не являются
входными данными или fallback для A/B Secret API.

## Безопасность логов

`safe_logging.configure_secret_redaction()` устанавливает фильтр на текущие
root handlers до сетевых запросов. Он скрывает Telegram, Dashboard и ASA
credentials, а также все непустые env-значения с именем
`ADAPTY_API_KEY_APP` и числовым суффиксом. Аргументы логов, traceback и URL
Telegram обрабатываются до форматирования. Секреты не выводятся в исходный код,
документацию, preview, отчёты или логи.
