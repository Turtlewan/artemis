# curate-extract golden-set calibration — 2026-07-04 (live haiku)

Required gate before spec 2 wires the extractor live (ai-systems review of `curate-extract`).
Harness: 24 hand-authored cases (canonical saves/forgets, referent phrasings, 9 adversarial
verb-idiom nones, borderlines), run against the real `ClaudeCodeProvider` haiku via
`CurateExtractor.extract` with `existing_domains=["calendar","notes","tasks"]`.
_Corpus caveat: hand-authored, not captured real usage (owner fidelity preference) — treat as a
v1 smoke; refine from real usage once the write path is live._

## Result: 22/24 PASS — gate PASSED with one designed fix routed to spec 2

- **Adversarial prefilter set: 9/9.** "can you save me some time", "log out of my account",
  "track down why the build failed", "what should i add to my tasks?", "do you remember…?",
  "build me a tool that adds…" → all correctly `none`.
- **Verbatim rule held** on every save (content unrephrased, checked by substring).
- **Label reuse (ADR-048 #5) behaved:** "add milk and eggs to the grocery list" → reused `tasks`;
  "log my workout" → new `workouts` (correct emergence); "note:"/"remember" → `notes`.
- **Both failures = one root cause, not model error:** "save the second one" and "forget what i
  said about the plumber" were extracted with the CORRECT op but an empty `domain` (legitimately
  unknown for referent/descriptor utterances) — then the spec-1 empty-domain→degrade rule
  (itself a security-review fold) collapsed them to `none`. The rule is right for
  referent-less saves and wrong for referent ops.

## Design fix (folded into spec 2, which owns curate.py changes)
1. Degrade-to-none on empty `domain` applies ONLY to `save` with an empty `referent`.
2. `forget` needs no domain: resolve via referent/stash or cross-domain content search under the
   exactly-one-match-or-refuse contract (+ synced-domain guard on the resolved row).
3. Referent-`save` with no stated target domain → honest refusal reply ("save it where? — e.g.
   'save the second one to notes'"), no write.

## Watch item (not a fail)
"add a reminder to water the plants every tuesday" → `save` into `calendar` — semantically fair,
but `calendar` is synced; spec 2's synced-domain guard will refuse with the read-only reply. The
reply text should steer the owner to a curated home (e.g. tasks). Revisit if it annoys in dogfood.
