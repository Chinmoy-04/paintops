# SOP-PAINT-002 — Orange Peel Investigation (Synthetic)

**Document ID:** SOP-PAINT-002  
**Title:** Orange Peel Texture Investigation  

> **SYNTHETIC TRAINING EXAMPLE — NOT AN APPROVED INDUSTRIAL SOP**  
> Fictional demo content only. Not an approved industrial procedure.

## Purpose

Guide synthetic investigation of orange-peel appearance defects reported by the computer-vision inspection station.

## Applicable station

Clearcoat booths (`BOOTH-03`, `BOOTH-06`, `BOOTH-09`), especially `BOOTH-03` on `PAINT-LINE-01` in demo fixtures.

## Example defect symptoms

- Micro-textured “orange peel” appearance after clearcoat cure
- Higher model confidence when texture is uniform across a panel
- Often co-occurs with elevated humidity readings in synthetic telemetry

## Inspection checks

1. Confirm `defect_type=orange_peel`.
2. Review booth temperature, humidity, and airflow telemetry.
3. Count recent orange-peel events in the same booth within 60 minutes (demo window).
4. Check spray nozzle inspection history (see SOP-PAINT-004).

## Possible contributing factors (hypotheses only)

- Humidity above the synthetic comfort band (~65%+)
- Reduced airflow reducing atomisation quality
- Spray viscosity or atomising pressure drift
- Nozzle fouling

## Suggested escalation / review steps

If three or more orange-peel events occur in the same booth within the synthetic recurrence window, draft a quality/maintenance inspection ticket for human approval. Do not change machine settings automatically.

## Related synthetic procedures

- SOP-PAINT-001 (surface defects overview)
- SOP-PAINT-003 (booth environment)
- SOP-PAINT-004 (spray nozzle inspection)
