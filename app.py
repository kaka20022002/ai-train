"""自适应运动风险评估系统 — 可视化测试界面

运行方法：
    cd "/Users/wyh/Downloads/06_代码项目/ai-train"
    streamlit run app.py
"""

import json
import os
import sys
import time
import traceback

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

# ── 自动加载 .env 内置配置 ───────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
except ImportError:
    pass

from risk_engine import RiskAssessmentEngine
from plan_generator_mock import PlanGeneratorMock
from exercise_meta import image_url as ex_image_url, technique_cn as ex_technique_cn


# ═══════════════════════════════════════════════════════════════════════════════
# 系统级 LLM 预设（从 .env 加载，无需用户输入）
# ═══════════════════════════════════════════════════════════════════════════════
LLM_CONFIGURED = bool(
    os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")
) and os.getenv("LLM_PROVIDER", "").lower() == "minimax_anthropic"

SYS_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")


# ═══════════════════════════════════════════════════════════════════════════════
# 中英文翻译字典
# ═══════════════════════════════════════════════════════════════════════════════
EXERCISE_CN = {
    "Arnold Press": "阿诺德推举",
    "Back Extension": "背部伸展",
    "Barbell Back Squat": "杠铃深蹲",
    "Barbell Bench Press": "杠铃卧推",
    "Barbell Curl": "杠铃弯举",
    "Barbell Row": "杠铃划船",
    "Bulgarian Split Squat": "保加利亚分腿蹲",
    "Cable Crossover": "绳索夹胸",
    "Calf Raise": "提踵",
    "Conventional Deadlift": "传统硬拉",
    "Crunch": "仰卧卷腹",
    "Dumbbell Fly": "哑铃飞鸟",
    "Dumbbell Hammer Curl": "哑铃锤式弯举",
    "Dumbbell Shrug": "哑铃耸肩",
    "Face Pull": "面拉",
    "Front Squat": "前蹲",
    "Good Morning": "早安式",
    "Hanging Leg Raise": "悬挂举腿",
    "Hip Thrust": "臀冲",
    "Incline Dumbbell Press": "上斜哑铃推举",
    "Lat Pulldown": "高位下拉",
    "Lateral Raise": "侧平举",
    "Leg Curl": "腿弯举",
    "Leg Extension": "腿屈伸",
    "Leg Press": "腿举",
    "Overhead Press": "过顶推举",
    "Plank": "平板支撑",
    "Preacher Curl": "牧师凳弯举",
    "Pull-Up": "引体向上",
    "Push-Up": "俯卧撑",
    "Romanian Deadlift": "罗马尼亚硬拉",
    "Russian Twist": "俄罗斯转体",
    "Seated Cable Row": "坐姿绳索划船",
    "Skull Crusher": "仰卧臂屈伸",
    "Sumo Deadlift": "相扑硬拉",
    "T-Bar Row": "T杠划船",
    "Tricep Dip": "双杠臂屈伸",
    "Tricep Pushdown": "绳索下压",
    "Walking Lunge": "行进弓步蹲",
    "Wrist Curl": "腕屈伸",
    # 热身/激活/冷身动作
    "Light Treadmill Walk": "轻松跑步机走",
    "Jumping Jacks": "开合跳",
    "Arm Circles": "绕臂",
    "Leg Swings": "摆腿",
    "Hip Circles": "绕髋",
    "Cat-Cow Stretch": "猫牛式伸展",
    "Bodyweight Good Morning": "徒手早安式",
    "Glute Bridge": "臀桥",
    "Bird Dog": "鸟狗式",
    "Dead Bug": "死虫式",
    "Band Pull-Apart": "弹力带拉开",
    "Clamshells": "贝壳式",
    "Scapular Push-Ups": "肩胛俯卧撑",
    "Static Quad Stretch": "股四头肌静态拉伸",
    "Hamstring Stretch": "腘绳肌拉伸",
    "Chest Doorway Stretch": "门框胸部拉伸",
    "Child's Pose": "婴儿式",
    "Supine Twist": "仰卧脊柱扭转",
    "Foam Rolling - Full Body": "全身泡沫轴放松",
}

MUSCLE_CN = {
    "Biceps Brachii": "肱二头肌",
    "Brachialis": "肱肌",
    "Deltoids": "三角肌",
    "Erector Spinae": "竖脊肌",
    "Forearm Flexors": "前臂屈肌",
    "Gastrocnemius": "腓肠肌",
    "Gluteus Maximus": "臀大肌",
    "Hamstrings": "腘绳肌",
    "Latissimus Dorsi": "背阔肌",
    "Obliques": "腹斜肌",
    "Pectorals": "胸大肌",
    "Quadriceps": "股四头肌",
    "Rear Deltoids": "三角肌后束",
    "Rectus Abdominis": "腹直肌",
    "Rhomboids": "菱形肌",
    "Trapezius": "斜方肌",
    "Triceps Brachii": "肱三头肌",
    "Multiple": "多肌群",
    "N/A": "—",
    "": "—",
}

# 常见英文 notes 片段中译
NOTE_CN = {
    "RPE 3-4": "强度 RPE 3-4（轻松）",
    "Low impact": "低冲击",
    "Spinal mobility": "脊柱灵活性",
    "Hamstring activation": "腘绳肌激活",
    "Squeeze at top": "顶点发力挤压",
    "Core stability": "核心稳定性",
    "Anti-extension": "抗伸展控制",
    "Rear delt activation": "三角肌后束激活",
    "Hip external rotation": "髋外旋",
    "Shoulder stability": "肩关节稳定",
    "Deep breathing": "配合深呼吸",
    "Focus on tight areas": "重点放松紧张部位",
}


def translate_notes(notes: str) -> str:
    """将 Mock 生成的英文备注翻译成中文；未命中则原样返回。"""
    if not notes:
        return ""
    # 'Risk Level: 3/5' 格式特殊处理
    if notes.startswith("Risk Level:"):
        lvl = notes.replace("Risk Level:", "").strip().split("/")[0]
        return f"动作风险等级 {lvl}/5 — 注意控制动作质量"
    return NOTE_CN.get(notes.strip(), notes)


def translate_safety_note(note: str) -> str:
    """翻译 Mock 生成器产生的英文安全提示。"""
    if not note:
        return note
    import re
    n = note
    n = re.sub(
        r"⚠️ (\d+) exercises have been excluded due to injury history\.",
        r"⚠️ 已根据伤病史排除 \1 个高风险动作。", n,
    )
    n = re.sub(
        r"📉 Volume has been reduced by 20% due to high RPE in previous session\.",
        "📉 因上次训练 RPE 偏高，本次训练量已下调约 20%。", n,
    )
    n = re.sub(
        r"🩹 Exercises involving ([A-Z, ]+) have been minimized due to acute pain\.",
        lambda m: f"🩹 因存在急性疼痛，已尽量减少涉及 {m.group(1)} 的动作。", n,
    )
    n = n.replace(
        "💡 Stop immediately if you experience sharp pain during any exercise.",
        "💡 训练中若出现剧烈疼痛应立即停止。",
    )
    n = n.replace(
        "💧 Stay hydrated and take extra rest between sets if needed.",
        "💧 注意补水，必要时适当延长组间休息。",
    )
    n = n.replace("🔴 CRITICAL:", "🔴 严重：").replace("🟠 IMPORTANT:", "🟠 重要：")
    return n


