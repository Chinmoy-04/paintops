# SOP-PAINT-009 — Booth Filter Maintenance (Synthetic)

**Document ID:** SOP-PAINT-009  
**Title:** Booth Exhaust Filter Condition Review  

> **SYNTHETIC TRAINING EXAMPLE — NOT AN APPROVED INDUSTRIAL SOP**  
> Fictional procedure for portfolio demonstration only.

## Purpose

Describe a synthetic review of booth filter condition when dust inclusions recur or filter differential pressure rises.

## Applicable station

All synthetic paint booths (`BOOTH-01` … `BOOTH-09`), especially primer booths.

## Example defect symptoms

- Dust inclusions or fibres trapped in the paint film
- Filter differential pressure trending upward in synthetic telemetry
- Reduced airflow readings alongside the pressure rise

## Inspection checks

1. Confirm `defect_type=dust_inclusion`.
2. Review the filter differential pressure trend over the last 24–48 h.
3. Check when the exhaust filter set was last replaced in the maintenance log.
4. Compare with other booths on the same line to see if the issue is booth-local.

## Possible contributing factors (hypotheses only)

- Loaded or damaged exhaust filters (synthetic)
- Overdue filter replacement interval
- Airflow imbalance pulling particles into the booth

## Suggested escalation / review steps

Draft a `maintenance_inspection` ticket when filter pressure is high and dust defects recur. Pause for human approval.

## Related synthetic procedures

- SOP-PAINT-001 (surface defects)
- SOP-PAINT-003 (booth environment)
