"""
Plan Generator - Mock and Real LLM Workout Plan Generation
===========================================================

This module provides the "Plan Generation Agent" that can either:

1. Use a MOCK LLM function to generate deterministic, offline workout plans
2. Call a REAL LLM (e.g., OpenAI GPT 系列模型) to generate plans

The real LLM path is optional and controlled via configuration. When no
API key is provided or USE_REAL_LLM is disabled, the system safely
falls back to the mock generator.

Author: Master's Thesis Project - Adaptive Athletic Risk Assessment System
Date: 2026-03-04

Integration Flow:
1. RiskAssessmentEngine → generates constraints
2. PlanGeneratorMock → receives constraints → generates safe workout plan
3. Output → Human-readable workout plan
"""

import json
import os
import random
from datetime import datetime, timezone
from typing import List, Dict, Any, Set, Optional
from dataclasses import dataclass
from enum import Enum

# Import our Risk Assessment Engine
from risk_engine import RiskAssessmentEngine, ForbiddenExercise, RiskConstraint
from llm_client import LLMClient
from exercise_meta import sanitize_workout_phases, guided_exercise_names


class WorkoutPhase(Enum):
    """Phases of a structured workout session."""
    WARMUP = "warm_up"
    ACTIVATION = "activation"
    MAIN_LIFTS = "main_lifts"
    ACCESSORIES = "accessories"
    COOLDOWN = "cool_down"


class ExerciseCategory(Enum):
    """Exercise categories for workout structuring."""
    COMPOUND = "Compound"
    ISOLATION = "Isolation"
    ISOMETRIC = "Isometric"


@dataclass
class PlannedExercise:
    """Represents a single exercise in the workout plan."""
    name: str
    sets: int
    reps: str  # Can be "8-12" or "30 seconds" for isometrics
    rest_seconds: int
    notes: Optional[str] = None
    target_muscle: Optional[str] = None


@dataclass
class WorkoutPlan:
    """Complete workout plan structure."""
    plan_id: str
    user_id: str
    date: str
    workout_type: str
    estimated_duration_minutes: int
    warm_up: List[PlannedExercise]
    activation: List[PlannedExercise]
    main_lifts: List[PlannedExercise]
    accessories: List[PlannedExercise]
    cool_down: List[PlannedExercise]
    safety_notes: List[str]


