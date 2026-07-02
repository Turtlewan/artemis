# Design note: secret-capture UI (step 4) + build-flow key gate (step 5)

Status: **design / decision-ready** (not yet specced). Builds on `cred-store` (step 3, the
keyring-backed `SecretStorePort`). Written 2026-07-02 during the autonomous R3/cred-store session.

These two are the last of the credential kernel. They have genuine UX/flow forks, so this note
surfaces the decisions rather than guessing them in a spec. Once the owner picks, each becomes a
small spec.

---

## Step 4 — secret-capture UI

**Goal:** the owner pastes an API key / token once, securely, and it lands in the OS keychain via
the cred-store — never touching logs, the webview console, or a URL.

**Proposed shape (brain half, low-fork):**
- Session-gated routes over the cred-store:
  - `POST /app/secrets` `{name, value}` → `store.set(name, value)` → 204 (echoes nothing).
  - `GET /app/secrets` → `{names: [...]}` (NAMES ONLY, never values).
  - `DELETE /app/secrets/{name}` → `store.delete`.
- Wire the cred-store onto `app.state.secrets` here (deferred from step 3 as dead-until-consumed).

**Proposed shape (client half, Tauri):**
- A Tauri command `app_secret_set(name, value)` that forwards to `POST /app/secrets` with the
  session token (token stays in Rust, out of the webview — same pattern as the capability commands).
- A small modal: `<input type="password">`, no echo, cleared on close.

**Forks for the owner:**
1. **Where does the modal live?** (a) a Settings/keys panel the owner opens deliberately, or
   (b) it only ever appears when the build gate (step 5) needs a missing key, or (c) both.
   → *Recommendation: (c) — a keys panel for management + the gate can deep-link to it.*
2. **Show existing secret names?** Listing names (not values) helps the owner see what's stored.
   → *Recommendation: yes, names only, with a delete affordance.*
3. **Value transport:** Tauri command arg (simplest, stays in-process) vs a dedicated secure field.
   → *Recommendation: Tauri command arg — it never enters the webview DOM/URL; Rust posts it.*

---

## Step 5 — build-flow key gate

**Goal:** when a capability the owner is building needs a credential, the flow prompts for it
(via step 4) BEFORE it runs, and injects the value into the WSL2 sandbox only for that capability's
run — the sandbox never sees the whole keychain.

**Context that already exists:** the forge's `PlanCard` already surfaces a capability's declared
`secrets` (status.md plangate-egress note). The WSL2 runner already passes an env into the sandbox
(`sandbox_wsl2.py`). So the gate = wire these together.

**Proposed flow:**
1. At the **propose** gate, the PlanCard lists required `secrets: [names]` (already shown) + which
   are MISSING from the cred-store (new: cross-check `store.list_names()`).
2. If any missing, the owner must capture them (step 4 modal) before "Build it" is enabled.
3. At **build/promote**, the runner injects ONLY that capability's declared secret values as env
   vars into the sandbox run (scoped per-run, not the whole store).

**Forks for the owner:**
1. **When to prompt:** block "Build it" until all secrets present (strict), or allow build and
   prompt at first run (lazy). → *Recommendation: strict — informed consent at the gate, matches
   the plan-gate-egress principle.*
2. **How a capability declares its secret need:** a `secrets:` list in SKILL.md frontmatter (the
   forge already emits this) — confirm the name convention so the gate and the runtime injection
   agree. → *Recommendation: SKILL.md `secrets: [NAME]`; inject as env `NAME` into the sandbox run.*
3. **Injection scope:** per-run env only (never persist into the capability's files or the sandbox
   image). → *Recommendation: per-run env, cleared after; this is a security invariant, not really
   optional.*
4. **Egress + secret together:** fold in `plangate-egress` (show granted `egress_domains` at the
   gate too) so the owner approves both credential AND network scope in one consent moment.
   → *Recommendation: yes, do them together — one consent surface.*

---

## Suggested build order once decided
`cred-store` (step 3, building now) → step 4 brain routes → step 4 client modal → step 5 gate
(cross-check + strict block) → step 5 runtime injection (sandbox env, per-run). Each is small;
apex-security reviews steps 4 + 5 (they move real credentials across the trust boundary).
