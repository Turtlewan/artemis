# ADR-043 — Telegram inbound routing + bless-based invoke consent

- **Status:** **Proposed** — owner + planning, 2026-07-03 (design settled in discussion; build NOT greenlit).
- **Date:** 2026-07-03
- **Deciders:** owner + planning
- **Refines:** ADR-035 (reach-out router / shared ingress), ADR-039 (capability invoke/reuse — reuses its confirm-before-run + dual-LLM quarantine), ADR-009/037 (untrusted-output quarantine). Builds on the live `TelegramTransport` (send + allowlisted long-poll receive) and the transport-neutral `IntentRouter`.
- **Design basis:** live audit — the runner `src/artemis/app.py` (`App.run`) drives only the scheduler; `transport.receive()` has **no consumer** today. `IntentRouter.classify` is already transport-neutral. `invoke.py` holds `build_invoke_proposal` → `confirm_invoke` (secret resolve → `FetchSandbox.run` → `_quarantine_output`). `Skill` carries `name` + integer `version` + `secrets` + `egress_domains` + `inputs`.

## Context

Telegram inbound is received + owner-allowlisted, but nothing routes it — you can text the bot and it
is dropped past the allowlist check. The owner wants to **drive Artemis from a text**: ask questions,
run web lookups, and **pull info from existing capabilities**. Authoring new capabilities stays on the
desktop. The blocker is consent: the desktop gates an invoke with a rich card (capability + egress +
secrets); a phone has no card, so credentialed capability runs need a chat-native consent model.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Inbound scope = chat / web-Q / invoke; NOT build** | The ingress loop routes inbound Telegram through `IntentRouter` to `plain_ask` (1), `web_q` (2), and existing-capability `invoke` (3). A `build` classification is refused over Telegram with a "build capabilities on the desktop" reply — authoring code from a weak-consent surface is out. |
| 2 | **Two-tier consent** | Every capability already passed a desktop consent card at build/promote (allowed to *exist*). **Bless** is a second, per-capability standing grant: "run this from Telegram without a per-run confirm." |
| 3 | **Invoke gate over Telegram** | Blessed → run immediately. Un-blessed → a confirm **message** showing capability + one-line description + **egress domains** + **secret(s) used** + inputs, with inline buttons **[Run once] / [Always allow] / [Cancel]**. Requires inline-keyboard send + `callback_query` receive — neither exists in `TelegramTransport` today (text-only). |
| 4 | **Bless-from-chat** | **[Always allow]** = bless (standing grant) + run this time. The consent surface (egress/secrets in the message body) is what keeps a phone-tap bless *informed*. Bless is also settable on the desktop (parity). |
| 5 | **Revoke, both surfaces** | Desktop shows a blessed-capabilities list to toggle off; a Telegram **`/blessed`** command lists them and un-blesses on tap. Both ship. |
| 6 | **Bless is version-scoped** | A bless keys to `(capability_name, version)`. A rebuild/update bumps `Skill.version`, so the old bless no longer matches → auto-reset; the owner re-blesses after seeing the new version's card once. New code ⇒ re-consent. |
| 7 | **Reuse the existing invoke + quarantine path** | The gate calls `build_invoke_proposal` / `confirm_invoke` (it does NOT reimplement secret resolve or execution); output flows through the existing dual-LLM quarantine (ADR-009/037) before the reply is sent back out the transport. |
| 8 | **Shared on-disk bless store (two processes)** | The brain (`artemis serve`, desktop bless routes) and the runner (`artemis run`, the ingress gate) are separate processes. Bless state lives in a shared JSON store under `ARTEMIS_DATA_DIR` (mirrors `layout.json`) so a bless on either surface is visible to both. Never silent-auto: an unblessed invoke always confirms (owner's locked stance, `agency-proactivity-scope-locked`). |

## Consequences

**Three file-disjoint, dependency-ordered specs (drafts — the bless gate needs a dispatched
apex-security review before any is marked ready):**
- **R4a** — runner ingress loop: consume `receive()`, classify, execute `plain_ask` + `web_q`, quarantined reply. (Prereq for R4b.)
- **R4b** — bless store (version-scoped) + Telegram invoke gate + inline-button consent + `callback_query` handling + `/blessed` revoke. **Security-critical.**
- **R4c** — desktop bless/revoke: brain routes + client toggle & blessed-list UI.

**Positive:** Artemis becomes a genuine pocket assistant for questions + capability pulls; the consent
model stays explicit and version-scoped; no new execution or secret path (reuses invoke + quarantine).

**Costs / risks:** inline-keyboard + callback handling is new transport surface; bless is a real standing
authorization — its store, version-scoping, and revoke are security-load-bearing (hence the mandatory
review). Two processes sharing an on-disk bless store needs care (atomic writes, read-fresh at gate time).

## Alternatives considered
- **Desktop-only bless** (stronger consent) — owner chose bless-from-chat for convenience; mitigated by putting egress/secrets in the confirm message so the tap is informed.
- **Auto-classify read-vs-write to skip confirms** — rejected: relies on a classifier for a safety decision; the explicit bless keeps a human in the loop (owner's locked stance).
- **Persist bless across capability updates** — rejected (decision 6): would auto-trust regenerated code the owner never re-saw.