class MockLLMResponse:
    """
    Mock LLM Response Generator
    
    This class simulates what an actual LLM (GPT-4, Claude, etc.) would do
    when generating a workout plan. It demonstrates the constraint-respecting
    logic that would be embedded in the LLM prompt.
    
    In production, this would be replaced with actual API calls to:
    - OpenAI GPT-4
    - Anthropic Claude
    - Local LLM via Ollama
    """
    
    # Pre-defined exercise pools for each workout phase
    # These would typically come from the exercise_db, but we define
    # phase-specific templates here for the mock
    
    WARMUP_EXERCISES = [
        PlannedExercise("Light Treadmill Walk", 1, "5 分钟", 0, "自觉强度 3–4（轻松）"),
        PlannedExercise("Jumping Jacks", 2, "30 seconds", 30, "Low impact"),
        PlannedExercise("Arm Circles", 2, "20 each direction", 15),
        PlannedExercise("Leg Swings", 2, "15 each leg", 15),
        PlannedExercise("Hip Circles", 2, "10 each direction", 15),
        PlannedExercise("Cat-Cow Stretch", 2, "10 reps", 15, "Spinal mobility"),
        PlannedExercise("Bodyweight Good Morning", 2, "10 reps", 15, "Hamstring activation"),
    ]
    
    ACTIVATION_EXERCISES = [
        PlannedExercise("Glute Bridge", 2, "15 reps", 30, "Squeeze at top"),
        PlannedExercise("Bird Dog", 2, "10 each side", 30, "Core stability"),
        PlannedExercise("Dead Bug", 2, "10 each side", 30, "Anti-extension"),
        PlannedExercise("Band Pull-Apart", 2, "15 reps", 30, "Rear delt activation"),
        PlannedExercise("Clamshells", 2, "15 each side", 30, "Hip external rotation"),
        PlannedExercise("Scapular Push-Ups", 2, "10 reps", 30, "Shoulder stability"),
    ]
    
    COOLDOWN_EXERCISES = [
        PlannedExercise("Static Quad Stretch", 1, "30 seconds each", 0),
        PlannedExercise("Hamstring Stretch", 1, "30 seconds each", 0),
        PlannedExercise("Chest Doorway Stretch", 1, "30 seconds", 0),
        PlannedExercise("Child's Pose", 1, "60 seconds", 0, "Deep breathing"),
        PlannedExercise("Supine Twist", 1, "30 seconds each side", 0),
        PlannedExercise("Foam Rolling - Full Body", 1, "5 minutes", 0, "Focus on tight areas"),
    ]
    
    @staticmethod
    def generate_mock_response(
        safe_exercises: List[str],
        forbidden_exercises: List[ForbiddenExercise],
        constraints: List[RiskConstraint],
        exercise_db: List[Dict[str, Any]],
        user_profile: Dict[str, Any],
        workout_type: str = "full_body"
    ) -> WorkoutPlan:
        """
        Generate a mock LLM workout plan response.
        
        This simulates what an LLM would do:
        1. Parse the constraints
        2. Filter available exercises
        3. Structure a balanced workout
        4. Add appropriate sets/reps/rest
        5. Include safety notes
        
        Args:
            safe_exercises: List of exercise names that passed risk filtering
            forbidden_exercises: List of exercises to avoid
            constraints: Dynamic constraints from feedback analysis
            exercise_db: Full exercise database
            user_profile: User profile with fitness level
            workout_type: Type of workout (full_body, upper, lower, push, pull)
            
        Returns:
            WorkoutPlan object with complete workout structure
        """
        
        # Extract forbidden exercise names for quick lookup
        forbidden_names: Set[str] = {ex.name for ex in forbidden_exercises}
        
        # Extract affected joints from constraints for extra caution
        affected_joints: Set[str] = set()
        for constraint in constraints:
            if constraint.affected_joints:
                affected_joints.update(constraint.affected_joints)
        
        # Build exercise lookup from database
        exercise_lookup: Dict[str, Dict] = {
            ex['name']: ex for ex in exercise_db
        }
        
        # Filter safe exercises by workout type and remove any involving affected joints
        filtered_safe: List[str] = []
        for ex_name in safe_exercises:
            if ex_name in forbidden_names:
                continue
            
            ex_data = exercise_lookup.get(ex_name, {})
            involved_joints = [j.lower() for j in ex_data.get('involved_joints', [])]
            
            # Extra caution: if user has acute pain in a joint, avoid ALL exercises
            # that involve that joint, even if they're technically "safe"
            if affected_joints and any(joint in affected_joints for joint in involved_joints):
                continue
            
            filtered_safe.append(ex_name)
        
        # Categorize exercises
        compound_exercises: List[str] = []
        isolation_exercises: List[str] = []
        
        for ex_name in filtered_safe:
            ex_data = exercise_lookup.get(ex_name, {})
            if ex_data.get('type') == 'Compound':
                compound_exercises.append(ex_name)
            else:
                isolation_exercises.append(ex_name)
        
        # Determine fitness level for volume/intensity adjustment
        fitness_level = user_profile.get('fitness_level', 'beginner')
        
        # Adjust sets/reps based on fitness level
        if fitness_level == 'beginner':
            main_sets, main_reps = 3, "8-10"
            accessory_sets, accessory_reps = 2, "10-12"
        elif fitness_level == 'intermediate':
            main_sets, main_reps = 4, "6-10"
            accessory_sets, accessory_reps = 3, "10-15"
        else:  # advanced
            main_sets, main_reps = 5, "5-8"
            accessory_sets, accessory_reps = 4, "8-12"
        
        # Check for intensity reduction constraint
        intensity_reduced = False
        for constraint in constraints:
            if constraint.constraint_type == "intensity" and "REDUCE" in constraint.description:
                intensity_reduced = True
                main_sets = max(2, main_sets - 1)
                accessory_sets = max(2, accessory_sets - 1)
                break
        
        # Select main lifts (2-3 compound movements)
        selected_main: List[PlannedExercise] = []
        num_main = min(3, len(compound_exercises))
        
        if compound_exercises:
            random.shuffle(compound_exercises)
            for ex_name in compound_exercises[:num_main]:
                ex_data = exercise_lookup.get(ex_name, {})
                selected_main.append(PlannedExercise(
                    name=ex_name,
                    sets=main_sets,
                    reps=main_reps,
                    rest_seconds=90 if fitness_level != 'beginner' else 120,
                    target_muscle=ex_data.get('target_muscle', 'Multiple'),
                    notes=f"Risk Level: {ex_data.get('risk_level', 'N/A')}/5"
                ))
        
        # Select accessories (3-4 isolation movements)
        selected_accessories: List[PlannedExercise] = []
        num_accessories = min(4, len(isolation_exercises))
        
        if isolation_exercises:
            random.shuffle(isolation_exercises)
            for ex_name in isolation_exercises[:num_accessories]:
                ex_data = exercise_lookup.get(ex_name, {})
                selected_accessories.append(PlannedExercise(
                    name=ex_name,
                    sets=accessory_sets,
                    reps=accessory_reps,
                    rest_seconds=60,
                    target_muscle=ex_data.get('target_muscle', 'N/A'),
                    notes=None
                ))
        
        # Generate safety notes based on constraints
        safety_notes: List[str] = []
        
        if forbidden_exercises:
            safety_notes.append(
                f"⚠️ 已根据伤病史排除 {len(forbidden_exercises)} 个高风险动作。"
            )
        
        for constraint in constraints:
            if constraint.priority == 1:
                safety_notes.append(f"🔴 严重：{constraint.description[:100]}…")
            elif constraint.priority == 2:
                safety_notes.append(f"🟠 重要：{constraint.description[:100]}…")
        
        if intensity_reduced:
            safety_notes.append("📉 因上次训练自觉强度偏高，本次训练量已下调约 20%。")
        
        if affected_joints:
            joint_cn = {
                "knee": "膝", "shoulder": "肩", "spine": "脊柱", "hip": "髋",
                "ankle": "踝", "elbow": "肘", "wrist": "腕", "neck": "颈",
            }
            joints = "、".join(joint_cn.get(j, j) for j in affected_joints)
            safety_notes.append(f"🩹 因存在急性疼痛，已尽量减少涉及 {joints} 的动作。")
        
        safety_notes.append("💡 训练中若出现剧烈疼痛应立即停止。")
        safety_notes.append("💧 注意补水，必要时适当延长组间休息。")
        
        # Select warmup and cooldown (random subset)
        warmup = random.sample(
            MockLLMResponse.WARMUP_EXERCISES, 
            min(4, len(MockLLMResponse.WARMUP_EXERCISES))
        )
        activation = random.sample(
            MockLLMResponse.ACTIVATION_EXERCISES,
            min(3, len(MockLLMResponse.ACTIVATION_EXERCISES))
        )
        cooldown = random.sample(
            MockLLMResponse.COOLDOWN_EXERCISES,
            min(4, len(MockLLMResponse.COOLDOWN_EXERCISES))
        )
        
        # Calculate estimated duration
        warmup_time = 5
        activation_time = 5
        main_time = sum(ex.sets * 2 for ex in selected_main)  # ~2 min per set
        accessory_time = sum(ex.sets * 1.5 for ex in selected_accessories)  # ~1.5 min per set
        cooldown_time = 5
        total_time = int(warmup_time + activation_time + main_time + accessory_time + cooldown_time)
        
        # Create the workout plan
        plan = WorkoutPlan(
            plan_id=f"plan_{random.randint(10000, 99999)}",
            user_id=user_profile.get('user_id', 'unknown'),
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            workout_type=workout_type,
            estimated_duration_minutes=total_time,
            warm_up=warmup,
            activation=activation,
            main_lifts=selected_main,
            accessories=selected_accessories,
            cool_down=cooldown,
            safety_notes=safety_notes
        )
        
        return plan