JOINT_CN = {
    "knee": "膝关节", "shoulder": "肩关节", "spine": "脊柱", "hip": "髋关节",
    "ankle": "踝关节", "wrist": "腕关节", "elbow": "肘关节", "neck": "颈椎",
    "hamstring": "腘绳肌", "quadriceps": "股四头肌",
}

TYPE_CN = {"Compound": "复合动作", "Isolation": "孤立动作", "Isometric": "等长动作"}

WORKOUT_TYPE_CN = {
    "full_body": "全身训练", "upper_body": "上肢训练", "lower_body": "下肢训练",
    "push": "推系训练", "pull": "拉系训练", "recovery": "恢复训练",
}

FITNESS_CN = {"beginner": "初级", "intermediate": "中级", "advanced": "高级"}
SEVERITY_CN = {"low": "轻度", "medium": "中度", "high": "重度"}
PAIN_TYPE_CN = {"sharp": "刺痛", "dull": "钝痛", "aching": "酸痛", "burning": "灼痛"}

CONSTRAINT_TYPE_CN = {
    "intensity": "强度调整",
    "volume": "训练量调整",
    "exercise_exclusion": "动作排除",
    "recovery": "恢复建议",
    "pain_management": "疼痛管理",
}


def ex_cn(name: str) -> str:
    return EXERCISE_CN.get(name, name)


def muscle_cn(name: str) -> str:
    return MUSCLE_CN.get(name, name) if name else "—"


def joint_cn(name: str) -> str:
    return JOINT_CN.get(name.lower(), name)


def joints_cn(joints) -> str:
    return "、".join(joint_cn(j) for j in joints)


def _phase_sets(exercises: list) -> int:
    return sum(int(ex.get("sets", 0) or 0) for ex in exercises)


# ═══════════════════════════════════════════════════════════════════════════════
# 页面配置与全局样式
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AI 运动风险评估系统",
    page_icon="🏋️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* 全局字体与文字色 */
html, body, [class*="css"], .stMarkdown, .stText {
    color: #f1f5f9 !important;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei",
                 "Helvetica Neue", Helvetica, Arial, sans-serif;
}

/* 头部横幅 —— 扁平化 */
.app-header {
    background: #1a1f2e;
    padding: 22px 28px;
    border-radius: 12px;
    margin-bottom: 22px;
    border-left: 4px solid #8b5cf6;
}
.app-header h1 {
    margin: 0;
    font-size: 1.6rem;
    font-weight: 600;
    color: #f1f5f9;
    letter-spacing: 0.02em;
}
.app-header p {
    margin: 6px 0 0 0;
    color: #94a3b8;
    font-size: 0.92rem;
}

