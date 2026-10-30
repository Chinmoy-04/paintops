"""PaintOps Streamlit review inbox — calls FastAPI only."""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE = os.getenv("PAINTOPS_API_BASE", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="PaintOps Review", layout="wide")

st.title("PaintOps — Quality Deviation Review")
st.warning(
    "SYNTHETIC decision-support demo — not for production industrial decisions. "
    "All events, SOPs, and thresholds are fictional portfolio examples."
)


def api_get(path: str, **params):
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{API_BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


def api_post(path: str, payload: dict):
    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{API_BASE}{path}", json=payload)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"API error {r.status_code}: {detail}")
        return r.json()


col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("Pending investigations")
    try:
        pending = api_get("/api/investigations", status="awaiting_approval")
    except Exception as exc:
        st.error(f"Cannot reach API at {API_BASE}: {exc}")
        pending = []

    if not pending:
        st.info("No investigations awaiting approval.")
        selected_id = None
    else:
        labels = {
            f"{p['event_id']} | {p.get('booth_id')} | {p.get('defect_type')} | "
            f"sev={p.get('severity')} | n={p.get('recurrence_count')}": p[
                "investigation_id"
            ]
            for p in pending
        }
        choice = st.radio("Select", list(labels.keys()))
        selected_id = labels[choice]

with col_right:
    st.subheader("Investigation detail")
    if selected_id:
        detail = api_get(f"/api/investigations/{selected_id}")
        st.json(
            {
                "status": detail.get("status"),
                "event": detail.get("event"),
                "recurrence_count": detail.get("recurrence_count"),
                "severity": detail.get("severity"),
                "suspected_cause": detail.get("suspected_cause"),
                "evidence": detail.get("evidence"),
                "sop_references": detail.get("sop_references"),
                "ticket_draft": detail.get("ticket_draft"),
                "analysis_provider": detail.get("analysis_provider"),
            }
        )
        reviewer = st.text_input("Reviewer", value="quality_manager_demo")
        comment = st.text_area("Comment (optional)", value="")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Approve", type="primary"):
                try:
                    result = api_post(
                        f"/api/investigations/{selected_id}/decision",
                        {
                            "decision": "approved",
                            "reviewer": reviewer,
                            "comment": comment or None,
                        },
                    )
                    st.success(result)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        with c2:
            if st.button("Reject"):
                try:
                    result = api_post(
                        f"/api/investigations/{selected_id}/decision",
                        {
                            "decision": "rejected",
                            "reviewer": reviewer,
                            "comment": comment or None,
                        },
                    )
                    st.warning(result)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    else:
        st.write("Select a pending investigation.")

st.divider()
st.subheader("Recent monitored / approved / rejected")
try:
    recent = api_get("/api/investigations")
    filtered = [r for r in recent if r.get("status") in {"monitored", "approved", "rejected"}]
    st.dataframe(filtered[:20], use_container_width=True)
except Exception as exc:
    st.error(str(exc))
