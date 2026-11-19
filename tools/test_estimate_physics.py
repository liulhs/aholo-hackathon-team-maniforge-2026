"""Offline tests for estimate_physics.py (no LLM call, no pxr needed).

Run: python -m pytest hackathon/tools/test_estimate_physics.py -q
"""
from pathlib import Path

import pytest

import estimate_physics as ep

GLB = Path(__file__).resolve().parents[1] / "experiments/2026-11-08-lux3d-takeout-box/g1_standard/raw_mesh.glb"


def _sample(**over):
    base = {
        "material": "paperboard", "is_hollow": True, "wall_thickness_mm": 0.5, "mass_kg": 0.03,
        "static_friction": 0.6, "dynamic_friction": 0.5, "restitution": 0.1, "confidence": 0.6,
        "reasoning": "folded paperboard box",
    }
    return {**base, **over}


@pytest.mark.skipif(not GLB.exists(), reason="Lux3D sample mesh not present")
def test_mesh_stats_matches_measured_takeout_box():
    stats = ep.mesh_stats(*ep.read_glb_mesh(GLB), 1.0)
    assert stats["volume_m3"] == pytest.approx(0.000801, rel=0.02)
    assert max(stats["bbox_m"]) == pytest.approx(0.120, abs=0.002)


def test_validate_sample_rejects_missing_keys_and_absurd_mass():
    assert ep.validate_sample({"material": "paperboard"}) is None
    assert ep.validate_sample(_sample(mass_kg=50.0)) is None
    assert ep.validate_sample(_sample(mass_kg="heavy")) is None
    assert ep.validate_sample(_sample(static_friction=0.0)) is None


def test_validate_sample_accepts_good_reply():
    clean = ep.validate_sample(_sample())
    assert clean is not None and clean["mass_kg"] == 0.03 and clean["is_hollow"] is True


def test_reconcile_hollow_box_uses_shell_mass_not_solid_volume():
    stats = {"area_m2": 0.0804, "volume_m3": 0.000801, "bbox_m": [0.111, 0.12, 0.12]}
    out = ep.reconcile([_sample(mass_kg=m) for m in (0.02, 0.03, 0.04)], stats)
    assert out["mass_kg"] == pytest.approx(0.03)
    assert out["mass_geometry_kg"] == pytest.approx(0.0804 * 0.0005 * 700, rel=0.01)  # ~28 g, not ~560 g
    assert out["flag_review"] is False


def test_reconcile_clips_friction_and_keeps_dynamic_below_static():
    stats = {"area_m2": 0.08, "volume_m3": 0.0008, "bbox_m": [0.1, 0.1, 0.1]}
    out = ep.reconcile([_sample(static_friction=1.8, dynamic_friction=1.9)] * 3, stats)
    assert out["static_friction"] == pytest.approx(0.8)  # paperboard table upper bound
    assert out["dynamic_friction"] <= out["static_friction"]
