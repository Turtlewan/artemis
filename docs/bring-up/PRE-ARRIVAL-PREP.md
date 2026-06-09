# Pre-Arrival Prep — do these NOW, before the Mac Mini

_Purpose: everything the owner can do **off-Mini, in advance**, so arrival day collapses to
transfer → bootstrap → a short gated pass. Default project state is **no hardware** (Mini not bought;
purchase pending the WWDC-2026 decision). Work top-down; the **⏳ lead-time** items are the ones worth
starting first because they depend on external approval/propagation or large downloads._

> Companion docs (owed, not yet written): `BRING-UP-RUNBOOK.md` (the ordered on-arrival sequence) and
> `SECRETS-INVENTORY.md` (every secret → where it lands). This checklist feeds both.

---

## A. Accounts, API keys & cloud setup (create now)

Each item: **what · why · where it lands on the Mini**. Collect the resulting secrets somewhere safe
(a password manager) now; they get loaded into the Mini's **macOS Keychain** (or a slot `.env`) at
bring-up — never committed.

### A1. ⏳ Google Cloud OAuth app — *(the biggest lead-time item; powers M8-a → Calendar + Gmail)*
1. Create a **Google Cloud project** (console.cloud.google.com) — e.g. "Artemis".
2. **Enable APIs**: Google Calendar API, Gmail API (APIs & Services → Library).
3. **OAuth consent screen**: User type **External**; fill app name, your support email, developer email.
4. **Publishing status → "In production"** (i.e. *published*), but **do NOT submit for verification**.
   This is deliberate (ADR-011 / M8-a): a *published* app's refresh token does **not** hit the 7-day
   expiry that *Testing*-mode apps suffer; single-owner accepts the "unverified app" warning screen +
   the 100-user cap. ⚠️ **Confirm at setup:** `gmail.readonly` is a *restricted* scope — verify Google
   still lets you proceed past the unverified screen for **your own** account in production (it normally
   does for the project owner). If policy blocks it, fall back to adding yourself as a **Test user** and
   we revisit the 7-day-token handling. Calendar scopes are *sensitive* (not restricted) and are fine.
5. **Create credentials → OAuth client ID → Application type: Desktop app.** This issues the
   `client_id` + `client_secret` and supports the loopback (`127.0.0.1`) redirect M8-a uses.
6. **Save** the `client_id` + `client_secret` → these become `GOOGLE_OAUTH_CLIENT_ID` /
   `GOOGLE_OAUTH_CLIENT_SECRET` in the Keychain on arrival.
7. (Scopes themselves are requested incrementally by the connectors at consent time — you don't pre-pick
   them here beyond what the consent screen lists.)

### A2. ⏳ Search provider keys — *(powers DR / Deep-Research + Curiosity Loop, ADR-009)*
- **Brave Search API** (default provider) — create an account, get an API key → `BRAVE_API_KEY`.
  ⚠️ Brave ended its free tier in early 2026 — this is a **paid/metered** key now; budget a small plan.
- **Tavily** (fallback provider) — account + key → `TAVILY_API_KEY` (has a free tier).
- **Jina Reader** (optional fetch upgrade) — only if you want it; → `JINA_API_KEY` (optional).
- Re-verify each provider's data-retention terms when you sign up (Tavily/Jina changed hands recently).

### A3. Tailscale — *(the private tunnel; ADR-002 — remote access, the client `/app/*` surface)*
- Create a **Tailscale account** now (e.g. via your Google/GitHub identity). The Mini joins the tailnet
  at bring-up. Optionally pre-generate an **auth key** for headless device join. No cost for personal use.

### A4. DeepSeek API — *(the coding backend; status.md backends = coding `deepseek-v4-flash`)*
- Create a **DeepSeek account** + API key → used by the build-agent's Claude Code coding sessions on the
  Mini (`ANTHROPIC_BASE_URL` → DeepSeek). This is what *builds* the spec queue. Save the key.

### A5. Claude subscription — *(the teacher + the build-agent's planning sessions; ADR-001/003)*
- Ensure your **Claude subscription** is active and usable via Claude Code CLI — it's the quota-capped
  teacher (`claude-cli` adapter, `roles.toml`) and drives planning-mode sessions on the Mini. Already in
  use here; just confirm it'll authenticate on the Mini.

### A6. ntfy push — *(M6 heartbeat delivery; stack/M0-b)*
- Decide **self-hosted ntfy on the Mini** (default — stays local/private, no account) **vs an ntfy.sh
  topic**. If self-hosted, nothing to do now; if ntfy.sh, reserve a hard-to-guess topic name. Install the
  **ntfy app** on your phone either way to receive pushes.

---

## B. Pre-download / pre-stage (so arrival isn't gated on big downloads)

The MLX model weights are large; pulling them on first run needs time + bandwidth on the Mini. **Option:**
pre-download to an **external SSD** now and transfer alongside the repo, OR accept a first-run download
window. The model set (from `config/roles.toml` + M3/M4/M5 specs) — exact pins live in the specs:
- **LLMs:** Qwen3-4B-Instruct-2507 (responder + research reader), **Qwen3.6-27B** (sensitive reasoner —
  the large one; needs the 64GB tier per ADR-001).
- **Embeddings/rerank:** Qwen3-Embedding-0.6B, Qwen3-Reranker-0.6B.
- **Voice (M5):** Kokoro-82M (TTS), Parakeet + Whisper (STT), openWakeWord, Silero VAD, ECAPA (speaker-ID).
- **Visual docs (M3):** ColQwen2.5 Light (MPS 2.5.1).
- **Runtime:** mlx-openai-server 1.8.1; Docling (ingestion).

_(Don't over-optimize this now — it's a convenience. The runbook will list exact versions; pre-staging
just removes a wait.)_

---

## C. Hardware (the gating purchase)
- **Decision pending WWDC 2026.** Per ADR-001 refinement the lever is the **64GB RAM tier**, not the M5
  chip: if WWDC ships an M5 Pro Mini with 64GB BTO ≤ ~S$3,600 → buy that; else 64GB-on-M4-Pro. 64GB is
  what unlocks Qwen3.6-27B as the local sensitive reasoner + the GraphRAG spike.
- After purchase: create the two macOS user accounts the deployment assumes — the **owner-runtime user**
  (runs the services) and the **build-agent user** (sandboxed Claude Code; M0-e). The runbook covers the
  exact setup.

---

## D. NOT needed before arrival (don't over-prepare)
- **The iPhone client app / real phone pairing** — built later (CLIENT milestone). The core M0–M7 build
  uses a **MockProver** for unlock, so phone pairing is **not** a blocker for the initial build. You'll
  pair the real phone when the client app ships.
- **Choosing connector scopes** — the Calendar/Gmail specs declare their own least-privilege scopes; you
  approve them at consent time, not now.
- **Offsite backups, NAS, satellites, watch** — all parked to post-core build.

---

## Quick status
| Item | Lead time | Have it? |
|------|-----------|----------|
| Google Cloud OAuth app (client_id/secret) | ⏳ medium | ☐ |
| Brave API key (paid) | ⏳ short | ☐ |
| Tavily API key | ⏳ short | ☐ |
| Jina key (optional) | — | ☐ |
| Tailscale account (+ auth key) | short | ☐ |
| DeepSeek API key | short | ☐ |
| Claude subscription confirmed | — | ☐ |
| ntfy decision + phone app | short | ☐ |
| Model weights pre-staged (optional) | ⏳ long (download) | ☐ |
| Mac Mini purchased (64GB, post-WWDC) | ⏳ gating | ☐ |
