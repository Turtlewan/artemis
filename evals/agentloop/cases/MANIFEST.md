# Agent-Loop Eval Corpus Manifest

All cases in this corpus are synthetic for this build. Record and memory fixtures use authored local-data scenarios with `source="authored"` unless a case note explicitly marks a synthetic domain marker.

Real-capture of live domains (calendar, tasks/passport) + owner label refinement is the owner follow-up step; capture.py is built + hermetically tested here.

## Counts

| kind | count | provenance |
|---|---:|---|
| driver_golden | 22 | synthetic |
| injection | 14 | synthetic |
| judge_calibration | 14 | synthetic |
| escalation | 12 | synthetic |

## Injection Coverage

| steer_target | count |
|---|---:|
| driver_action | 4 |
| exfil_read | 4 |
| judge_flip | 3 |
| handoff_survival | 3 |

Synthetic canary payload cases: `inj-002-driver-action-write`, `inj-004-exfil-secrets`, `inj-006-exfil-passport`, `inj-008-judge-flip-pass`, `inj-011-handoff-survival-corrective`.

## Judge Calibration Labels

| sub-kind | count | human_label_passed |
|---|---:|---|
| grounded+addresses | 4 | True |
| ungrounded/invented-fact | 3 | False |
| borderline/partial-address | 2 | False |
| false-premise | 2 | False |
| false-accept-probe confident-but-ungrounded | 3 | False |

## Case Provenance

Every `driver_golden`, `injection`, `judge_calibration`, and `escalation` case file in this directory tree is synthetic and authored for this corpus freeze. Injection payloads are inert JSON string data in `sanitized_text`; synthetic canary values live only in `payload` fields and are never intended to be rendered by local reads.
