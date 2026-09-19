# Dust: Legacy Operations + Baileys

This is your original Dust codebase migrated from Selenium to Baileys.

## Preserved original operations

- `session_bot/db_ops.py` - transaction saving, cancellation, settlement and table queries.
- `session_bot/constant.py` - all market timings and aliases.
- `session_bot/reply_processor.py` - original market/HLA decision flow.
- `session_bot/dynamic_handler.py`, `dynamic_time_manager.py` and `schedule_task.py`.
- `m_res.py` - safe local `i_op` / `i_cl` helper; no import-time test write.

## Changed only

- `session_bot/web_bot/` Selenium reader/writer is removed.
- `session_bot/__init__.py` is now a Baileys-outbox adapter.
- `session_bot/config.py` reads your local `config.yaml`; it no longer contains external MongoDB credentials.
- `src/index.mjs` is the only WhatsApp transport.

## HLA placement

Copy your existing `hla_adv` folder here exactly:

```text
session_bot/hla_adv/
```

The preserved `reply_processor.py` still imports:

```python
from .hla_adv import hla
```

So no other legacy operation file needs to be copied by you.

## Required flow

```text
Incoming group message
 -> raw_messages_<date> stores full message/key first
 -> state received

"last" trigger
 -> all same-group received records, chronological order
 -> original Reply_processor + HLA + db_ops transaction save
 -> reply_pending durable outbox
 -> Baileys native quoted reply
 -> replied
```

## Delivery and recovery guarantees

- `message_id` is unique together with client/session/source JID, so duplicate
  Baileys `notify`/`append` events do not run HLA or send duplicate replies.
- Every source JID has its own lock: message order is preserved from the first
  saved message through the `last` trigger. Different groups use up to
  `max_parallel_sources` backend workers at the same time.
- Original WhatsApp timestamp is stored and is the batch order key. The full
  raw message/key is retained for the native quoted reply.
- `reply_pending` is written before send. If server/connection stops, durable
  outbox items return to `retry` with backoff; a successful quoted send marks
  only that input record as `replied`.
- Raw/outbox use durable non-daily collections so a restart after midnight does
  not abandon a previous business-date reply. Legacy transaction data remains
  in `Market/<YY-MM-DD>`.
- Baileys keeps one serial queue per JID, waits for group resolution after
  reconnect, and reconnects automatically unless WhatsApp logs the account out.

Check progress at:

```text
GET /status/vijay/vijay
```

The default `config.yaml` uses `processing.mode: on_trigger`. Change it to
`immediate` only when you want old immediate-reply behaviour.

## Setup and run

```bash
cp .env.example .env
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
npm install
npm start
```

Use `auth_info/` for one Baileys session only. First run prints a QR.
