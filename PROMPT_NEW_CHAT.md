Проект: «Система сигналов» — Bybit USDT perpetuals, шорт-сигналы после пампа.
Репозиторий уже на GitHub (bybit-short-signals), ветка main. Локальная папка может называться «Система сигналов».

Старт (обязательно, до любых правок):
1. Прочитай полностью TZ.md и PROGRESS.md в корне репозитория (включая раздел «РАСШИРЕНИЯ UI И ДОСОК» и журнал 2026-10-06).
2. Прочитай .cursor/rules/deploy-workflow.mdc.
3. Изучи код по цепочке: config.py → collector/ → signal_engine/ (engine.py, pump_scan.py, x2_retrace.py, watch_store.py, pump_history.py, swing_highs.py) → ws_server/ (app.py, hub.py, cache.py, static/).
4. Пойми текущее состояние: вкладки «Сигналы», «Памп-скан», «2× откат», «Тест стратегии» (виртуальные шорты, `signal_engine/paper/`); липкие board_watches; debounce колонок; dismiss API.

Принцип работы в этом проекте («чистый лист» = новый чат, не переписывать архитектуру):
- Продолжаем с текущего main, минимальные дифы, существующие конвенции.
- После любой задачи с изменениями в репозитории (код, конфиг, тесты, TZ/PROGRESS): сам делаешь commit → git push origin main → deploy на VPS:
  ssh -o BatchMode=yes root@129.101.127.78 "bash /opt/signals/scripts/deploy.sh"
- Каталог на сервере: /opt/signals, venv: .venv, UI: http://129.101.127.78:8787
- Не коммить .env и секреты. Не спрашивай меня «закоммитить?» / «задеплоить?» — делай сам.
- В чат пиши только краткий отчёт: что сделано, hash коммита, Deploy OK или ошибка.
- Тесты по возможности на VPS: cd /opt/signals && .venv/bin/python -m unittest …

Контекст последних решений по «2× откат» (не ломать без запроса):
- Вход: turnover ≥ 300k USDT, рост 7d ≥ 0%, два пика 4H/1H, всплеск объёма на ноге роста (×4), min mult ~1.72× за 21d.
- Выход: у дна пампа / низкий current mult; не снимать при hist is None.
- Эталоны для проверки: NIL, HUMA, MINA, SAND, GRASS — scripts/verify_x2_examples.py, audit_x2_turnover.py.

Моя следующая задача: **ничего не делать по коду и не предлагать рефакторинг — только онбординг (чтение TZ/PROGRESS и обзор кода). После краткого отчёта «готов, жду команду» — ждать мою следующую команду в чате.**
