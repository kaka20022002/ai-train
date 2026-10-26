from program_recommender import ProgramRecommendationService


def _profile(**overrides):
    profile = {
        "user_id": "usr_recommend",
        "fitness_level": "beginner",
        "fitness_goal": "strength",
        "training_frequency": 3,
        "available_equipment": [],
        "medical_history": [],
    }
    profile.update(overrides)
    return profile


def test_beginner_strength_plan_ranks_first():
    result = ProgramRecommendationService().recommend(
        user_profile=_profile(),
        safe_exercise_count=40,
        forbidden_exercise_count=0,
        limit=6,
    )

    assert result["recommendations"][0]["template_id"] == "strength_foundation_3d"
    assert result["recommendations"][0]["rank"] == 1
    assert result["recommendations"][0]["score"] > 0


def test_equipment_filter_removes_incompatible_templates():
    result = ProgramRecommendationService().recommend(
        user_profile=_profile(available_equipment=["bodyweight"]),
        safe_exercise_count=20,
        forbidden_exercise_count=20,
        limit=12,
    )

    ids = {item["template_id"] for item in result["recommendations"]}
    assert "home_dumbbell_4d" not in ids
    assert "strength_peak_4d" not in ids
    assert "home_bodyweight_3d" in ids
    assert all(not item["required_equipment"] for item in result["recommendations"])


def test_high_rpe_history_lowers_advanced_plan_score():
    service = ProgramRecommendationService()
    profile = _profile(
        fitness_level="advanced",
        fitness_goal="strength",
        training_frequency=4,
    )
    baseline = service.recommend(
        user_profile=profile,
        safe_exercise_count=40,
        forbidden_exercise_count=0,
        limit=12,
    )
    high_load = service.recommend(
        user_profile=profile,
        sessions=[
            {
                "date": "2026-10-01",
                "completion_rate": 0.55,
                "rpe": 9,
                "pain_feedback": {
                    "has_pain": True,
                    "pain_location": "knee",
                },
            }
        ],
        safe_exercise_count=40,
        forbidden_exercise_count=0,
        limit=12,
    )

    baseline_peak = next(
        item
        for item in baseline["recommendations"]
        if item["template_id"] == "strength_peak_4d"
    )
    high_load_peak = next(
        item
        for item in high_load["recommendations"]
        if item["template_id"] == "strength_peak_4d"
    )
    assert high_load_peak["score"] < baseline_peak["score"]
    assert high_load["user_snapshot"]["session_count"] == 1