/* 状态徽章 */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 6px;
    font-size: 0.88rem;
    font-weight: 500;
    margin-bottom: 10px;
    border: 1px solid transparent;
}
.status-llm  { background: rgba(16,185,129,0.12); color: #34d399; border-color: rgba(16,185,129,0.3); }
.status-mock { background: rgba(100,116,139,0.15); color: #cbd5e1; border-color: rgba(100,116,139,0.3); }
.status-fail { background: rgba(245,158,11,0.12); color: #fbbf24; border-color: rgba(245,158,11,0.3); }

/* 阶段标题（仅在 tabs 外时使用） */
.phase-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-right: 8px;
}

/* 动作卡：图文双栏 */
.ex-card {
    background: #151b2b;
    border-radius: 10px;
    padding: 18px;
    margin-bottom: 14px;
    border: 1px solid #2a334a;
}
.ex-title {
    font-size: 1.15rem;
    font-weight: 600;
    color: #f1f5f9;
    margin: 0 0 4px 0;
}
.ex-subtitle {
    color: #94a3b8;
    font-size: 0.85rem;
    margin-bottom: 12px;
    font-style: italic;
}
.ex-params-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}
.chip {
    display: inline-flex;
    align-items: center;
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 500;
    background: #1e2740;
    color: #cbd5e1;
    border: 1px solid #2d3a57;
}
.chip.sets   { background: #2a1f47; color: #c4b5fd; border-color: #4c3a7a; }
.chip.rest   { background: #0e2f3a; color: #67e8f9; border-color: #1e4757; }
.chip.muscle { background: #0f2e23; color: #6ee7b7; border-color: #1d4f3d; }

/* 教练要点框 */
.coach-box {
    background: rgba(139, 92, 246, 0.08);
    border-left: 3px solid #8b5cf6;
    padding: 10px 14px;
    border-radius: 6px;
    margin-bottom: 10px;
}
.coach-title {
    color: #a78bfa;
    font-weight: 600;
    font-size: 0.88rem;
    margin-bottom: 4px;
}
.coach-box p { color: #e2e8f0; margin: 0; font-size: 0.88rem; line-height: 1.55; }

/* 技术要领列表 */
.tech-box {
    background: #11192b;
    border-radius: 8px;
    padding: 12px 16px;
    border: 1px solid #2a334a;
}
.tech-title {
    color: #fbbf24;
    font-weight: 600;
    font-size: 0.88rem;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
}
.tech-step {
    display: flex;
    gap: 10px;
    padding: 6px 0;
    color: #e2e8f0;
    font-size: 0.88rem;
    line-height: 1.55;
    border-bottom: 1px dashed #2a334a;
}
.tech-step:last-child { border-bottom: none; }
.tech-step-num {
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #fbbf24;
    color: #111827;
    text-align: center;
    line-height: 22px;
    font-size: 0.78rem;
    font-weight: 700;
}

/* 图片占位 */
.img-placeholder {
    width: 100%;
    aspect-ratio: 4/3;
    background: #11192b;
    border: 1px dashed #2a334a;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #475569;
    font-size: 0.85rem;
}

/* 摘要指标卡 */
.metric-box {
    background: #151b2b;
    border: 1px solid #2a334a;
    border-radius: 8px;
    padding: 14px 10px;
    text-align: center;
}
.metric-value { font-size: 1.85rem; font-weight: 700; line-height: 1; color: #f1f5f9; }
.metric-label { font-size: 0.78rem; color: #94a3b8; margin-top: 6px; }

/* 禁止动作行 */
.forbidden-row {
    background: rgba(239, 68, 68, 0.08);
    border-left: 3px solid #ef4444;
    padding: 10px 14px;
    border-radius: 6px;
    margin-bottom: 6px;
}
.forbidden-name   { color: #fca5a5; font-weight: 600; }
.forbidden-reason { color: #e2e8f0; font-size: 0.85rem; margin-top: 4px; }
.forbidden-sub    { color: #86efac; font-size: 0.85rem; margin-top: 3px; }

/* 约束条 */
.constraint-row {
    padding: 10px 14px; border-radius: 6px; margin-bottom: 6px;
    border-left: 3px solid #fbbf24; background: rgba(251, 191, 36, 0.06);
}
.constraint-row.priority-1 { border-left-color: #ef4444; background: rgba(239, 68, 68, 0.06); }
.constraint-row.priority-3 { border-left-color: #60a5fa; background: rgba(96, 165, 250, 0.06); }

/* 时间轴 */
.plan-timeline {
    display: flex; gap: 3px; margin: 12px 0 18px 0; height: 30px;
    border-radius: 6px; overflow: hidden; border: 1px solid #2a334a;
}
.timeline-seg {
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 0.78rem; font-weight: 600;
}

/* 系统状态条 */
.sys-status {
    padding: 10px 14px;
    background: rgba(16, 185, 129, 0.08);
    border: 1px solid rgba(16, 185, 129, 0.25);
    border-radius: 6px;
    margin-bottom: 12px;
    font-size: 0.85rem;
    color: #34d399;
}
.sys-status.warning {
    background: rgba(245, 158, 11, 0.08);
    border-color: rgba(245, 158, 11, 0.25);
    color: #fbbf24;
}

/* Streamlit tabs 文字颜色修正 */
.stTabs [data-baseweb="tab"] {
    color: #cbd5e1;
    font-weight: 500;
}
.stTabs [aria-selected="true"] {
    color: #c4b5fd !important;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 资源缓存
# ═══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def load_engine():
    db = os.path.join(os.path.dirname(__file__), "exercise_db.json")
    return RiskAssessmentEngine(db_path=db)


# ═══════════════════════════════════════════════════════════════════════════════
# 阶段元信息
# ═══════════════════════════════════════════════════════════════════════════════
_PHASE_META = {
    "warm_up":     {"cn": "🔥 热身阶段",   "desc": "提高体温、激活心肺", "color": "#f97316"},
    "activation":  {"cn": "⚡ 激活阶段",   "desc": "唤醒目标肌群",       "color": "#facc15"},
    "main_lifts":  {"cn": "💪 主项训练",   "desc": "复合动作为主",       "color": "#7c3aed"},
    "accessories": {"cn": "🎯 辅助训练",   "desc": "孤立动作为主",       "color": "#06b6d4"},
    "cool_down":   {"cn": "🧘 放松拉伸",   "desc": "降低心率、促进恢复",  "color": "#22c55e"},
}


def render_exercise_card(ex: dict, idx: int, phase_color: str):
    """渲染一个动作的完整卡片（图文双栏：左侧示意图 + 右侧详情）。"""
    name_en = ex.get("name", "") or ""
    name_cn = ex_cn(name_en)
    sets = ex.get("sets", "?")
    reps = ex.get("reps", "?")
    rest = ex.get("rest_seconds", 0) or 0
    rest_text = f"{rest} 秒" if rest > 0 else "无需休息"
    target = muscle_cn(ex.get("target_muscle", ""))
    notes = ex.get("notes") or ""
    notes_cn = translate_notes(notes) if notes else ""
    img = ex_image_url(name_en)
    tech = ex_technique_cn(name_en)

    col_img, col_info = st.columns([1, 2], gap="medium")

    # ── 左列：图片 ────────────────────────────────────────────
    with col_img:
        if img:
            st.image(img, use_container_width=True)
        else:
            st.markdown(
                f"<div class='img-placeholder'>暂无示意图</div>",
                unsafe_allow_html=True,
            )

    # ── 右列：信息 ────────────────────────────────────────────
    with col_info:
        # 标题
        title_html = (
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px'>"
            f"<span style='display:inline-flex;align-items:center;justify-content:center;"
            f"width:26px;height:26px;border-radius:50%;background:{phase_color};"
            f"color:#fff;font-size:0.8rem;font-weight:700'>{idx}</span>"
            f"<span class='ex-title'>{name_cn}</span>"
            f"</div>"
        )
        st.markdown(title_html, unsafe_allow_html=True)

        if name_cn != name_en and name_en:
            st.markdown(
                f"<div class='ex-subtitle'>{name_en}</div>",
                unsafe_allow_html=True,
            )

        # 参数芯片
        chips_html = (
            f"<div class='ex-params-row'>"
            f"<span class='chip sets'>组数 · {sets} × {reps}</span>"
            f"<span class='chip rest'>组间休息 · {rest_text}</span>"
        )
        if target and target != "—":
            chips_html += f"<span class='chip muscle'>目标 · {target}</span>"
        chips_html += "</div>"
        st.markdown(chips_html, unsafe_allow_html=True)

        # 教练要点（来自 LLM 的 notes 字段，动态生成）
        if notes_cn:
            st.markdown(
                f"<div class='coach-box'>"
                f"<div class='coach-title'>本次训练要点</div>"
                f"<p>{notes_cn}</p>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── 底部：动作标准技术要领（跨两列）────────────────────────
    if tech:
        steps_html = "".join(
            f"<div class='tech-step'>"
            f"<span class='tech-step-num'>{i}</span>"
            f"<span>{step}</span>"
            f"</div>"
            for i, step in enumerate(tech, 1)
        )
        st.markdown(
            f"<div class='tech-box'>"
            f"<div class='tech-title'>📘 标准动作要领</div>"
            f"{steps_html}"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_phase_tab(key: str, exercises: list):
    """在当前 tab 中渲染一个阶段的全部动作。"""
    meta = _PHASE_META.get(key, {"cn": key, "desc": "", "color": "#64748b"})
    color = meta["color"]

    if not exercises:
        st.info(f"本训练计划在「{meta['cn'].split(' ',1)[-1]}」阶段无动作安排。")
        return

    total_sets = _phase_sets(exercises)
    st.markdown(
        f"<div style='color:#94a3b8;font-size:0.88rem;margin:4px 0 16px 0'>"
        f"<span class='phase-badge' style='background:{color}20;color:{color}'>"
        f"{meta['cn'].split(' ',1)[-1]}</span>"
        f"{meta['desc']} · 共 {len(exercises)} 个动作 · {total_sets} 组"
        f"</div>",
        unsafe_allow_html=True,
    )

    for idx, ex in enumerate(exercises, 1):
        render_exercise_card(ex, idx, color)
        if idx < len(exercises):
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


def render_timeline(phases: dict):
    segs = []
    total_sets = 0
    for key in ("warm_up", "activation", "main_lifts", "accessories", "cool_down"):
        s = _phase_sets(phases.get(key, []))
        total_sets += s
        segs.append((key, s))

    if total_sets == 0:
        return

    html = '<div class="plan-timeline">'
    for key, s in segs:
        if s == 0:
            continue
        color = _PHASE_META[key]["color"]
        html += (
            f'<div class="timeline-seg" '
            f'style="flex:{s}; background:{color}">{s}</div>'
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════════════════
INJURY_LOCATIONS = ["knee", "shoulder", "spine", "hip", "ankle",
                    "wrist", "elbow", "neck", "hamstring", "quadriceps"]

CONDITION_EXAMPLES = {
    "knee": "meniscus_tear（半月板撕裂）/ acl_tear（前交叉韧带）/ patellar_tendonitis（髌腱炎）",
    "shoulder": "rotator_cuff_tear（肩袖撕裂）/ shoulder_impingement（肩峰撞击）",
    "spine": "lumbar_herniation（腰椎间盘突出）/ lumbar_radiculopathy（神经根病变）",
    "hip": "hip_labral_tear（髋唇撕裂）/ hip_impingement（髋关节撞击）",
    "ankle": "ankle_sprain（踝扭伤）/ achilles_tendonitis（跟腱炎）",
    "wrist": "wrist_sprain（腕扭伤）/ carpal_tunnel（腕管综合征）",
    "elbow": "tennis_elbow（网球肘）/ golfer_elbow（高尔夫球肘）",
    "neck": "cervical_strain（颈部拉伤）",
    "hamstring": "hamstring_tear（腘绳肌拉伤）",
    "quadriceps": "quadriceps_strain（股四头肌拉伤）",
}


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — 简化配置
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### ⚙️ 系统配置")
    st.divider()

    # 系统状态
    if LLM_CONFIGURED:
        st.markdown(f"""
        <div class="sys-status">
            <span>✅ <b>大模型已就绪</b></span>
        </div>
        """, unsafe_allow_html=True)
        st.caption(f"模型：`{SYS_MODEL}`")
        st.caption("端点：`api.minimaxi.com/anthropic`")
    else:
        st.markdown("""
        <div class="sys-status warning">
            <span>⚠️ <b>未配置大模型</b> — 将使用 Mock 模式</span>
        </div>
        """, unsafe_allow_html=True)
        st.caption("请检查项目根目录 `.env` 文件")

    st.divider()
    st.markdown("#### 🤖 生成方式")

    gen_mode = st.radio(
        "生成方式",
        ["🧠 大模型智能生成（推荐）", "📦 离线 Mock 模式（无需网络）"],
        index=0 if LLM_CONFIGURED else 1,
        label_visibility="collapsed",
        disabled=not LLM_CONFIGURED,
    )
    use_llm = gen_mode.startswith("🧠") and LLM_CONFIGURED

    st.divider()
    st.markdown("#### 🏋️ 训练类型")
    workout_type = st.selectbox(
        "训练类型",
        list(WORKOUT_TYPE_CN.keys()),
        format_func=lambda x: WORKOUT_TYPE_CN.get(x, x),
        label_visibility="collapsed",
    )

    st.divider()
    with st.expander("🔧 高级：自定义 API（可选）"):
        st.caption("若需覆盖默认配置，在此处填写；留空则使用系统内置。")
        custom_key = st.text_input("API 密钥", type="password", value="",
                                    placeholder="sk-cp-...（留空使用默认）")
        custom_model = st.text_input("模型名称", value="",
                                      placeholder="默认 MiniMax-M2.7")
        if custom_key:
            os.environ["ANTHROPIC_API_KEY"] = custom_key
        if custom_model:
            os.environ["MINIMAX_MODEL"] = custom_model

    st.divider()
    st.caption("🎓 自适应运动风险评估系统")
    st.caption("Master's Thesis Project")


# ═══════════════════════════════════════════════════════════════════════════════
# 主页头部
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="app-header">
    <h1>🏋️ AI 自适应运动风险评估系统</h1>
    <p>基于用户伤病史与训练反馈，智能生成安全、个性化、可立即执行的训练计划</p>
</div>
""", unsafe_allow_html=True)

st.info(
    "📢 **界面已升级**：完整功能已合并至 Next.js 统一前端 → "
    "[http://localhost:3000](http://localhost:3000)  "
    "（生成计划 / 风险分析 / 动作库 / AI 教练 / 仪表盘）。"
    "本 Streamlit 页面保留作备用演示。"
)

tab_gen, tab_risk, tab_db, tab_chat = st.tabs(
    ["📋 生成训练计划", "🔍 伤病风险分析", "📚 动作数据库", "💬 AI 教练对话"]
)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 生成训练计划
# ═══════════════════════════════════════════════════════════════════════════════
with tab_gen:
    col_input, col_result = st.columns([1, 1.35], gap="large")

    # ── 左列：输入 ──────────────────────────────────────────────────────────
    with col_input:
        st.markdown("### 👤 用户基本信息")

        c1, c2 = st.columns(2)
        user_id = c1.text_input("用户编号", value="user_001")
        fitness_level = c2.selectbox(
            "训练水平",
            list(FITNESS_CN.keys()),
            index=1,
            format_func=lambda x: FITNESS_CN.get(x, x),
            help="初级：训练经验 < 6 月；中级：6 月至 2 年；高级：> 2 年",
        )

        c3, c4, c5 = st.columns(3)
        age = c3.number_input("年龄（岁）", 16, 80, 28)
        weight = c4.number_input("体重（kg）", 40, 150, 75)
        height = c5.number_input("身高（cm）", 140, 220, 175)

        st.markdown("### 🩺 伤病史")
        st.caption("添加用户已有的伤病，系统将据此筛除高风险动作。")

        if "injuries" not in st.session_state:
            st.session_state.injuries = []

        def add_injury():
            st.session_state.injuries.append({
                "location": "knee", "severity": "medium",
                "condition": "", "is_chronic": True,
            })

        def remove_injury(idx):
            st.session_state.injuries.pop(idx)

        for i, inj in enumerate(st.session_state.injuries):
            with st.container(border=True):
                header_col, del_col = st.columns([4, 1])
                header_col.markdown(
                    f"**伤病 #{i+1}**  "
                    f"<span style='color:#94a3b8;font-size:0.85rem'>"
                    f"{joint_cn(inj['location'])} · {SEVERITY_CN.get(inj['severity'], '')}"
                    f"</span>",
                    unsafe_allow_html=True,
                )
                del_col.button("🗑 删除", key=f"del_{i}",
                               on_click=remove_injury, args=(i,),
                               use_container_width=True)

                ia, ib, ic = st.columns([1, 1, 1])
                inj["location"] = ia.selectbox(
                    "部位", INJURY_LOCATIONS, key=f"loc_{i}",
                    index=INJURY_LOCATIONS.index(inj["location"]),
                    format_func=joint_cn,
                )
                inj["severity"] = ib.selectbox(
                    "严重程度", ["low", "medium", "high"], key=f"sev_{i}",
                    index=["low", "medium", "high"].index(inj["severity"]),
                    format_func=lambda x: SEVERITY_CN.get(x, x),
                )
                inj["is_chronic"] = ic.checkbox(
                    "慢性伤", value=inj.get("is_chronic", True), key=f"chr_{i}",
                )
                hint = CONDITION_EXAMPLES.get(inj["location"], "")
                inj["condition"] = st.text_input(
                    "诊断名称",
                    value=inj.get("condition", ""),
                    placeholder=hint,
                    key=f"cond_{i}",
                    help=f"示例：{hint}" if hint else None,
                )

        st.button("➕ 添加伤病", on_click=add_injury, use_container_width=True)

        # ── 训练反馈 ────────────────────────────────────────────────────────
        with st.expander("📊 上次训练反馈（可选 — 用于动态调整）"):
            enable_feedback = st.checkbox("启用训练反馈", value=False)
            rpe = None
            pain_dict = None
            fatigue_dict = None

            if enable_feedback:
                rpe = st.slider(
                    "自觉运动强度（RPE 1-10）", 1, 10, 7,
                    help="1 = 极其轻松；5 = 中等；10 = 精疲力竭",
                )
                enable_pain = st.checkbox("存在疼痛", value=False)
                if enable_pain:
                    pc1, pc2, pc3 = st.columns(3)
                    pain_loc = pc1.selectbox(
                        "疼痛部位", INJURY_LOCATIONS,
                        key="pain_loc", format_func=joint_cn,
                    )
                    pain_sev = pc2.slider("疼痛强度", 1, 10, 5, key="pain_sev")
                    pain_type = pc3.selectbox(
                        "疼痛性质", list(PAIN_TYPE_CN.keys()), key="pain_type",
                        format_func=lambda x: PAIN_TYPE_CN.get(x, x),
                    )
                    pain_trigger = st.text_input(
                        "触发该疼痛的动作（可选）", key="pain_trigger",
                        placeholder="例如：Barbell Back Squat",
                    )
                    pain_dict = {
                        "has_pain": True,
                        "pain_location": pain_loc,
                        "pain_severity": pain_sev,
                        "pain_type": pain_type,
                        "pain_trigger": pain_trigger or None,
                    }
                enable_fatigue = st.checkbox("存在明显疲劳", value=False)
                if enable_fatigue:
                    fc1, fc2 = st.columns(2)
                    overall_fatigue = fc1.slider("整体疲劳度", 1, 10, 6, key="fatigue_val")
                    sleep_quality = fc2.slider("昨晚睡眠质量", 1, 10, 7, key="sleep_val")
                    fatigue_dict = {
                        "overall_fatigue": overall_fatigue,
                        "sleep_quality_last_night": sleep_quality,
                    }

        st.divider()
        generate_btn = st.button(
            "🚀 生成训练计划",
            type="primary",
            use_container_width=True,
        )

    # ── 右列：结果 ──────────────────────────────────────────────────────────
    with col_result:
        if generate_btn:
            medical_history = [
                {
                    "location": inj["location"],
                    "severity": inj["severity"],
                    "condition": inj["condition"] or f"{inj['location']}_injury",
                    "is_chronic": inj["is_chronic"],
                }
                for inj in st.session_state.injuries
            ]
            user_profile = {
                "user_id": user_id,
                "fitness_level": fitness_level,
                "age": age,
                "weight_kg": weight,
                "height_cm": height,
                "medical_history": medical_history,
            }

            feedback_input = None
            if enable_feedback and rpe is not None:
                feedback_input = {"rpe": rpe}
                if pain_dict:
                    feedback_input["pain_feedback"] = pain_dict
                if fatigue_dict:
                    feedback_input["fatigue_feedback"] = fatigue_dict

            try:
                engine = load_engine()

                # ═══ 调用生成器并统计耗时 ═══
                spin_msg = (
                    f"🤖 正在调用 {SYS_MODEL} 生成计划（约 30–90 秒）…"
                    if use_llm else "🔍 正在分析风险并生成计划…"
                )
                t_start = time.time()
                with st.spinner(spin_msg):
                    plan_gen = PlanGeneratorMock(engine, use_llm=use_llm)
                    plan = plan_gen.generate_plan(
                        user_profile=user_profile,
                        feedback_input=feedback_input,
                        workout_type=workout_type,
                    )
                    plan_json = plan_gen.export_plan_as_json(
                        plan, generator_version=plan_gen.generator_version,
                    )
                elapsed = time.time() - t_start

                # ═══ 调用结果状态徽章 ═══
                actual_version = plan_json.get("generator_version", "?")
                if actual_version == "llm_v1.0":
                    status_html = f"""
                    <span class="status-badge status-llm">
                        ✅ 已成功调用大模型 · {SYS_MODEL} · 耗时 {elapsed:.1f}s
                    </span>"""
                elif actual_version == "mock_v1.0_fallback":
                    status_html = """
                    <span class="status-badge status-fail">
                        ⚠️ 大模型调用失败，已自动降级为 Mock 模式
                    </span>"""
                else:
                    status_html = f"""
                    <span class="status-badge status-mock">
                        📦 Mock 离线模式 · 耗时 {elapsed:.2f}s
                    </span>"""
                st.markdown(status_html, unsafe_allow_html=True)

                forbidden, safe = engine.analyze_static_risk(user_profile)
                constraints = (
                    engine.analyze_dynamic_feedback(feedback_input)
                    if feedback_input else []
                )

                # ═══ 计划摘要 ═══
                st.markdown("### 📋 训练计划总览")

                info_c1, info_c2, info_c3, info_c4 = st.columns(4)
                info_c1.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#7c3aed;font-size:1.3rem">
                    {WORKOUT_TYPE_CN.get(plan_json.get('workout_type',''), plan_json.get('workout_type',''))}
                    </div><div class="metric-label">训练类型</div></div>""",
                    unsafe_allow_html=True)
                info_c2.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#06b6d4">
                    {plan_json.get('estimated_duration_minutes','?')}
                    <span style="font-size:1rem;color:#94a3b8">分钟</span></div>
                    <div class="metric-label">预计时长</div></div>""",
                    unsafe_allow_html=True)
                phases = plan_json.get("phases", {})
                total_ex = sum(len(phases.get(k, [])) for k in _PHASE_META)
                total_sets = sum(_phase_sets(phases.get(k, [])) for k in _PHASE_META)
                info_c3.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#22c55e">{total_ex}</div>
                    <div class="metric-label">动作总数</div></div>""",
                    unsafe_allow_html=True)
                info_c4.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#f59e0b">{total_sets}</div>
                    <div class="metric-label">总组数</div></div>""",
                    unsafe_allow_html=True)

                gen_at = plan_json.get("generated_at", "")[:19].replace("T", " ")
                st.caption(
                    f"📌 计划编号：`{plan_json.get('plan_id','?')}` · "
                    f"用户：`{plan_json.get('user_id','?')}` · 生成时间：{gen_at}"
                )

                render_timeline(phases)

                # ═══ 风险分析 ═══
                st.markdown("### 🔒 风险分析摘要")
                m1, m2, m3 = st.columns(3)
                m1.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#f87171">{len(forbidden)}</div>
                    <div class="metric-label">禁止动作</div></div>""",
                    unsafe_allow_html=True)
                m2.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#4ade80">{len(safe)}</div>
                    <div class="metric-label">可用动作</div></div>""",
                    unsafe_allow_html=True)
                m3.markdown(f"""<div class="metric-box">
                    <div class="metric-value" style="color:#facc15">{len(constraints)}</div>
                    <div class="metric-label">动态约束</div></div>""",
                    unsafe_allow_html=True)

                if forbidden:
                    with st.expander(f"🚫 查看 {len(forbidden)} 个被禁止的动作", expanded=False):
                        for ex in forbidden:
                            st.markdown(f"""
                            <div class="forbidden-row">
                                <div class="forbidden-name">🚫 {ex_cn(ex.name)}
                                <span style="color:#64748b;font-size:0.8rem;font-weight:400">
                                （{ex.name}）</span></div>
                                <div class="forbidden-reason">📝 {ex.reason}</div>
                                <div class="forbidden-sub">✅ 建议替代：{ex_cn(ex.substitution) if ex.substitution else '—'}</div>
                            </div>""", unsafe_allow_html=True)

                if constraints:
                    with st.expander(f"⚠️ 查看 {len(constraints)} 条动态约束", expanded=True):
                        for c in constraints:
                            priority_icon = "🔴" if c.priority == 1 else "🟡" if c.priority == 2 else "🔵"
                            priority_text = "高" if c.priority == 1 else "中" if c.priority == 2 else "低"
                            type_cn = CONSTRAINT_TYPE_CN.get(c.constraint_type, c.constraint_type)
                            st.markdown(f"""
                            <div class="constraint-row priority-{c.priority}">
                                <strong>{priority_icon} {type_cn}</strong>
                                <span style="color:#94a3b8;font-size:0.8rem">（优先级：{priority_text}）</span>
                                <div style="color:#cbd5e1;font-size:0.88rem;margin-top:4px">{c.description}</div>
                            </div>""", unsafe_allow_html=True)

                # ═══ 安全提示 ═══
                if plan_json.get("safety_notes"):
                    with st.expander("💡 安全提示与注意事项", expanded=True):
                        for note in plan_json["safety_notes"]:
                            st.markdown(f"- {translate_safety_note(note)}")

                # ═══ 详细训练安排（分 tab 展示，告别长滚动）═══
                st.markdown("### 💪 详细训练安排")
                st.caption("下面按训练阶段分页展示，点击标签切换，每个动作附带示意图与标准技术要领。")

                phase_order = ("warm_up", "activation", "main_lifts", "accessories", "cool_down")
                tab_labels = []
                for k in phase_order:
                    exs = phases.get(k, [])
                    meta = _PHASE_META[k]
                    # 只显示有动作的阶段
                    label = f"{meta['cn'].split(' ', 1)[-1]} · {len(exs)}"
                    tab_labels.append(label)

                phase_tabs = st.tabs(tab_labels)
                for tab, key in zip(phase_tabs, phase_order):
                    with tab:
                        render_phase_tab(key, phases.get(key, []))

                # ═══ 下载 ═══
                st.markdown("### 📥 导出计划")
                col_dl1, col_dl2, col_dl3 = st.columns(3)

                # 文本版
                text_lines = [
                    "═" * 60,
                    "           🏋️  个性化训练计划",
                    "═" * 60,
                    f"计划编号：{plan_json.get('plan_id','?')}",
                    f"用户编号：{plan_json.get('user_id','?')}",
                    f"训练类型：{WORKOUT_TYPE_CN.get(plan_json.get('workout_type',''), plan_json.get('workout_type',''))}",
                    f"预计时长：{plan_json.get('estimated_duration_minutes','?')} 分钟",
                    f"生成方式：{'🧠 大模型' if actual_version=='llm_v1.0' else '📦 Mock' if actual_version=='mock_v1.0' else '⚠️ 降级'}",
                    f"生成时间：{gen_at}",
                    "",
                ]
                for key in ("warm_up", "activation", "main_lifts", "accessories", "cool_down"):
                    exs = phases.get(key, [])
                    if not exs:
                        continue
                    meta = _PHASE_META[key]
                    text_lines.append(f"━━━ {meta['cn']} （{_phase_sets(exs)} 组） ━━━")
                    for i, ex in enumerate(exs, 1):
                        name = ex_cn(ex.get("name", ""))
                        text_lines.append(
                            f"  {i}. {name}  —  "
                            f"{ex.get('sets','?')} 组 × {ex.get('reps','?')}  "
                            f"（休息 {ex.get('rest_seconds', 0)}s）"
                        )
                        if ex.get("target_muscle"):
                            text_lines.append(f"     🎯 目标肌群：{muscle_cn(ex['target_muscle'])}")
                        if ex.get("notes"):
                            text_lines.append(f"     💡 要点：{translate_notes(ex['notes'])}")
                        text_lines.append("")

                if plan_json.get("safety_notes"):
                    text_lines.append("━━━ 安全提示 ━━━")
                    for n in plan_json["safety_notes"]:
                        text_lines.append(f"  • {translate_safety_note(n)}")

                # Markdown 版
                md_lines = [
                    f"# 🏋️ 个性化训练计划",
                    "",
                    f"- **计划编号**：`{plan_json.get('plan_id','?')}`",
                    f"- **用户**：`{plan_json.get('user_id','?')}`",
                    f"- **训练类型**：{WORKOUT_TYPE_CN.get(plan_json.get('workout_type',''), '')}",
                    f"- **预计时长**：{plan_json.get('estimated_duration_minutes','?')} 分钟",
                    f"- **生成时间**：{gen_at}",
                    "",
                ]
                for key in ("warm_up", "activation", "main_lifts", "accessories", "cool_down"):
                    exs = phases.get(key, [])
                    if not exs:
                        continue
                    meta = _PHASE_META[key]
                    md_lines.append(f"## {meta['cn']}  <small>（{_phase_sets(exs)} 组）</small>")
                    md_lines.append("")
                    md_lines.append("| # | 动作 | 组×次 | 休息 | 目标肌群 | 教练要点 |")
                    md_lines.append("|---|------|-------|------|----------|----------|")
                    for i, ex in enumerate(exs, 1):
                        md_lines.append(
                            f"| {i} | **{ex_cn(ex.get('name',''))}** | "
                            f"{ex.get('sets','?')}×{ex.get('reps','?')} | "
                            f"{ex.get('rest_seconds',0)}s | "
                            f"{muscle_cn(ex.get('target_muscle',''))} | "
                            f"{translate_notes(ex.get('notes','')) or '—'} |"
                        )
                    md_lines.append("")
                if plan_json.get("safety_notes"):
                    md_lines.append("## ⚠️ 安全提示")
                    for n in plan_json["safety_notes"]:
                        md_lines.append(f"- {translate_safety_note(n)}")

                col_dl1.download_button(
                    "📄 下载纯文本",
                    data="\n".join(text_lines),
                    file_name=f"{plan_json['plan_id']}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
                col_dl2.download_button(
                    "📝 下载 Markdown",
                    data="\n".join(md_lines),
                    file_name=f"{plan_json['plan_id']}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
                col_dl3.download_button(
                    "📦 下载 JSON",
                    data=json.dumps(plan_json, ensure_ascii=False, indent=2),
                    file_name=f"{plan_json['plan_id']}.json",
                    mime="application/json",
                    use_container_width=True,
                )

            except Exception as exc:
                st.error(f"❌ 生成失败：{exc}")
                with st.expander("错误详情"):
                    st.code(traceback.format_exc())
        else:
            st.info("👈 请先在左侧填写用户档案和伤病史，然后点击「🚀 生成训练计划」")
            st.markdown("""
            #### 📖 使用说明

            1. **填写用户基本信息**：年龄、体重、身高、训练水平
            2. **录入伤病史**：点击「➕ 添加伤病」可添加多条伤病记录
            3. **（可选）录入训练反馈**：上次训练的 RPE、疼痛、疲劳度
            4. **选择训练类型**（左侧边栏）：全身/上肢/下肢/推/拉/恢复
            5. **点击「🚀 生成训练计划」**

            #### 🎯 输出特性

            - **五阶段计划**：热身 → 激活 → 主项 → 辅助 → 放松
            - **每个动作包含**：组数、次数、组间休息、目标肌群、**教练技术要点**
            - **风险分析报告**：禁止动作列表 + 替代建议 + 动态约束
            - **多格式导出**：纯文本（打印直接可用）/ Markdown / JSON
            """)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 伤病风险分析
# ═══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown("### 🔍 静态伤病风险分析")
    st.caption("输入用户的伤病史，系统将列出哪些动作应被禁止以及原因。")

    rc1, rc2 = st.columns([1, 1.4], gap="large")

    with rc1:
        r_user_id = st.text_input("用户编号", value="risk_user", key="risk_uid")
        r_fitness = st.selectbox(
            "训练水平", list(FITNESS_CN.keys()), index=1, key="risk_fit",
            format_func=lambda x: FITNESS_CN.get(x, x),
        )

        st.markdown("**伤病史**")
        if "risk_injuries" not in st.session_state:
            st.session_state.risk_injuries = []

        def add_risk_injury():
            st.session_state.risk_injuries.append(
                {"location": "knee", "severity": "high", "condition": ""}
            )

        def del_risk_injury(idx):
            st.session_state.risk_injuries.pop(idx)

        for i, inj in enumerate(st.session_state.risk_injuries):
            with st.container(border=True):
                ra, rb = st.columns(2)
                inj["location"] = ra.selectbox(
                    "部位", INJURY_LOCATIONS, key=f"rloc_{i}",
                    index=INJURY_LOCATIONS.index(inj.get("location", "knee")),
                    format_func=joint_cn,
                )
                inj["severity"] = rb.selectbox(
                    "严重程度", ["low", "medium", "high"], key=f"rsev_{i}",
                    index=["low", "medium", "high"].index(inj.get("severity", "medium")),
                    format_func=lambda x: SEVERITY_CN.get(x, x),
                )
                inj["condition"] = st.text_input(
                    "诊断名称（可选）",
                    value=inj.get("condition", ""),
                    key=f"rcond_{i}",
                )
                st.button("🗑 删除", key=f"rdel_{i}",
                          on_click=del_risk_injury, args=(i,),
                          use_container_width=True)

        st.button("➕ 添加伤病", key="add_risk_inj",
                  on_click=add_risk_injury, use_container_width=True)
        analyze_btn = st.button("🔍 开始分析",
                                type="primary", use_container_width=True, key="risk_btn")

    with rc2:
        if analyze_btn:
            engine = load_engine()
            profile = {
                "user_id": r_user_id,
                "fitness_level": r_fitness,
                "medical_history": [
                    {"location": inj["location"], "severity": inj["severity"],
                     "condition": inj.get("condition") or f"{inj['location']}_injury"}
                    for inj in st.session_state.risk_injuries
                ],
            }
            forbidden, safe = engine.analyze_static_risk(profile)
            total = len(engine.exercise_db)

            mc1, mc2 = st.columns(2)
            mc1.markdown(f"""<div class="metric-box">
                <div class="metric-value" style="color:#f87171">{len(forbidden)}</div>
                <div class="metric-label">禁止动作</div></div>""",
                unsafe_allow_html=True)
            mc2.markdown(f"""<div class="metric-box">
                <div class="metric-value" style="color:#4ade80">{len(safe)}</div>
                <div class="metric-label">可用动作（共 {total} 个）</div></div>""",
                unsafe_allow_html=True)

            if not forbidden:
                st.success(f"✅ 该用户无禁忌动作，所有 {total} 个动作均可安全训练。")
            else:
                st.markdown("#### 📋 禁止动作详情")
                rows = []
                for ex in forbidden:
                    rows.append({
                        "动作名称": ex_cn(ex.name),
                        "英文": ex.name,
                        "禁止原因": ex.reason,
                        "风险等级": ex.risk_level,
                        "涉及关节": joints_cn(ex.involved_joints),
                        "推荐替代": ex_cn(ex.substitution) if ex.substitution else "—",
                    })
                st.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "风险等级": st.column_config.ProgressColumn(
                            "风险等级", min_value=1, max_value=5, format="%d/5",
                        ),
                    },
                )
        else:
            st.info("👈 填写左侧伤病史后点击「🔍 开始分析」。")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — 动作数据库
# ═══════════════════════════════════════════════════════════════════════════════
with tab_db:
    engine = load_engine()

    st.markdown("### 📚 动作知识库")
    st.caption(f"共收录 {len(engine.exercise_db)} 个动作。支持按动作类型、风险等级、涉及关节筛选。")

    db_col1, db_col2, db_col3 = st.columns(3)
    filter_type = db_col1.selectbox(
        "动作类型",
        ["全部", "Compound", "Isolation", "Isometric"],
        format_func=lambda x: "全部" if x == "全部" else TYPE_CN.get(x, x),
        key="db_type",
    )
    filter_risk = db_col2.slider("最大风险等级", 1, 5, 5, key="db_risk",
                                  help="只显示风险等级 ≤ 此值的动作")
    filter_joint = db_col3.selectbox(
        "涉及关节",
        ["全部"] + list(JOINT_CN.keys()),
        format_func=lambda x: "全部" if x == "全部" else JOINT_CN.get(x, x),
        key="db_joint",
    )

    rows = []
    for ex in engine.exercise_db:
        if filter_type != "全部" and ex.get("type") != filter_type:
            continue
        if ex.get("risk_level", 5) > filter_risk:
            continue
        joints = ex.get("involved_joints", [])
        if filter_joint != "全部" and filter_joint not in joints:
            continue
        rows.append({
            "编号": ex.get("id"),
            "动作名称": ex_cn(ex.get("name", "")),
            "英文名": ex.get("name", ""),
            "类型": TYPE_CN.get(ex.get("type", ""), ex.get("type", "")),
            "目标肌群": muscle_cn(ex.get("target_muscle", "")),
            "涉及关节": joints_cn(joints),
            "风险等级": ex.get("risk_level"),
            "推荐替代": ex_cn(ex.get("substitution", "")) if ex.get("substitution") else "—",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "风险等级": st.column_config.ProgressColumn(
                    "风险等级", min_value=1, max_value=5, format="%d/5",
                ),
            },
        )
        st.caption(f"📊 当前显示 {len(df)} / {len(engine.exercise_db)} 个动作")
    else:
        st.warning("⚠️ 没有符合筛选条件的动作，请调整筛选参数。")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — AI 教练对话（Phase 4）
# ═══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    # Lazy-import backend modules so any failure here doesn't break other tabs.
    from sqlalchemy.orm import Session as _Session

    try:
        from database import SessionLocal as _SessionLocal
        from coach_agent import CoachAgent, build_context
        import crud as _crud
        _CHAT_OK = True
        _CHAT_ERR = None
    except Exception as _e:
        _CHAT_OK = False
        _CHAT_ERR = str(_e)

    st.markdown("### 💬 与你的 AI 健身教练对话")
    st.caption(
        "教练会自动读取你的用户档案、训练历史、当前活跃训练计划与下一次训练，"
        "并据此回答问题、给出建议、提议执行操作。"
    )

    if not _CHAT_OK:
        st.error(f"对话功能加载失败：{_CHAT_ERR}")
        st.stop()

    # ── 顶栏：用户选择 + 会话管理 ─────────────────────────────────────────
    chat_col_user, chat_col_action = st.columns([3, 2])

    with chat_col_user:
        chat_user_id = st.text_input(
            "用户编号",
            value=st.session_state.get("chat_user_id", "user_001"),
            key="chat_user_id_input",
            help="教练会以此用户身份读取数据库（档案、历史、计划）",
        )
        st.session_state["chat_user_id"] = chat_user_id

    with chat_col_action:
        st.write("")  # spacing
        if st.button("🆕 开启新对话", use_container_width=True, key="chat_new"):
            st.session_state["chat_messages"] = []
            st.session_state["chat_conversation_id"] = None
            st.session_state["chat_pending_action"] = None
            st.rerun()

    # ── 教练人设说明（折叠） ───────────────────────────────────────────────
    with st.expander("ℹ️ 这位教练能做什么？", expanded=False):
        st.markdown("""
**教练的能力（基于上下文 + LLM）：**

- 📊 **数据驱动建议**：分析你最近 8 次训练的 RPE 趋势、疼痛规律、完成率
- 🩹 **伤病感知**：根据你的医疗史，避开危险动作并提醒注意事项
- 🎯 **计划洞察**：知道你当前活跃的多周计划进度和下一次训练
- ⚡ **建议操作**：可以提议生成新计划/推进周次/记录训练（需你点击确认）

**示例提问：**
- "我最近 5 次训练表现怎么样？需要调整吗？"
- "膝盖最近有点不舒服，下次训练是不是该减量？"
- "帮我生成一份 4 周的力量计划"
- "推进到下一周计划"
        """)

    # ── 初始化 session state ─────────────────────────────────────────────
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []
    if "chat_conversation_id" not in st.session_state:
        st.session_state["chat_conversation_id"] = None
    if "chat_pending_action" not in st.session_state:
        st.session_state["chat_pending_action"] = None

    # ── 历史消息渲染 ──────────────────────────────────────────────────────
    for m in st.session_state["chat_messages"]:
        role = m.get("role", "user")
        avatar = "👤" if role == "user" else "🤖"
        with st.chat_message(role, avatar=avatar):
            st.markdown(m.get("content", ""))
            ar = m.get("action_request")
            if ar and role == "assistant":
                _label = ar.get("confirm_label") or ar.get("tool")
                _tool = ar.get("tool")
                _rationale = ar.get("rationale", "")
                st.info(f"💡 教练建议执行：**{_label}**\n\n_理由：{_rationale}_")
                st.caption(
                    "（动作执行需到对应 Tab 操作 — 这里仅展示教练的建议，不会自动执行）"
                )

    # ── 输入框 ────────────────────────────────────────────────────────────
    user_input = st.chat_input(
        "向教练提问…（如：我最近训练强度合适吗？）",
        key="chat_input",
    )

    if user_input:
        if not LLM_CONFIGURED:
            st.warning(
                "⚠️ 当前未配置真实 LLM（缺少 ANTHROPIC_API_KEY/MINIMAX_API_KEY 或 LLM_PROVIDER 不为 minimax_anthropic）。"
                "教练会使用本地兜底回复，可正常验证流程。"
            )

        # 显示用户消息
        st.session_state["chat_messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        # 调用 CoachAgent（直接进程内调用，无需 HTTP）
        agent = CoachAgent()
        db: _Session = _SessionLocal()
        try:
            context = build_context(db, chat_user_id, history_window=8)
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["chat_messages"][:-1]  # exclude current
                if m.get("role") in ("user", "assistant")
            ]

            with st.chat_message("assistant", avatar="🤖"):
                placeholder = st.empty()
                streamed = ""

                try:
                    # 尝试流式
                    for evt in agent.stream_respond(
                        context=context,
                        history=history,
                        user_message=user_input,
                    ):
                        if evt["type"] == "delta":
                            streamed += evt["text"]
                            placeholder.markdown(streamed + "▌")
                        elif evt["type"] == "final":
                            final_content = evt.get("content", "") or streamed
                            action_req = evt.get("action_request")
                            placeholder.markdown(final_content)
                            st.session_state["chat_messages"].append({
                                "role": "assistant",
                                "content": final_content,
                                "action_request": action_req,
                            })
                            if action_req:
                                _label = action_req.get("confirm_label") or action_req.get("tool")
                                _rationale = action_req.get("rationale", "")
                                st.info(f"💡 教练建议执行：**{_label}**\n\n_理由：{_rationale}_")
                            break
                        elif evt["type"] == "error":
                            placeholder.error(f"⚠️ 教练响应失败：{evt.get('message')}")
                            break
                except Exception as exc:
                    # Fallback: non-streaming
                    placeholder.markdown("（流式失败，切换为同步模式）")
                    response = agent.respond(
                        context=context,
                        history=history,
                        user_message=user_input,
                    )
                    placeholder.markdown(response.content)
                    st.session_state["chat_messages"].append({
                        "role": "assistant",
                        "content": response.content,
                        "action_request": (
                            response.action_request.to_dict()
                            if response.action_request else None
                        ),
                    })
        finally:
            db.close()
