# Telegram go-live runbook (step 2 — manual, ~30 min)

The `TelegramTransport` is built + hermetically tested but has never run against the real Bot API.
This is the one-time manual bring-up. You need your phone.

## 1. Mint a bot token (BotFather)
1. In Telegram, message **@BotFather** → `/newbot`.
2. Give it a name + a username ending in `bot` (e.g. `artemis_owner_bot`).
3. BotFather replies with a **token** like `123456:ABC-DEF...`. Copy it.

## 2. Capture your chat id
1. Message your new bot anything (e.g. `/start`) from your phone.
2. Fetch the chat id (paste the token in):
   ```
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   In the JSON, find `message.chat.id` (an integer, e.g. `987654321`). That's your owner chat id.

## 3. Set env (persist for the brain)
Since Artemis reads these from the environment (`telegram_from_env`):
```powershell
setx TELEGRAM_BOT_TOKEN "123456:ABC-DEF..."
setx TELEGRAM_CHAT_IDS "987654321"          # allowlist (comma-separated if more than one)
setx TELEGRAM_OWNER_CHAT_ID "987654321"     # where proactive messages go
```
Open a **fresh** terminal afterwards (setx doesn't affect the current one).
> These env vars are the stopgap until the credential store (step 3) + secret-capture (step 4) land;
> once those ship, the token migrates into the OS keychain and these can be removed.

## 4. Prove it end-to-end
1. Start Artemis: `uv run artemis` — it env-selects Telegram (else console).
2. Schedule a near-future proactive job so the phone buzzes:
   ```
   uv run artemis add --in 2min "Telegram go-live test — if you see this, it works."
   uv run artemis list        # confirm it's queued
   ```
   (Adjust to the actual `artemis add` flag surface — `uv run artemis add --help`.)
3. Within ~2 min your phone should receive the message from the bot. ✅
4. Reply to the bot from your phone; confirm the allowlisted long-poll receive picks it up in the
   `uv run artemis` logs (inbound is allowlisted to `TELEGRAM_CHAT_IDS`).

## Done when
Phone buzzes on the scheduled job AND an inbound reply shows in the brain logs. Record the observed
result. After this, R4 (transport-ingress) will route those inbound messages through the R3 intent
router so you can *ask/build by texting the bot*.
