#!/usr/bin/env python3
import json
from signal_engine.live.em6_bybit.broker import Em6BybitBroker

b = Em6BybitBroker()
r = b._client().get_wallet_balance(accountType="UNIFIED")
acct = (r.get("result") or {}).get("list") or []
print(json.dumps(acct[0] if acct else {}, indent=2)[:4000])
