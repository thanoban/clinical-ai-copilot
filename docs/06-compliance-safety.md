# 06 — Compliance, Safety & Ethics

Build these in from Phase 0. They are cheap to design in and expensive to retrofit.

## Human-in-the-loop is the product, not a feature

Every output is a **draft for a clinician to confirm**. The dashboard's
confirm/edit/reject action (pipeline step 9) is a required gate — the system never
emits a clinically actionable result on its own. This constraint shapes the UI, the
API contract, and the story you tell regulators and investors.

## PHI & de-identification

- **De-identify at ingestion**, inside the `IngestionPort` adapter, before any
  other component sees the artifact. Strip DICOM PHI tags, burn-in text, and
  free-text identifiers.
- If using real patient data: **IRB/ethics approval + PhysioNet DUAs** required.
- Raw data and weights never enter git — DVC pointers only (see [03](03-tech-stack.md)).
- PHI-touching services run in a locked-down environment (on-prem or isolated VPC).

## Regulatory framing

A *deployed* diagnostic tool is **Software as a Medical Device (SaMD)** — FDA / CE /
CDSCO territory. For the research/MVP stage:

- Stay clearly in **"research prototype, not for clinical use."** State it in the
  UI and in any paper.
- Design the human-confirm gate and audit logging as if you *will* seek clearance
  later — it makes the eventual SaMD path far shorter.
- Do not let the product "look like a cleared device." Hard research-only framing
  throughout (a listed liability risk).

## Bias & subgroup performance

- Report performance **per subgroup**: age, sex, scanner/manufacturer, site.
- Imaging models fail *silently* on out-of-distribution scanners — the OOD detector
  in the guardrail (step 7) is a safety control, not just a metric.
- Bake subgroup reporting into `eval/` from Phase 7, not as an afterthought.

## Failure transparency

- **Log every low-confidence escalation.** Never suppress uncertainty to look more
  capable.
- Calibration curves and selective-prediction plots are first-class deliverables.
- The verifier's disagreements are surfaced to the clinician, not hidden — a
  flagged conflict is *more* trustworthy than a smooth false consensus.

## Safety checklist (per release)

- [ ] De-identification verified on a held-out sample (no PHI leaks).
- [ ] "Research only — not for clinical use" visible in the UI and reports.
- [ ] Human-confirm gate cannot be bypassed via the API.
- [ ] Low-confidence / OOD cases escalate and are logged.
- [ ] Subgroup performance reported; no silent regression on a subgroup.
- [ ] Verifier is a genuinely different model from the specialist.
