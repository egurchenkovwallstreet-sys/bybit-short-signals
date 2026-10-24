---
name: bybit-pump-short
description: >-
  Analyzes Bybit USDT-perp pump-fade shorts and paper variants (t20, p10, mln,
  333, em6, pyl, vps). Use when reviewing closed paper trades, proposing entry
  filters or exits, comparing variants, changing paper/detect/strategy code, or
  discussing the signal boards.
---

# Bybit pump short

Лаборатория шорта после пампа на Bybit USDT-перпах. Система **не торгует за человека** (кроме опционального EM6 demo). Paper-варианты крутятся параллельно, у каждого свой счёт $1000.

Правила входа/выхода уже в коде. Этот скилл учит агента **разбирать сделки и предлагать одно изменение**, а не придумывать новую стратегию с RSI.

## Источник правды

Читать в таком порядке. Не пересказывать правила своими словами, если они уже записаны.

1. `.cursor/rules/paper-entry-filters.mdc` — шлюз, t20/p10/mln, копии, выходы, что нельзя добавлять.
2. `.cursor/rules/pyl-confirm-clock.mdc` — часы входа/выхода pyl / vps5 / vps15.
3. `TZ.md` + `PROGRESS.md` — архитектура и текущее состояние.
4. Код: `signal_engine/paper/detect.py` (`paper_entry_blocks`, `evaluate`), `position.py`, `strategy.py`, пороги `PAPER_*` в `config.py`.

Семейства вариантов — [families.md](families.md).

## Как работать

Когда просят улучшить вход, выход или разобрать минусы:

1. **Одна гипотеза.** Что ломается: вход, выход или монета. Не мешать три сразу.
2. **Одно изменение.** Новый фильтр *или* сдвиг порога *или* другая ступень стопа. Не «пакет из пяти пунктов».
3. **Та же выборка + позже.** Считать KEEP / DROP / PnL на закрытых сделках, затем проверить на более позднем окне. Метод — скилл `walk-forward-validation`.
4. **Не ломать топ.** Если правило режет плюсовые t20/p10 сильнее, чем спасает ликвидации — отказ. В `paper-entry-filters.mdc` уже список запретов (откат ≤10%, обязательные sells_dominate/buys_faded, объём ×10, резка grade C, ослабление пола пампа).
5. **Код не менять**, пока пользователь явно не скажет внедрить. Сначала цифры в чат.

Шаблон отчёта — скилл `strategy-framework`. Риск и просадка счёта варианта — `risk-management`.

## Семьи (не смешивать)

| Семья | Край | Не предлагать |
|---|---|---|
| Памп-шорт `t20` `p10` `mln` + копии | Памп затих → шорт. Шлюз + 5 из 9 / plus | ICT, Фибо, «купи RSI 30», живые ордера |
| Pivot `pyl` `vps15` `vac` | LH/HL и часы свечи | Шлюз пампа, переворот одной операцией |
| `333` / `33315` | Pivot + EMA60, выход только стоп | Закрытие противоп. pivot |
| `em4`–`em10` | Отрыв от EMA60, без пампа | Шлюз 12%, 5 из 9 |

## Данные и скрипты

- База: `data/paper_strategy.db` (на VPS; локально может не быть). Сделки: `paper_trades`, вход в `entry_json`.
- Разбор входа: `scripts/eval_entry_filters.py`, `scripts/analyze_paper_closed.py`, `scripts/paper_closed_full_report.py`.
- Сетка выходов: `scripts/simulate_*trail*.py`, `scripts/simulate_333_*.py`, `scripts/simulate_keep_exit_grid.py`.
- API: `GET /api/paper/snapshot`, `/api/paper/trades?status=closed&variant=t20`.

Одноразовые `scripts/_*.py` не коммитить, если пользователь не просил.

## Жёсткие запреты

- Не слать ордера и не подключать чужие брокерские скиллы (OKX, Alpaca, SimpleFX).
- Не ослаблять согласованный шлюз без команды.
- Не внедрять фильтр «потому что так в учебнике». Нужна цифра на ваших закрытых.
- Не переписывать архитектуру collector → Redis → engine → ws_server.
- После минуса по стопу у `333` / `33315` кулдаун 45 мин уже есть — не дублировать в другом месте без нужды.

## Известный пробел

Шлюз на выборке ~81 сделки: KEEP 24, WR 42%, лучше факта, но ликвидации STRK / WUSDT / KAIA всё ещё проходят. Не закрывать этот пробел правилом, которое убивает плюсовые сделки.
