"""Specialist agents and the deterministic plan of which ones run for which defect."""

from __future__ import annotations

from functools import lru_cache

from app.graph.specialists import environment, equipment, process
from app.graph.specialists.base import SpecialistSpec, build_specialist_graph

SPECS: dict[str, SpecialistSpec] = {
    "environment": environment.SPEC,
    "equipment": equipment.SPEC,
    "process": process.SPEC,
}

# Which specialists investigate which defect. Deterministic: a model may later ADD
# specialists to this list but can never remove one. `process` always runs because
# it is the specialist that retrieves the SOPs every ticket must cite.
DEFECT_SPECIALISTS: dict[str, tuple[str, ...]] = {
    "orange_peel": ("environment", "equipment", "process"),
    "runs_sags": ("equipment", "process"),
    "dust_inclusion": ("environment", "equipment", "process"),
    "uneven_coverage": ("equipment", "process"),
    "fisheye_craters": ("equipment", "process"),
    "color_mismatch": ("environment", "process"),
}


def plan_for(defect_type: str) -> list[str]:
    """Specialists to run for a defect; falls back to all of them for an unknown defect."""
    return list(DEFECT_SPECIALISTS.get(defect_type, tuple(SPECS)))


@lru_cache
def specialist_graph(name: str):
    """Compiled subgraph for a specialist (compiled once per process)."""
    return build_specialist_graph(SPECS[name])
