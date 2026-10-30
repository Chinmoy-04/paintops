# SOP-PAINT-006 — Rework and Quality Hold Guidance (Synthetic)

**Document ID:** SOP-PAINT-006  
**Title:** Rework and Quality Hold Guidance  

> **SYNTHETIC TRAINING EXAMPLE — NOT AN APPROVED INDUSTRIAL SOP**  
> PaintOps never authorises rework or holds automatically. Humans must approve every ticket.

## Purpose

Describe how a human reviewer might consider a quality inspection or hold proposal after evidence review. This system only drafts tickets — it does not execute rework.

## Applicable station

Downstream quality review desk (synthetic).

## Example defect symptoms

- High-severity defects flagged by analysis
- Recurring same-booth defects
- Missing SOP evidence requiring manual verification

## Inspection checks

1. Review investigation evidence, recurrence count, and SOP references.
2. Confirm the ticket draft marks hypotheses clearly.
3. Approve or reject — rejection must create no ticket.

## Possible contributing factors (hypotheses only)

Depends on upstream SOPs; do not invent causes when evidence is thin.

## Suggested escalation / review steps

- Approve → create exactly one action ticket in SQL.
- Reject → record reviewer and reason; no ticket.
- If `no_relevant_sop_found`, require manual SOP verification before any real-world analogue action.

## Related synthetic procedures

- SOP-PAINT-001 through SOP-PAINT-005
