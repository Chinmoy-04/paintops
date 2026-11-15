# SOP-PAINT-007 — Fisheye and Crater Investigation (Synthetic)

**Document ID:** SOP-PAINT-007  
**Title:** Fisheye / Crater Contamination Investigation  

> **SYNTHETIC TRAINING EXAMPLE — NOT AN APPROVED INDUSTRIAL SOP**  
> Fictional procedure for portfolio demonstration only.

## Purpose

Guide synthetic investigation of fisheye and crater defects (small circular voids where the paint film pulls away from a spot) reported by the inspection station.

## Applicable station

Basecoat and clearcoat booths on `PAINT-LINE-01` … `PAINT-LINE-03` (synthetic).

## Example defect symptoms

- Small round craters with a raised rim in the paint film
- Clusters on several bodies within a short time window
- Onset shortly after a material or process change in demo fixtures

## Inspection checks

1. Confirm `defect_type=fisheye_craters`.
2. Check whether a new material batch started in the booth before the first event (see SOP-PAINT-010).
3. Check whether the pattern is booth-local or affects several booths on the same line.
4. Review recent surface preparation records (see SOP-PAINT-005).

## Possible contributing factors (hypotheses only)

- Silicone or oil contamination on the substrate or in compressed air (synthetic)
- Material batch outside the demo viscosity band
- Incomplete cleaning after maintenance

## Suggested escalation / review steps

Draft a `quality_inspection` ticket when craters recur after a batch change. Consider a quality hold per SOP-PAINT-006. Pause for human approval.

## Related synthetic procedures

- SOP-PAINT-005 (surface preparation)
- SOP-PAINT-006 (rework and quality hold)
- SOP-PAINT-010 (material batch handling)
