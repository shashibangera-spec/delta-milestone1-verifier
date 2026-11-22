# Product Owner Decision Log

This log records decisions and scope boundaries known to be approved. Dates use UTC where an exact timestamp is available; otherwise the date is recorded without inventing a time.

| Date | Decision / approval | Status and effect |
|---|---|---|
| 20 Nov 2026 | AMT Engine V1.0 work isolated in the designated verifier repository; preserve existing historical baseline and collector evidence. | **APPROVED** — no changes to unrelated repositories or existing immutable evidence. |
| 21 Nov 2026 | AMT Engine V1.0 deterministic daily profile methodology approved: Delta India BTCUSD PRICE 30m, 48 bars, UTC 00:00–00:00 session, $50 globally anchored rows, 70% VA, lower-price POC tie and Option A one-row-at-a-time VA expansion. | **APPROVED / FROZEN** — see [specification](AMT_ENGINE_V1_SPEC.md). |
| 21 Nov 2026 | Historical parity scope accepted for 183 profiles and 8,113 TPO rows, read-only, with no writes to live or reference branch. | **COMPLETED** — zero reported mismatches; session assignment remains conditional. |
| 21 Nov 2026 | Historical session assignment must remain CONDITIONAL because timestamp semantics are not independently proven. | **BINDING QUALIFICATION** — no claim of proven session alignment. |
| 21 Nov 2026 | Implementation commit `5e55c3ea8adbfc87907d0225d4d006a38746900b` passed 39 offline tests and compile verification; parity was not established by that test result alone. | **RECORDED** — later parity workflow evidence is separately listed in the validation register. |
| 22 Nov 2026 | Closed-session writer guard and persistence rollback coverage accepted as implementation hardening. | **APPROVED** — methodology unchanged; offline CI evidence at [run 44992010705](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44992010705). |
| 22 Nov 2026 | PR #10 branch reconciliation accepted and closed. | **COMPLETED** — [PR #10](https://github.com/shashibangera-spec/delta-milestone1-verifier/pull/10); historical-parity workflow unchanged; no historical calculation or database write included. |
| 22 Nov 2026 | Historical AMT Research milestone accepted as substantially complete with clarification addendum qualifications. | **CLOSED** — preserve the 183-session baseline; no reconstruction, profile recalculation or further research initiated. |
| 22 Nov 2026 | Accepted 20 and 21 November daily profiles and historical parity evidence remain immutable. | **BINDING** — no overwrite, recalculation or reopening. |
| 22 Nov 2026 | 22 November daily calculation remains a separate scheduled validation and is pending until actually completed and validated. | **PENDING** — do not infer acceptance from a successful workflow run. |
| 22 Nov 2026 | This documentation-only update is authorized in `delta-milestone1-verifier` as a separate PR. | **AUTHORIZED SCOPE** — Markdown documentation only; no code, database, schema, workflow, Pine, collector, dashboard or production configuration changes. |
| 22 Nov 2026 | Future developing-auction, value-migration and event-sequencing research may be considered separately. | **NOT AUTHORIZED YET** — separate commissioning required. |

## Standing change-control rules

1. Approved AMT Engine V1.0 calculation rules must not be silently altered.
2. Historical profiles, fingerprints, parity evidence and accepted daily records are immutable.
3. Documentation may be updated when an authorized milestone completes, but must preserve the historical decision and evidence trail.
4. Mark unknown facts **UNVERIFIED**, assumptions **CONDITIONAL**, and unfinished work **PENDING**.
5. No production readiness or unattended-operation claim without direct evidence and explicit approval.
6. No new research phase, implementation, schema migration, workflow change, Pine change, collector/dashboard change or production action without separate explicit authorization.


## Auction State Observer V1 — delegated methodology dispositions (22 Nov 2026)

| Date | Decision / approval | Status and effect |
|---|---|---|
| 22 Nov 2026 | Auction State Observer V1 consolidated methodology baseline accepted for documentation purposes. | **APPROVED / CLOSED FOR DOCUMENTATION** — see [final methodology](AUCTION_STATE_OBSERVER_V1_METHODOLOGY.md) and [Issue #13](https://github.com/shashibangera-spec/delta-milestone1-verifier/issues/13). No implementation authorization. |
| 22 Nov 2026 | Balance anchor fixed to the first expected 00:00–00:30 UTC candle; developing-profile snapshot captured at that candle's confirmed close. | **FINALIZED RULE** — subject to verified source timestamp/session mapping. |
| 22 Nov 2026 | Balance assessment requires all 12 expected bars to be present and valid; evaluate only after the twelfth bar closes. | **FINALIZED RULE** — any missing/invalid/unconfirmed/conflicting bar or unavailable anchor snapshot yields INSUFFICIENT EVIDENCE; no late start or re-anchoring. |
| 22 Nov 2026 | Balance remains unavailable as a confirmed first-screen condition until the read-only 6/12/16-bar historical sensitivity review is completed and accepted. | **BINDING VALIDATION GATE** — 12 bars remains an initial operational design threshold, not an empirically validated market constant. |
| 22 Nov 2026 | Profile acceptance, source finality, exact feed/timestamp/session mapping and developing-profile as-of validity remain explicit evidence gates. | **NOT VERIFIED / CONDITIONAL** — do not infer PASS from completeness, run success, elapsed time or row existence. |
| 22 Nov 2026 | Observer V1 work is documentation-only under the existing freeze. | **AUTHORIZED SCOPE** — methodology/status/decision/validation documentation only; no application code, database, schema, collector, PR implementation, staging, production dashboard or deployment changes. |

These are delegated Observer methodology dispositions recorded for the documentation baseline; they are not represented as separate decisions individually approved by the Product Owner. They close the methodology design baseline for documentation only and do not certify capability, validation completion or implementation readiness.
