# Phase D — Google spoke go-live runbook (Windows-host v1)

Activation procedure to take Gmail/Calendar from fake-tested to **live**, then exercise the email-rules
reactions harness (observe → live). This is an **owner-run ops exercise**, not an automated build.
Most code is already built (M8-a auth foundation, Gmail connector, CAL-*); going live = OAuth setup +
running the CLIs. **Re-walk these steps live at exercise time** — verify each against the actual CLIs,
which may have been refined since (memory `dev-email-rules-oauth-at-exercise`).

## Prerequisites (must be built first)
- **m2-win-b** — Windows Hello unlock (the CLIs unlock owner-private scope via a Hello gesture). ✅ built.
- **win-owner-cli-keyprovider** — wires `artemis-google-auth` / `artemis-dev-email-rules` to
  `WindowsKeyProvider` (without it they `RuntimeError` on Windows). ⏳ build before this runbook.
- **win-brain-runtime (⑤a)** — only needed if exercising end-to-end against a running brain.
- A Google account — **use a dedicated test account**, not your primary, for the first run.

## Step 1 — Google Cloud project + APIs
1. https://console.cloud.google.com → create (or pick) a project.
2. **APIs & Services → Enable APIs:** enable **Gmail API** and **Google Calendar API**.

## Step 2 — OAuth consent screen
1. **APIs & Services → OAuth consent screen** → User type **External** → fill the minimal app info.
2. **Test users → add your owner/test email** (External + Testing mode = only test users can consent;
   no Google verification needed).
3. **Scopes:** the consent grants the **least-privilege union the connectors registered** (run
   `python -c "from artemis.integrations.google.scopes import required_scopes; print(sorted(required_scopes()))"`
   to see the exact set — expected read-only Gmail + Calendar). Do not add broader scopes.

## Step 3 — OAuth client credentials
1. **APIs & Services → Credentials → Create credentials → OAuth client ID** → Application type
   **Desktop app**. (Desktop = the loopback/PKCE flow `run_installed_app_consent` uses.)
2. Copy the **Client ID** and **Client secret**.

## Step 4 — Provide the credentials to Artemis (env)
`load_oauth_config()` reads two env vars (NOT a JSON file):
```
GOOGLE_OAUTH_CLIENT_ID=<client id>
GOOGLE_OAUTH_CLIENT_SECRET=<client secret>
```
Set them in the slot `.env` (or the shell). **Secret hygiene:** add both to the Keychain→`.env`
inject map (M0-f) for prod stability; never commit them.

## Step 5 — Unlock + log in
1. `artemis-google-auth login` → the CLI unlocks owner-private scope (a **Windows Hello prompt
   appears** — provide your gesture), then opens the browser loopback consent. Approve the requested
   read-only scopes. The refresh token is stored in the **owner-private SQLCipher token store**
   (encrypted at rest, keyed by `WindowsKeyProvider`).
2. `artemis-google-auth status` → confirm the token is present + the scopes match.
   (`artemis-google-auth revoke` to undo; also revoke at https://myaccount.google.com/permissions.)

## Step 6 — Pull the email reader model
The reactions email classifier uses a **toolless** local reader (it reads untrusted email; it must
not be a tool-caller):
```
ollama pull qwen3:4b        # the responder/reader; confirm the toolless model id the harness expects
```

## Step 7 — Exercise the email-rules harness (observe)
```
artemis-dev-email-rules --once
```
Runs Lane-B observe: polls the test inbox → launders → classifies (R5d) → emits → dispatches in
**observe** (logs `WOULD <action>` + the structured extracts, writes nothing durable). Read the log,
then tune the R5d classifier + R6c rules against what real email produced.

## Step 8 — Go live (owner flip, later)
When confident, set `reactions_mode = live` (RuntimeConfig / `policy.json`) so reactions dispatch for
real. This is a deliberate manual flip — reactions ship DORMANT (`observe`) until you make it.

## Security notes
- Least-privilege read-only scopes; test account first; tokens encrypted at rest (owner-private
  SQLCipher); email stays local (cloud = general skills only, per owner rules).
- The Hello gesture gates every owner-private unlock the CLIs perform — a locked vault fails closed.
