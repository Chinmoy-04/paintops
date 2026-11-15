# SOP-PAINT-008 — Colour Mismatch Investigation (Synthetic)

**Document ID:** SOP-PAINT-008  
**Title:** Colour Mismatch Investigation  

> **SYNTHETIC TRAINING EXAMPLE — NOT AN APPROVED INDUSTRIAL SOP**  
> Fictional procedure for portfolio demonstration only.

## Purpose

Outline a synthetic investigation when the inspection station flags a body whose colour differs from the reference panel.

## Applicable station

Basecoat booths (`BOOTH-02`, `BOOTH-05`, `BOOTH-08`) in demo fixtures.

## Example defect symptoms

- Shade or flop difference compared with the synthetic reference panel
- Difference visible between adjacent panels of the same body
- Lower model confidence than texture defects in demo fixtures

## Inspection checks

1. Confirm `defect_type=color_mismatch`.
2. Identify the active material batch and when it started (see SOP-PAINT-010).
3. Compare booth telemetry against the booth's own baseline (see SOP-PAINT-003).
4. Check whether film build may differ because of nozzle condition (see SOP-PAINT-004).

## Possible contributing factors (hypotheses only)

- Batch-to-batch tint variation (synthetic)
- Film thickness variation from spray pattern changes
- Incomplete mixing of the material before use

## Suggested escalation / review steps

Draft a `quality_inspection` ticket for repeated mismatches on one batch. Pause for human approval.

## Related synthetic procedures

- SOP-PAINT-004 (spray nozzle inspection)
- SOP-PAINT-010 (material batch handling)
