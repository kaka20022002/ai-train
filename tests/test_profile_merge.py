"""档案合并：修订计划时只能更严，不能更松。"""
from __future__ import annotations

from agents.contracts import RiskProfile
from agents.profile_merge import stricter_of


def _profile(
    *,
    impact: int = 5,
    load: int | None = None,
    session: int | None = None,
    avoid: tuple[str, ...] = (),
    joint_caps: dict[str, int] | None = None,
    forbidden: dict[int, str] | None = None,
    allowed: tuple[int, ...] = (1, 2, 3, 4),
    level: str = "low",
    clearance: str = "cleared",
    summary: str = "",
) -> RiskProfile:
    return RiskProfile(
        user_id="usr_demo",
        allowed_ids=allowed,
        forbidden_reasons=forbidden or {},
        joint_caps=joint_caps or {},
        impact_ceiling=impact,
        load_pct_cap=load,
        session_cap_minutes=session,
        avoid_patterns=avoid,
        risk_report={
            "overall": {"risk_level": level, "clearance": clearance, "summary": summary}
        },
    )


class TestMerge:
    def test_none_base_returns_other(self) -> None:
        other = _profile(impact=3)
        assert stricter_of(None, other) is other

    def test_takes_stricter_scalars(self) -> None:
        base = _profile(impact=2, load=50, session=30)
        fresh = _profile(impact=5, load=None, session=None)
        merged = stricter_of(base, fresh)
        assert merged.impact_ceiling == 2
        assert merged.load_pct_cap == 50
        assert merged.session_cap_minutes == 30

    def test_none_means_no_cap_so_the_capped_side_wins(self) -> None:
        base = _profile(load=None)
        fresh = _profile(load=60)
        assert stricter_of(base, fresh).load_pct_cap == 60

    def test_patterns_are_unioned(self) -> None:
        base = _profile(avoid=("lunge",))
        fresh = _profile(avoid=("deep_knee_flexion",))
        assert stricter_of(base, fresh).avoid_patterns == (
            "deep_knee_flexion",
            "lunge",
        )

    def test_forbidden_and_joint_caps_unioned(self) -> None:
        base = _profile(forbidden={7: "knee"}, joint_caps={"knee": 2})
        fresh = _profile(forbidden={9: "ankle"}, joint_caps={"knee": 4, "ankle": 3})
        merged = stricter_of(base, fresh)
        assert set(merged.forbidden_reasons) == {7, 9}
        assert merged.joint_caps == {"knee": 2, "ankle": 3}

    def test_allowed_ids_intersect(self) -> None:
        base = _profile(allowed=(1, 2, 3))
        fresh = _profile(allowed=(2, 3, 4))
        assert stricter_of(base, fresh).allowed_ids == (2, 3)

    def test_report_keeps_the_more_conservative_side(self) -> None:
        base = _profile(level="moderate", clearance="conditional", summary="半月板撕裂")
        fresh = _profile(level="low", clearance="cleared", summary="无伤病记录")
        merged = stricter_of(base, fresh)
        assert merged.risk_level == "moderate"
        assert merged.clearance == "conditional"
        assert "半月板" in (merged.risk_report["overall"]["summary"])

    def test_more_conservative_fresh_report_wins(self) -> None:
        base = _profile(level="low", clearance="cleared", summary="无伤病")
        fresh = _profile(level="high", clearance="restricted", summary="急性期")
        merged = stricter_of(base, fresh)
        assert merged.risk_level == "high"
        assert merged.clearance == "restricted"

    def test_hash_reflects_merged_constraints(self) -> None:
        """合并结果的约束是「两边取严」的组合，hash 要能反映它。"""
        base = _profile(impact=2, avoid=())
        fresh = _profile(impact=4, avoid=("lunge",))
        merged = stricter_of(base, fresh)
        assert merged.profile_hash
        assert merged.profile_hash not in (base.profile_hash, fresh.profile_hash)

    def test_hash_matches_base_when_base_is_strictly_stricter(self) -> None:
        """base 全面更严时，合并结果等价于 base —— hash 相同才是对的。"""
        base = _profile(impact=2, load=50)
        fresh = _profile(impact=5, load=80)
        assert stricter_of(base, fresh).profile_hash == base.profile_hash


class TestRoundTrip:
    def test_to_dict_from_dict(self) -> None:
        original = _profile(
            impact=3,
            load=60,
            session=30,
            avoid=("lunge",),
            forbidden={7: "knee"},
            joint_caps={"knee": 2},
        )
        restored = RiskProfile.from_dict(original.to_dict())
        assert restored.impact_ceiling == original.impact_ceiling
        assert restored.load_pct_cap == original.load_pct_cap
        assert restored.session_cap_minutes == original.session_cap_minutes
        assert restored.avoid_patterns == original.avoid_patterns
        assert restored.forbidden_reasons == original.forbidden_reasons
        assert restored.profile_hash == original.profile_hash
        assert restored.risk_level == original.risk_level
