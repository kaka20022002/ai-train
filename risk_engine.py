"""
Risk Assessment Engine for Adaptive Athletic Training System
=============================================================

This module implements a rule-based risk assessment engine that analyzes
user injury profiles and workout feedback to generate safety constraints
for an AI-powered fitness recommendation system.

Author: Master's Thesis Project - Adaptive Athletic Risk Assessment System
Date: 2026-03-04

Core Concepts:
1. Static Risk Analysis: Pre-session filtering based on chronic injuries
2. Dynamic Risk Analysis: Post-session adaptation based on acute feedback
"""

import json
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class SeverityLevel(Enum):
    """Injury severity classification based on clinical guidelines."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ForbiddenExercise:
    """Data class representing an exercise that should be avoided."""
    name: str
    reason: str
    involved_joints: List[str]
    risk_level: int
    substitution: str


@dataclass
class RiskConstraint:
    """Data class representing a training constraint for the LLM generator."""
    constraint_type: str  # "intensity", "exclusion", "modification"
    description: str
    priority: int  # 1 = Critical, 2 = High, 3 = Medium
    affected_joints: Optional[List[str]] = None


class RiskAssessmentEngine:
    """
    Risk Assessment Engine for filtering exercises based on injury history
    and workout feedback.
    
    The engine implements a two-phase risk assessment approach:
    
    Phase 1 - Static Risk Analysis:
        Analyzes the user's chronic injury history to identify exercises
        that pose inherent risks based on joint involvement and injury severity.
        
    Phase 2 - Dynamic Risk Analysis:
        Analyzes real-time workout feedback (RPE, pain reports) to generate
        adaptive constraints for the next training session.
    
    Attributes:
        exercise_db (List[Dict]): The loaded exercise knowledge base
        
    Risk Logic References:
        - ACL injuries: Avoid high-load knee flexion exercises (risk_level >= 3)
        - Rotator cuff: Avoid overhead movements and internal rotation under load
        - Lumbar issues: Avoid spinal flexion under load, prioritize neutral spine
    """
    
    # Risk thresholds based on sports medicine guidelines
    HIGH_SEVERITY_THRESHOLD = 3  # Exercises with risk_level >= 3 are dangerous for high-severity injuries
    MEDIUM_SEVERITY_THRESHOLD = 4  # Exercises with risk_level >= 4 are dangerous for medium-severity injuries
    
    # RPE (Rate of Perceived Exertion) thresholds based on Borg Scale adaptation
    RPE_OVEREXERTION_THRESHOLD = 8  # Above this indicates excessive fatigue
    RPE_UNDEREXERTION_THRESHOLD = 4  # Below this indicates insufficient stimulus
    
    # Intensity adjustment percentages
    INTENSITY_REDUCTION_PERCENT = 20
    INTENSITY_INCREASE_PERCENT = 10
    
    def __init__(self, db_path: str = 'exercise_db.json') -> None:
        """
        Initialize the Risk Assessment Engine by loading the exercise database.
        
        Args:
            db_path: Path to the exercise database JSON file.
            
        Raises:
            FileNotFoundError: If the database file doesn't exist.
            json.JSONDecodeError: If the database file contains invalid JSON.
        """
        self.exercise_db: List[Dict[str, Any]] = []
        self._load_database(db_path)
    
    def _load_database(self, db_path: str) -> None:
        """
        Load and validate the exercise database.
        
        Args:
            db_path: Path to the exercise database JSON file.
        """
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                self.exercise_db = json.load(f)
            
            # Validate database structure
            if not isinstance(self.exercise_db, list):
                raise ValueError("Exercise database must be a JSON array")
            
            print(f"✅ Knowledge Base Loaded: {len(self.exercise_db)} exercises.")
            
        except FileNotFoundError:
            print(f"❌ Error: {db_path} not found.")
            raise
        except json.JSONDecodeError as e:
            print(f"❌ Error: Invalid JSON in {db_path}: {e}")
            raise
    
    def analyze_static_risk(self, user_profile: Dict[str, Any]) -> Tuple[List[ForbiddenExercise], List[str]]:
        """
        Perform static risk analysis based on user's chronic injury history.
        
        This method implements a rule-based filtering algorithm that matches
        user injuries against exercise joint requirements. The algorithm considers:
        
        1. Joint Matching: If an exercise involves a joint where the user has an injury
        2. Severity Gating: Different severity levels trigger different risk thresholds
           - HIGH severity: Block all exercises involving the affected joint (risk_level >= 3)
           - MEDIUM severity: Block only high-risk exercises (risk_level >= 4)
           - LOW severity: Allow with caution (logged but not blocked)
        
        Clinical Rationale:
        - High-severity injuries (e.g., acute tears, herniations) require complete
          avoidance of loaded movements through the affected joint
        - Medium-severity injuries allow low-impact alternatives
        - Low-severity injuries may only require form modifications
        
        Args:
            user_profile: User profile dictionary containing 'medical_history' list
            
        Returns:
            Tuple containing:
                - List of ForbiddenExercise objects (exercises to avoid)
                - List of safe exercise names (exercises that passed filtering)
        """
        user_id = user_profile.get('user_id', 'Unknown')
        medical_history = user_profile.get('medical_history', [])

        # Equipment gating (Sprint 3): if the user declared the equipment they
        # have access to, exclude exercises that require unavailable equipment.
        # When the field is absent/empty we assume full equipment access, keeping
        # backward compatibility with existing profiles.
        equipment_set = self._build_equipment_set(user_profile.get('available_equipment'))

        forbidden_exercises: List[ForbiddenExercise] = []
        safe_exercises: List[str] = []
        equipment_filtered: List[str] = []
        
        print(f"\n{'='*60}")
        print(f"📋 STATIC RISK ANALYSIS - User: {user_id}")
        print(f"{'='*60}")
        print(f"📊 Medical History Entries: {len(medical_history)}")
        
        # Build a mapping of injured joints to their severity levels
        # This allows efficient lookup during exercise iteration
        injury_map: Dict[str, Dict[str, Any]] = {}
        for injury in medical_history:
            location = injury.get('location', '').lower()
            severity = injury.get('severity', 'low').lower()
            condition = injury.get('condition', 'unknown')
            pain_trigger = injury.get('pain_trigger', 'unknown')
            
            # Store the most severe injury for each location
            if location not in injury_map or self._compare_severity(severity, injury_map[location]['severity']) > 0:
                injury_map[location] = {
                    'severity': severity,
                    'condition': condition,
                    'pain_trigger': pain_trigger
                }
        
        print(f"🔍 Identified Injury Locations: {list(injury_map.keys())}")
        
        # Iterate through each exercise and check against injury map
        for exercise in self.exercise_db:
            exercise_name = exercise.get('name', 'Unknown')
            involved_joints = [j.lower() for j in exercise.get('involved_joints', [])]
            risk_level = exercise.get('risk_level', 1)
            substitution = exercise.get('substitution', 'Rest or consult physiotherapist')
            
            is_forbidden = False
            risk_reason = ""
            
            # Check each joint involved in the exercise
            for joint in involved_joints:
                if joint in injury_map:
                    injury_info = injury_map[joint]
                    severity = injury_info['severity']
                    condition = injury_info['condition']
                    
                    # Apply severity-based risk gating
                    # HIGH severity: Block if exercise risk_level >= 3
                    if severity == SeverityLevel.HIGH.value and risk_level >= self.HIGH_SEVERITY_THRESHOLD:
                        is_forbidden = True
                        risk_reason = (
                            f"HIGH-RISK: {joint.upper()} has {condition} (severity: HIGH). "
                            f"Exercise risk level ({risk_level}) exceeds safe threshold."
                        )
                        break
                    
                    # MEDIUM severity: Block if exercise risk_level >= 4
                    elif severity == SeverityLevel.MEDIUM.value and risk_level >= self.MEDIUM_SEVERITY_THRESHOLD:
                        is_forbidden = True
                        risk_reason = (
                            f"MODERATE-RISK: {joint.upper()} has {condition} (severity: MEDIUM). "
                            f"Exercise is high-intensity (risk level {risk_level})."
                        )
                        break
                    
                    # LOW severity: Log but don't block (could add to warnings)
                    elif severity == SeverityLevel.LOW.value and risk_level >= 5:
                        is_forbidden = True
                        risk_reason = (
                            f"CAUTION: {joint.upper()} has {condition} (severity: LOW). "
                            f"Exercise is maximum intensity (risk level {risk_level})."
                        )
                        break
            
            if is_forbidden:
                forbidden_exercises.append(ForbiddenExercise(
                    name=exercise_name,
                    reason=risk_reason,
                    involved_joints=involved_joints,
                    risk_level=risk_level,
                    substitution=substitution
                ))
                continue

            # Equipment gating — exercise is injury-safe but may need equipment
            # the user doesn't have. Excluded from the safe pool (not "forbidden",
            # since it is not a safety issue).
            if equipment_set is not None:
                required = [e.lower() for e in exercise.get('required_equipment', [])]
                if required and not all(r in equipment_set for r in required):
                    equipment_filtered.append(exercise_name)
                    continue

            safe_exercises.append(exercise_name)
        
        # Print summary
        print(f"\n🚫 Forbidden Exercises: {len(forbidden_exercises)}")
        if equipment_set is not None:
            print(f"🛠️  Equipment-filtered (unavailable gear): {len(equipment_filtered)}")
        print(f"✅ Safe Exercises: {len(safe_exercises)}")
        
        return forbidden_exercises, safe_exercises

    @staticmethod
    def _build_equipment_set(available_equipment: Optional[List[str]]) -> Optional[set]:
        """
        Normalise the user's available equipment into a lookup set.

        Returns None when the user did not specify any equipment (→ no filtering,
        assume full access). Otherwise returns a lowercase set that always
        implicitly includes 'bodyweight'.
        """
        if not available_equipment:
            return None
        equipment_set = {e.lower() for e in available_equipment if e}
        if not equipment_set:
            return None
        equipment_set.add('bodyweight')  # bodyweight movements are always doable
        return equipment_set
    
    def analyze_dynamic_feedback(self, feedback_input: Dict[str, Any]) -> List[RiskConstraint]:
        """
        Perform dynamic risk analysis based on post-workout feedback.
        
        This method analyzes real-time feedback to generate adaptive constraints
        for the LLM-based workout generator. The algorithm considers:
        
        1. RPE (Rate of Perceived Exertion) Analysis:
           - RPE > 8: User is overexerted → Reduce intensity
           - RPE < 4: User is underexerted → Increase challenge
           - RPE 4-8: Optimal training zone → No adjustment needed
           
        2. Pain Feedback Analysis:
           - If pain reported: Generate exclusion constraints for affected area
           - Pain severity affects constraint priority
           
        3. Fatigue Feedback Analysis (if available):
           - High overall fatigue: Suggest recovery session
           - Poor sleep quality: Reduce volume
        
        Physiological Rationale:
        - RPE is a validated measure of training load (Foster et al., 2001)
        - Pain during exercise indicates potential tissue damage
        - Accumulated fatigue increases injury risk
        
        Args:
            feedback_input: Feedback dictionary containing 'rpe', 'pain_feedback', etc.
            
        Returns:
            List of RiskConstraint objects for the LLM generator
        """
        session_id = feedback_input.get('session_id', 'Unknown')
        user_id = feedback_input.get('user_id', 'Unknown')
        
        constraints: List[RiskConstraint] = []
        
        print(f"\n{'='*60}")
        print(f"📊 DYNAMIC FEEDBACK ANALYSIS - Session: {session_id}")
        print(f"{'='*60}")
        
        # === RPE Analysis ===
        rpe = feedback_input.get('rpe', 5)
        print(f"💪 RPE Score: {rpe}/10")
        
        if rpe > self.RPE_OVEREXERTION_THRESHOLD:
            # User is overexerted - need to reduce intensity
            constraints.append(RiskConstraint(
                constraint_type="intensity",
                description=(
                    f"REDUCE INTENSITY: User reported RPE {rpe}/10 (overexertion threshold: {self.RPE_OVEREXERTION_THRESHOLD}). "
                    f"Decrease training intensity by {self.INTENSITY_REDUCTION_PERCENT}% for next session. "
                    f"Consider: fewer sets, lighter weights, or longer rest periods."
                ),
                priority=2  # High priority
            ))
            print(f"   ⚠️  Overexertion detected - recommending {self.INTENSITY_REDUCTION_PERCENT}% intensity reduction")
            
        elif rpe < self.RPE_UNDEREXERTION_THRESHOLD:
            # User is underexerted - can increase challenge
            constraints.append(RiskConstraint(
                constraint_type="intensity",
                description=(
                    f"INCREASE INTENSITY: User reported RPE {rpe}/10 (underexertion threshold: {self.RPE_UNDEREXERTION_THRESHOLD}). "
                    f"Implement progressive overload: increase weight by {self.INTENSITY_INCREASE_PERCENT}% "
                    f"or add 1-2 reps per set."
                ),
                priority=3  # Medium priority
            ))
            print(f"   📈 Underexertion detected - recommending progressive overload")
        else:
            print(f"   ✅ RPE in optimal zone (4-8)")
        
        # === Pain Feedback Analysis ===
        pain_feedback = feedback_input.get('pain_feedback', {})
        has_pain = pain_feedback.get('has_pain', False)
        
        if has_pain:
            # 注意：feedback 往往来自 Pydantic 的 model_dump()，未填写的字段会
            # 以 None 而非「缺键」的形式出现。用 .get(k, default) 兜不住这种情况，
            # 必须用 `or` —— 否则 pain_location 为 None 时 .upper() 会抛
            # AttributeError，把整个 /generate_plan 打成 500。
            pain_location = pain_feedback.get('pain_location') or 'unknown'
            pain_severity = pain_feedback.get('pain_severity') or 0
            trigger_exercise = pain_feedback.get('trigger_exercise') or 'Unknown'
            pain_type = pain_feedback.get('pain_type') or 'unspecified'
            
            print(f"🩹 Pain Reported: {pain_location.upper()}")
            print(f"   Severity: {pain_severity}/10")
            print(f"   Type: {pain_type}")
            print(f"   Trigger: {trigger_exercise}")
            
            # Determine constraint priority based on pain severity
            if pain_severity >= 7:
                priority = 1  # Critical
                action = "IMMEDIATELY EXCLUDE"
            elif pain_severity >= 4:
                priority = 2  # High
                action = "EXCLUDE"
            else:
                priority = 3  # Medium
                action = "MODIFY OR REDUCE LOAD"
            
            constraints.append(RiskConstraint(
                constraint_type="exclusion",
                description=(
                    f"{action}: User reported {pain_type} pain (severity {pain_severity}/10) "
                    f"in {pain_location.upper()} during '{trigger_exercise}'. "
                    f"Exclude all exercises heavily involving the {pain_location} joint for the next session. "
                    f"If pain persists, recommend medical consultation."
                ),
                priority=priority,
                affected_joints=[pain_location.lower()]
            ))
            
            # Add specific exercise exclusion
            constraints.append(RiskConstraint(
                constraint_type="exclusion",
                description=(
                    f"SPECIFIC EXCLUSION: Remove '{trigger_exercise}' from the next workout plan. "
                    f"This exercise directly triggered pain response."
                ),
                priority=priority,
                affected_joints=[pain_location.lower()]
            ))
        else:
            print(f"🩹 Pain Feedback: None reported ✅")
        
        # === Fatigue Feedback Analysis (Extended) ===
        fatigue_feedback = feedback_input.get('fatigue_feedback', {})
        # 同样要防 None：疲劳/睡眠字段留空时 model_dump() 会给 None，
        # 直接拿去做数值比较会抛 TypeError。
        if fatigue_feedback and any(
            fatigue_feedback.get(k) is not None
            for k in ('overall_fatigue', 'sleep_quality_last_night')
        ):
            overall_fatigue = fatigue_feedback.get('overall_fatigue') or 5
            sleep_quality = fatigue_feedback.get('sleep_quality_last_night') or 7
            
            print(f"😴 Fatigue Level: {overall_fatigue}/10")
            print(f"💤 Sleep Quality: {sleep_quality}/10")
            
            # High fatigue with poor sleep = increased injury risk
            if overall_fatigue >= 8 and sleep_quality <= 4:
                constraints.append(RiskConstraint(
                    constraint_type="modification",
                    description=(
                        f"RECOVERY RECOMMENDATION: User shows high fatigue ({overall_fatigue}/10) "
                        f"combined with poor sleep ({sleep_quality}/10). "
                        f"Consider: Active recovery session, mobility work, or rest day."
                    ),
                    priority=2
                ))
                print(f"   ⚠️  High fatigue + poor sleep - recommending recovery focus")
        
        # Print summary
        print(f"\n📋 Generated Constraints: {len(constraints)}")
        
        return constraints
    
    def _compare_severity(self, sev1: str, sev2: str) -> int:
        """
        Compare two severity levels.
        
        Args:
            sev1: First severity level
            sev2: Second severity level
            
        Returns:
            1 if sev1 > sev2, -1 if sev1 < sev2, 0 if equal
        """
        severity_order = {'low': 1, 'medium': 2, 'high': 3}
        s1 = severity_order.get(sev1.lower(), 0)
        s2 = severity_order.get(sev2.lower(), 0)
        
        if s1 > s2:
            return 1
        elif s1 < s2:
            return -1
        return 0
    
    def generate_llm_prompt_constraints(
        self, 
        forbidden_exercises: List[ForbiddenExercise], 
        constraints: List[RiskConstraint]
    ) -> str:
        """
        Generate a formatted constraint block for the LLM workout generator.
        
        This method converts the structured risk analysis output into a
        natural language prompt that can be prepended to the LLM's
        workout generation instructions.
        
        Args:
            forbidden_exercises: List of exercises to avoid
            constraints: List of dynamic constraints
            
        Returns:
            Formatted string for LLM prompt injection
        """
        prompt_lines = [
            "=" * 60,
            "🛡️ SAFETY CONSTRAINTS FOR WORKOUT GENERATION",
            "=" * 60,
            "",
            "The following constraints MUST be respected when generating the workout plan:",
            ""
        ]
        
        # Add forbidden exercises
        if forbidden_exercises:
            prompt_lines.append("## FORBIDDEN EXERCISES (Do NOT include these):")
            for i, ex in enumerate(forbidden_exercises, 1):
                prompt_lines.append(f"  {i}. {ex.name}")
                prompt_lines.append(f"     Reason: {ex.reason}")
                prompt_lines.append(f"     Substitute with: {ex.substitution}")
                prompt_lines.append("")
        
        # Add dynamic constraints sorted by priority
        if constraints:
            prompt_lines.append("## DYNAMIC CONSTRAINTS (Apply these rules):")
            sorted_constraints = sorted(constraints, key=lambda x: x.priority)
            for i, c in enumerate(sorted_constraints, 1):
                priority_label = {1: "🔴 CRITICAL", 2: "🟠 HIGH", 3: "🟡 MEDIUM"}.get(c.priority, "⚪")
                prompt_lines.append(f"  {i}. [{priority_label}] {c.description}")
                prompt_lines.append("")
        
        prompt_lines.append("=" * 60)
        
        return "\n".join(prompt_lines)


# =============================================================================
# MAIN EXECUTION BLOCK - Verification and Testing
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🏋️ ADAPTIVE ATHLETIC RISK ASSESSMENT SYSTEM - Engine Test")
    print("="*70)
    
    try:
        # 1. Initialize the Risk Assessment Engine
        engine = RiskAssessmentEngine(db_path='exercise_db.json')
        
        # 2. Load user profile
        print("\n📁 Loading user profile...")
        try:
            with open('user_profile.json', 'r', encoding='utf-8') as f:
                user_profile = json.load(f)
            print(f"   ✅ Loaded profile for user: {user_profile.get('user_id', 'Unknown')}")
        except FileNotFoundError:
            print("   ❌ user_profile.json not found. Using sample data.")
            user_profile = {
                "user_id": "test_user",
                "medical_history": [
                    {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
                ]
            }
        
        # 3. Load feedback input
        print("\n📁 Loading feedback input...")
        try:
            with open('feedback_input.json', 'r', encoding='utf-8') as f:
                feedback_input = json.load(f)
            print(f"   ✅ Loaded feedback for session: {feedback_input.get('session_id', 'Unknown')}")
        except FileNotFoundError:
            print("   ❌ feedback_input.json not found. Using sample data.")
            feedback_input = {
                "session_id": "test_session",
                "rpe": 9,
                "pain_feedback": {"has_pain": True, "pain_location": "knee", "pain_severity": 6, "trigger_exercise": "Squat"}
            }
        
        # 4. Run Static Risk Analysis
        forbidden_exercises, safe_exercises = engine.analyze_static_risk(user_profile)
        
        # 5. Run Dynamic Feedback Analysis
        constraints = engine.analyze_dynamic_feedback(feedback_input)
        
        # 6. Generate LLM Prompt
        llm_prompt = engine.generate_llm_prompt_constraints(forbidden_exercises, constraints)
        
        # 7. Print Final Output
        print("\n" + "="*70)
        print("📤 FINAL OUTPUT - LLM PROMPT CONSTRAINTS")
        print("="*70)
        print(llm_prompt)
        
        # 8. Print detailed reports
        print("\n" + "="*70)
        print("📊 DETAILED REPORTS")
        print("="*70)
        
        print("\n🚫 FORBIDDEN EXERCISES DETAIL:")
        print("-" * 40)
        for ex in forbidden_exercises:
            print(f"  ❌ {ex.name}")
            print(f"     Risk Level: {ex.risk_level}/5")
            print(f"     Joints: {', '.join(ex.involved_joints)}")
            print(f"     Reason: {ex.reason}")
            print(f"     Substitute: {ex.substitution}")
            print()
        
        print("\n✅ SAFE EXERCISES:")
        print("-" * 40)
        for i, ex in enumerate(safe_exercises, 1):
            print(f"  {i:2d}. {ex}")
        
        print("\n" + "="*70)
        print("✅ ENGINE TEST COMPLETED SUCCESSFULLY")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ ENGINE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()