class PlanGeneratorMock:
    """
    Mock Plan Generator that simulates LLM-based workout generation.
    
    This class demonstrates the integration between the Risk Assessment Engine
    and a hypothetical LLM-based plan generator. In production, the `generate_plan`
    method would make actual API calls to an LLM service.
    """
    
    def __init__(
        self,
        risk_engine: RiskAssessmentEngine,
        use_llm: bool = False,
        llm_client: Optional[LLMClient] = None,
    ):
        """Initialize the Plan Generator with a Risk Assessment Engine.

        Args:
            risk_engine: Instance of RiskAssessmentEngine for constraint generation
            use_llm: Whether to use a real LLM instead of the mock generator
            llm_client: Optional pre-configured LLMClient instance
        """
        self.risk_engine = risk_engine
        self.exercise_db = risk_engine.exercise_db
        self.use_llm = use_llm
        self.llm_client = llm_client
        self.generator_version = "llm_v1.0" if use_llm else "mock_v1.0"
    
    def generate_plan(
        self,
        user_profile: Dict[str, Any],
        feedback_input: Optional[Dict[str, Any]] = None,
        workout_type: str = "full_body",
        history_context: str = "",
    ) -> WorkoutPlan:
        """
        Generate a personalized, constraint-respecting workout plan.

        This method orchestrates the full pipeline:
        1. Run static risk analysis on user profile
        2. Run dynamic feedback analysis (if feedback provided)
        3. Generate LLM constraints prompt
        4. Call mock LLM (or real LLM) to generate plan, injecting history_context
        5. Return structured workout plan

        Args:
            user_profile    : User profile with medical history
            feedback_input  : Optional recent workout feedback
            workout_type    : Type of workout to generate
            history_context : Pre-formatted training history context string from
                              history_analyzer.analyze_history() — injected into
                              the LLM prompt when USE_REAL_LLM is enabled.

        Returns:
            WorkoutPlan object ready for rendering
        """
        print("\n" + "="*70)
        print("🤖 PLAN GENERATOR - Starting Workout Generation Pipeline")
        print("="*70)
        
        # Step 1: Static Risk Analysis
        print("\n📋 Step 1: Running Static Risk Analysis...")
        forbidden_exercises, safe_exercises = self.risk_engine.analyze_static_risk(user_profile)
        
        # Step 2: Dynamic Feedback Analysis (if available)
        constraints: List[RiskConstraint] = []
        if feedback_input:
            print("\n📋 Step 2: Running Dynamic Feedback Analysis...")
            constraints = self.risk_engine.analyze_dynamic_feedback(feedback_input)
        else:
            print("\n📋 Step 2: No feedback provided, skipping dynamic analysis.")
        
        # Step 3: Generate LLM Prompt (for demonstration)
        print("\n📋 Step 3: Generating LLM Constraint Prompt...")
        llm_prompt = self.risk_engine.generate_llm_prompt_constraints(forbidden_exercises, constraints)
        
        # Step 4: Call Real LLM or Mock LLM
        print("\n📋 Step 4: Generating Workout Plan...")

        if self.use_llm:
            print("   [LLM MODE] Calling real LLM for plan generation...")

            # Lazy-init 默认 LLMClient，避免在未启用时强依赖 API Key
            if self.llm_client is None:
                self.llm_client = LLMClient()

            try:
                plan_dict = self.llm_client.generate_workout_plan(
                    constraints_text=llm_prompt,
                    user_profile=user_profile,
                    workout_type=workout_type,
                    safe_exercises=safe_exercises,
                    forbidden_exercises=forbidden_exercises,
                    constraints=constraints,
                    history_context=history_context,
                )
                workout_plan = self._plan_from_json(plan_dict)
            except (ValueError, Exception) as llm_err:
                print(
                    f"   ⚠️  LLM generation failed ({llm_err}). "
                    "Falling back to Mock generator."
                )
                workout_plan = MockLLMResponse.generate_mock_response(
                    safe_exercises=safe_exercises,
                    forbidden_exercises=forbidden_exercises,
                    constraints=constraints,
                    exercise_db=self.exercise_db,
                    user_profile=user_profile,
                    workout_type=workout_type,
                )
                # Reflect the fallback in the version tag
                self.generator_version = "mock_v1.0_fallback"
        else:
            print("   [MOCK MODE] Simulating GPT-style response locally...")
            workout_plan = MockLLMResponse.generate_mock_response(
                safe_exercises=safe_exercises,
                forbidden_exercises=forbidden_exercises,
                constraints=constraints,
                exercise_db=self.exercise_db,
                user_profile=user_profile,
                workout_type=workout_type,
            )
        
        print("   ✅ Workout plan generated successfully!")
        
        return workout_plan
    
    def render_plan_as_text(self, plan: WorkoutPlan) -> str:
        """
        Render the workout plan as a human-readable text format.
        
        Args:
            plan: WorkoutPlan object to render
            
        Returns:
            Formatted string representation of the workout plan
        """
        lines = [
            "",
            "╔" + "═"*68 + "╗",
            "║" + " 🏋️ PERSONALIZED WORKOUT PLAN ".center(68) + "║",
            "╠" + "═"*68 + "╣",
            f"║  Plan ID: {plan.plan_id}".ljust(69) + "║",
            f"║  User: {plan.user_id}".ljust(69) + "║",
            f"║  Date: {plan.date}".ljust(69) + "║",
            f"║  Type: {plan.workout_type.replace('_', ' ').title()}".ljust(69) + "║",
            f"║  Duration: ~{plan.estimated_duration_minutes} minutes".ljust(69) + "║",
            "╠" + "═"*68 + "╣",
        ]
        
        # Safety Notes Section
        lines.append("║  ⚠️  SAFETY NOTES:".ljust(69) + "║")
        lines.append("║" + " "*68 + "║")
        for note in plan.safety_notes:
            # Wrap long notes
            wrapped = self._wrap_text(note, 64)
            for line in wrapped:
                lines.append(f"║    {line}".ljust(69) + "║")
        lines.append("╠" + "═"*68 + "╣")
        
        # Warm-up Section
        lines.append("║  🔥 WARM-UP (5 minutes)".ljust(69) + "║")
        lines.append("║" + " "*68 + "║")
        for ex in plan.warm_up:
            lines.append(f"║    • {ex.name}: {ex.reps}".ljust(69) + "║")
        lines.append("╠" + "═"*68 + "╣")
        
        # Activation Section
        lines.append("║  ⚡ ACTIVATION (5 minutes)".ljust(69) + "║")
        lines.append("║" + " "*68 + "║")
        for ex in plan.activation:
            lines.append(f"║    • {ex.name}: {ex.sets}x{ex.reps}".ljust(69) + "║")
        lines.append("╠" + "═"*68 + "╣")
        
        # Main Lifts Section
        lines.append("║  💪 MAIN LIFTS".ljust(69) + "║")
        lines.append("║" + " "*68 + "║")
        for i, ex in enumerate(plan.main_lifts, 1):
            lines.append(f"║    {i}. {ex.name}".ljust(69) + "║")
            lines.append(f"║       Sets: {ex.sets} | Reps: {ex.reps} | Rest: {ex.rest_seconds}s".ljust(69) + "║")
            lines.append(f"║       Target: {ex.target_muscle}".ljust(69) + "║")
            if ex.notes:
                lines.append(f"║       Note: {ex.notes}".ljust(69) + "║")
            lines.append("║" + " "*68 + "║")
        lines.append("╠" + "═"*68 + "╣")
        
        # Accessories Section
        lines.append("║  🎯 ACCESSORIES".ljust(69) + "║")
        lines.append("║" + " "*68 + "║")
        for i, ex in enumerate(plan.accessories, 1):
            lines.append(f"║    {i}. {ex.name}".ljust(69) + "║")
            lines.append(f"║       Sets: {ex.sets} | Reps: {ex.reps} | Rest: {ex.rest_seconds}s".ljust(69) + "║")
            lines.append(f"║       Target: {ex.target_muscle}".ljust(69) + "║")
            lines.append("║" + " "*68 + "║")
        lines.append("╠" + "═"*68 + "╣")
        
        # Cool-down Section
        lines.append("║  🧘 COOL-DOWN (5 minutes)".ljust(69) + "║")
        lines.append("║" + " "*68 + "║")
        for ex in plan.cool_down:
            lines.append(f"║    • {ex.name}: {ex.reps}".ljust(69) + "║")
        
        lines.append("╚" + "═"*68 + "╝")
        
        return "\n".join(lines)
    
    def _wrap_text(self, text: str, width: int) -> List[str]:
        """Wrap text to specified width."""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + 1 <= width:
                current_line.append(word)
                current_length += len(word) + 1
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_length = len(word)
        
        if current_line:
            lines.append(" ".join(current_line))
        
        return lines if lines else [""]
    
    def export_plan_as_json(
        self,
        plan: WorkoutPlan,
        generator_version: str = "mock_v1.0",
    ) -> Dict[str, Any]:
        """
        Export the workout plan as a JSON-serializable dictionary.

        This format is useful for:
        - Storing in a database
        - Sending to a mobile app
        - Integration with other services

        Args:
            plan: WorkoutPlan object to export
            generator_version: Version tag reflecting which generator
                produced the plan (e.g. "mock_v1.0" or "llm_v1.0").

        Returns:
            Dictionary representation of the plan
        """
        def exercise_to_dict(ex: PlannedExercise) -> Dict:
            return {
                "name": ex.name,
                "sets": ex.sets,
                "reps": ex.reps,
                "rest_seconds": ex.rest_seconds,
                "notes": ex.notes,
                "target_muscle": ex.target_muscle
            }

        generated_at = (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        return {
            "plan_id": plan.plan_id,
            "user_id": plan.user_id,
            "date": plan.date,
            "workout_type": plan.workout_type,
            "estimated_duration_minutes": plan.estimated_duration_minutes,
            "phases": sanitize_workout_phases({
                "warm_up": [exercise_to_dict(ex) for ex in plan.warm_up],
                "activation": [exercise_to_dict(ex) for ex in plan.activation],
                "main_lifts": [exercise_to_dict(ex) for ex in plan.main_lifts],
                "accessories": [exercise_to_dict(ex) for ex in plan.accessories],
                "cool_down": [exercise_to_dict(ex) for ex in plan.cool_down]
            }),
            "safety_notes": plan.safety_notes,
            "generated_at": generated_at,
            "generator_version": generator_version,
        }

    @staticmethod
    def _plan_from_json(data: Dict[str, Any]) -> WorkoutPlan:
        """Create a WorkoutPlan instance from a JSON-like dict.

        The expected structure matches export_plan_as_json output and
        the API response schema used in main.py.
        """

        def dict_to_ex(ex: Dict[str, Any]) -> PlannedExercise:
            return PlannedExercise(
                name=ex.get("name", "Unknown"),
                sets=ex.get("sets", 0),
                reps=ex.get("reps", ""),
                rest_seconds=ex.get("rest_seconds", 0),
                notes=ex.get("notes"),
                target_muscle=ex.get("target_muscle"),
            )

        phases = data.get("phases", {})
        safe_pool = list(guided_exercise_names())
        if isinstance(phases, dict):
            phases = sanitize_workout_phases(phases, safe_pool)

        return WorkoutPlan(
            plan_id=data.get("plan_id", "plan_unknown"),
            user_id=data.get("user_id", "unknown"),
            date=data.get("date", "2026-01-01"),
            workout_type=data.get("workout_type", "full_body"),
            estimated_duration_minutes=data.get("estimated_duration_minutes", 45),
            warm_up=[dict_to_ex(ex) for ex in phases.get("warm_up", [])],
            activation=[dict_to_ex(ex) for ex in phases.get("activation", [])],
            main_lifts=[dict_to_ex(ex) for ex in phases.get("main_lifts", [])],
            accessories=[dict_to_ex(ex) for ex in phases.get("accessories", [])],
            cool_down=[dict_to_ex(ex) for ex in phases.get("cool_down", [])],
            safety_notes=data.get("safety_notes", []),
        )


# =============================================================================
# VERIFICATION FUNCTIONS
# =============================================================================

def verify_plan_safety(
    plan: WorkoutPlan,
    forbidden_exercises: List[ForbiddenExercise]
) -> bool:
    """
    Verify that the generated plan does not contain any forbidden exercises.
    
    This is a critical safety check that ensures the Risk Assessment Engine's
    constraints are properly respected.
    
    Args:
        plan: Generated workout plan
        forbidden_exercises: List of exercises that should be avoided
        
    Returns:
        True if plan is safe, False otherwise
    """
    forbidden_names = {ex.name.lower() for ex in forbidden_exercises}
    
    all_plan_exercises = (
        [ex.name for ex in plan.main_lifts] +
        [ex.name for ex in plan.accessories]
    )
    
    violations = []
    for ex_name in all_plan_exercises:
        if ex_name.lower() in forbidden_names:
            violations.append(ex_name)
    
    if violations:
        print(f"\n❌ SAFETY VIOLATION: Plan contains forbidden exercises!")
        for v in violations:
            print(f"   - {v}")
        return False
    else:
        print(f"\n✅ SAFETY VERIFIED: No forbidden exercises in the plan.")
        return True


# =============================================================================
# MAIN EXECUTION - Demo Scenario
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🏋️ ADAPTIVE ATHLETIC TRAINING SYSTEM - Plan Generator Demo")
    print("="*70)
    
    try:
        # 1. Initialize the Risk Assessment Engine
        print("\n📦 Initializing Risk Assessment Engine...")
        risk_engine = RiskAssessmentEngine(db_path='exercise_db.json')
        
        # 2. Initialize the Plan Generator (LLM 或 Mock)
        use_llm_env = os.getenv("USE_REAL_LLM", "false").lower()
        use_llm = use_llm_env in ("1", "true", "yes")
        mode_label = "LLM" if use_llm else "Mock"
        print(f"📦 Initializing Plan Generator ({mode_label} Mode)...")
        plan_generator = PlanGeneratorMock(risk_engine, use_llm=use_llm)
        
        # 3. Load user profile
        print("\n📁 Loading user profile...")
        try:
            with open('user_profile.json', 'r', encoding='utf-8') as f:
                user_profile = json.load(f)
            print(f"   ✅ Loaded: {user_profile.get('user_id')}")
        except FileNotFoundError:
            print("   ⚠️ user_profile.json not found, using default.")
            user_profile = {
                "user_id": "demo_user",
                "fitness_level": "intermediate",
                "medical_history": []
            }
        
        # 4. Load feedback input
        print("\n📁 Loading feedback input...")
        try:
            with open('feedback_input.json', 'r', encoding='utf-8') as f:
                feedback_input = json.load(f)
            print(f"   ✅ Loaded: {feedback_input.get('session_id')}")
        except FileNotFoundError:
            print("   ⚠️ feedback_input.json not found, proceeding without feedback.")
            feedback_input = None
        
        # 5. Generate the workout plan
        workout_plan = plan_generator.generate_plan(
            user_profile=user_profile,
            feedback_input=feedback_input,
            workout_type="full_body"
        )
        
        # 6. Verify plan safety
        print("\n" + "="*70)
        print("🔒 SAFETY VERIFICATION")
        print("="*70)
        forbidden, _ = risk_engine.analyze_static_risk(user_profile)
        is_safe = verify_plan_safety(workout_plan, forbidden)
        
        # 7. Render and display the plan
        print("\n" + "="*70)
        print("📋 FINAL WORKOUT PLAN OUTPUT")
        print("="*70)
        
        rendered_plan = plan_generator.render_plan_as_text(workout_plan)
        print(rendered_plan)
        
        # 8. Export as JSON (for API/database)
        print("\n" + "="*70)
        print("📤 JSON EXPORT (for API/Database)")
        print("="*70)
        
        json_export = plan_generator.export_plan_as_json(workout_plan)
        print(json.dumps(json_export, indent=2, ensure_ascii=False))
        
        print("\n" + "="*70)
        print("✅ DEMO COMPLETED SUCCESSFULLY")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
