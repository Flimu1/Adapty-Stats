#!/usr/bin/env python3
"""
Скрипт для проверки ответов Adapty API. Не зависит от config.py.
Запуск из корня проекта: python3 scripts/test_adapty_api.py
Требует: .env с ADAPTY_API_KEY_APP1, опционально ADAPTY_BASE_URL.
"""
import json
import os
import sys
from datetime import datetime, timedelta

# Загружаем .env из корня проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

import requests

def main():
    api_key = os.getenv("ADAPTY_API_KEY_APP1", "").strip()
    base_url = (os.getenv("ADAPTY_BASE_URL") or os.getenv("ADAPTY_API_BASE_URL") or "https://api-admin.adapty.io").rstrip("/")
    path = (os.getenv("ADAPTY_ANALYTICS_PATH") or "api/v1/client-api/metrics/analytics/").strip().lstrip("/")
    tz = "Europe/Minsk"

    if not api_key:
        print("ERROR: ADAPTY_API_KEY_APP1 not set in .env")
        sys.exit(1)

    url = f"{base_url}/{path}"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": tz,
    }

    now = datetime.utcnow()
    now_24h = now - timedelta(hours=24)
    now_48h = now - timedelta(hours=48)
    epoch = datetime(2020, 1, 1)

    # Тест 1: период последние 24ч (как раньше работало)
    range_24h = (now_24h, now)
    # Тест 2: период "всё время" (как сейчас в проде)
    range_all = (epoch, now)
    # Тест 3: период "всё время до 24ч назад"
    range_all_24h_ago = (epoch, now_24h)

    # Сначала проверяем long range с period_unit=month (API запрещает day для >1 года)
    print(f"\n{'='*60}")
    print("Period: All-time with period_unit=month (epoch -> now)")
    date_str = [epoch.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]
    for chart_id in ("mrr", "installs"):
        body = {
            "chart_id": chart_id,
            "filters": {"date": date_str},
            "period_unit": "month",
            "format": "json",
        }
        try:
            r = requests.post(url, json=body, headers=headers, timeout=30)
            print(f"\n--- chart_id={chart_id} period_unit=month ---")
            print(f"Status: {r.status_code}")
            if r.ok and r.text:
                data = r.json()
                if "data" in data and isinstance(data["data"], dict):
                    d = data["data"]
                    print("data keys:", list(d.keys()))
                    for k, v in list(d.items())[:2]:
                        if isinstance(v, dict):
                            print(f"  {k}.value = {v.get('value')}")
                            if "data" in v and isinstance(v["data"], list):
                                print(f"  {k}.data length = {len(v['data'])}")
                                if v["data"]:
                                    print(f"  {k}.data[-1] = {v['data'][-1]}")
                else:
                    print("Response:", r.text[:400])
        except Exception as e:
            print(f"Error: {e}")

    # Окно "предыдущие 24ч" — что возвращает API для MRR (для дельты)
    print(f"\n{'='*60}")
    print("Period: Previous 24h (48h ago -> 24h ago) for MRR")
    date_str = [now_48h.strftime("%Y-%m-%d"), now_24h.strftime("%Y-%m-%d")]
    r = requests.post(url, json={"chart_id": "mrr", "filters": {"date": date_str}, "period_unit": "day", "format": "json"}, headers=headers, timeout=30)
    print("Status:", r.status_code)
    if r.ok and r.text:
        d = r.json().get("data") or {}
        gr = d.get("gross_revenue") or {}
        print("gross_revenue.value =", gr.get("value"))
        arr = gr.get("data") or []
        if arr and isinstance(arr[0], dict):
            vals = arr[0].get("values") or []
            if vals:
                print("data[0].values[-1].y =", vals[-1].get("y"))

    for name, (date_from, date_to) in [
        ("Last 24h", range_24h),
        ("All-time (epoch -> now) period_unit=day", range_all),
        ("All-time (epoch -> now-24h)", range_all_24h_ago),
    ]:
        date_str = [date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")]
        print(f"\n{'='*60}")
        print(f"Period: {name}")
        print(f"Date range: {date_str}")
        for chart_id in ("mrr", "installs"):
            body = {
                "chart_id": chart_id,
                "filters": {"date": date_str},
                "period_unit": "day",
                "format": "json",
            }
            try:
                r = requests.post(url, json=body, headers=headers, timeout=30)
                print(f"\n--- chart_id={chart_id} ---")
                print(f"Status: {r.status_code}")
                if not r.text:
                    print("Body: (empty)")
                    continue
                data = r.json()
                # Кратко: ключи и значение data
                if "data" in data and isinstance(data["data"], dict):
                    d = data["data"]
                    print("data keys:", list(d.keys()))
                    for k, v in d.items():
                        if isinstance(v, dict):
                            if "value" in v:
                                print(f"  {k}.value = {v['value']}")
                            if "data" in v and isinstance(v["data"], list):
                                print(f"  {k}.data length = {len(v['data'])}")
                                if v["data"]:
                                    print(f"  {k}.data[0] = {v['data'][0]}")
                                    if len(v["data"]) > 1:
                                        print(f"  {k}.data[-1] = {v['data'][-1]}")
                        else:
                            print(f"  {k} = {type(v).__name__}")
                else:
                    print("Response (first 500 chars):", json.dumps(data)[:500])
            except Exception as e:
                print(f"Error: {e}")

    print("\n" + "="*60)
    print("Done.")

if __name__ == "__main__":
    main()
