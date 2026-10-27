"""动作元数据：示意图 URL + 中文技术要领（教练级详解）。

数据来源：
- 图片：free-exercise-db (Public Domain, https://github.com/yuhonas/free-exercise-db)
- 技术要领：基于 NSCA Essentials of Strength Training and Conditioning 等教材整理
"""

from __future__ import annotations

_IMG_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"


# 动作英文名 → 图片路径（追加 _IMG_BASE 拼成完整 URL）
_IMG_MAP = {
    "Barbell Back Squat":       "Barbell_Full_Squat/0.jpg",
    "Front Squat":              "Front_Barbell_Squat/0.jpg",
    "Conventional Deadlift":    "Barbell_Deadlift/0.jpg",
    "Romanian Deadlift":        "Romanian_Deadlift/0.jpg",
    "Sumo Deadlift":            "Sumo_Deadlift/0.jpg",
    "Barbell Bench Press":      "Barbell_Bench_Press_-_Medium_Grip/0.jpg",
    "Incline Dumbbell Press":   "Incline_Dumbbell_Press/0.jpg",
    "Overhead Press":           "Standing_Military_Press/0.jpg",
    "Arnold Press":             "Arnold_Dumbbell_Press/0.jpg",
    "Lateral Raise":            "Side_Lateral_Raise/0.jpg",
    "Barbell Row":              "Bent_Over_Barbell_Row/0.jpg",
    "T-Bar Row":                "T-Bar_Row_with_Handle/0.jpg",
    "Seated Cable Row":         "Seated_Cable_Rows/0.jpg",
    "Lat Pulldown":             "Wide-Grip_Lat_Pulldown/0.jpg",
    "Pull-Up":                  "Pullups/0.jpg",
    "Face Pull":                "Face_Pull/0.jpg",
    "Dumbbell Shrug":           "Dumbbell_Shrug/0.jpg",
    "Barbell Curl":             "Barbell_Curl/0.jpg",
    "Preacher Curl":            "Preacher_Curl/0.jpg",
    "Dumbbell Hammer Curl":     "Hammer_Curls/0.jpg",
    "Tricep Pushdown":          "Triceps_Pushdown/0.jpg",
    "Skull Crusher":            "EZ-Bar_Skullcrusher/0.jpg",
    "Tricep Dip":               "Dips_-_Triceps_Version/0.jpg",
    "Cable Crossover":          "Cable_Crossover/0.jpg",
    "Dumbbell Fly":             "Dumbbell_Flyes/0.jpg",
    "Push-Up":                  "Pushups/0.jpg",
    "Leg Press":                "Leg_Press/0.jpg",
    "Leg Extension":            "Leg_Extensions/0.jpg",
    "Leg Curl":                 "Seated_Leg_Curl/0.jpg",
    "Bulgarian Split Squat":    "Dumbbell_Lunges/0.jpg",
    "Walking Lunge":            "Dumbbell_Lunges/0.jpg",
    "Hip Thrust":               "Barbell_Hip_Thrust/0.jpg",
    "Calf Raise":               "Standing_Barbell_Calf_Raise/0.jpg",
    "Good Morning":             "Good_Morning/0.jpg",
    "Back Extension":           "Hyperextensions_Back_Extensions/0.jpg",
    "Plank":                    "Plank/0.jpg",
    "Crunch":                   "Crunch_-_Hands_Overhead/0.jpg",
    "Hanging Leg Raise":        "Hanging_Leg_Raise/0.jpg",
    "Russian Twist":            "Seated_Barbell_Twist/0.jpg",
    "Wrist Curl":               "Cable_Wrist_Curl/0.jpg",
    # 热身 / 激活 / 冷身（训练计划中也会出现）
    "Glute Bridge":             "Barbell_Hip_Thrust/0.jpg",
    "Bird Dog":                 "Dead_Bug/0.jpg",
    "Cat-Cow Stretch":          "Cat_Stretch/0.jpg",
    "Light Treadmill Walk":     "Walking_Treadmill/0.jpg",
    "Jumping Jacks":            "Rope_Jumping/0.jpg",
    "Arm Circles":              "Arm_Circles/0.jpg",
    "Leg Swings":               "Dumbbell_Lunges/0.jpg",
    "Hip Circles":              "Standing_Hip_Circles/0.jpg",
    "Bodyweight Good Morning":  "Good_Morning/0.jpg",
    "Dead Bug":                 "Dead_Bug/0.jpg",
    "Band Pull-Apart":          "Band_Pull_Apart/0.jpg",
    "Clamshells":               "Adductor_Groin/0.jpg",
    "Scapular Push-Ups":        "Pushups/0.jpg",
    "Static Quad Stretch":      "Quad_Stretch/0.jpg",
    "Hamstring Stretch":        "Hamstring_Stretch/0.jpg",
    "Chest Doorway Stretch":    "Dumbbell_Flyes/0.jpg",
    "Child's Pose":             "Childs_Pose/0.jpg",
    "Supine Twist":             "Seated_Barbell_Twist/0.jpg",
    "Foam Rolling - Full Body": "Calves-SMR/0.jpg",
}


# 动作英文名 → 中文技术要领（3-6 条结构化教学要点）
_TECHNIQUE = {
    "Goblet Squat": [
        "双手捧住一只哑铃贴于胸前，肘尖朝下，全程保持贴胸。",
        "脚略宽于肩、脚尖外展 15-20 度，重心落在全脚掌。",
        "屈髋屈膝同步下蹲，膝盖跟随脚尖方向，蹲到不塌腰的最低点。",
        "起身时先蹬地再伸膝，胸口与髋同时上升，不要先抬臀。",
        "哑铃贴胸会产生前侧负荷，反而帮助保持躯干直立——这是它比杠铃深蹲更适合膝伤恢复期的原因。",
    ],
    "Dumbbell Romanian Deadlift": [
        "双手持哑铃置于大腿前侧，双脚与髋同宽，膝微屈并固定角度。",
        "以髋为轴向后推臀，哑铃贴腿下放，感受腘绳肌被拉长。",
        "下放到腘绳肌张力明显但腰背仍中立的位置即停，不必触地。",
        "起身靠髋部前推完成，不要用腰把身体「抬」起来。",
        "全程脊柱中立、核心收紧；一旦出现腰部代偿立刻减幅度。",
    ],
    "Dumbbell Sumo Deadlift": [
        "双脚宽站、脚尖外展约 30 度，哑铃置于两脚中间。",
        "屈髋屈膝下蹲握铃，背部挺直，胸口朝前。",
        "起身时膝与髋同时伸展，哑铃贴身体中线上行。",
        "顶端收紧臀部，不要过度后仰。",
        "宽站距让髋关节承担更多负荷、膝关节压力更小，适合膝伤人群。",
    ],
    "Single-Leg Glute Bridge": [
        "仰卧屈膝，一脚踩地，另一腿伸直或屈膝抬起。",
        "呼气时踩地侧臀部发力，把髋顶到躯干与大腿成一直线。",
        "顶端停留 1-2 秒，感受臀部而非腰部发力。",
        "控制下放，不要直接落下。",
        "单侧版本会明显增加骨盆稳定需求；若出现骨盆旋转先退回双腿臀桥。",
    ],
    "One-Arm Dumbbell Row": [
        "一手一膝支撑于长凳，背部与地面接近平行，核心收紧。",
        "持铃手自然下垂，肩胛先下沉再启动。",
        "以肘领先向后上方拉，肘贴近身体，拉到腰侧。",
        "顶端短暂停顿，控制下放到肩胛充分前伸。",
        "全程躯干不旋转——若身体跟着转，说明重量过大。",
    ],
    "Dumbbell Bent-Over Row": [
        "双脚与髋同宽，屈髋前倾至躯干接近水平，哑铃自然下垂。",
        "核心收紧锁定躯干角度，全程不变。",
        "双肘沿身体两侧后拉，肩胛骨向脊柱靠拢。",
        "下放时控制离心，肩胛充分前伸后再启动下一次。",
        "腰部有不适时改为单臂支撑版本，或提高躯干角度减小力矩。",
    ],
    "Inverted Row": [
        "在史密斯机或低杠下方仰卧，双手握杠略宽于肩。",
        "身体绷成一条直线，从肩到脚踝不塌不拱。",
        "肩胛先收紧，再以肘领先把胸口拉向杠。",
        "控制下放到手臂完全伸直，全程保持核心张力。",
        "难度靠调整杠高或屈膝程度调节，比引体向上更适合起步阶段。",
    ],
    "Cat-Cow": [
        "四点跪姿，手掌在肩下、膝在髋下。",
        "吸气时抬头塌腰（牛式），呼气时拱背低头（猫式）。",
        "逐节活动脊柱，从腰到颈连贯流动。",
        "动作与呼吸同步，速度放慢。",
    ],
    "Shoulder Pass-Through": [
        "双手宽握弹力带或木棍，置于体前。",
        "手臂伸直，缓慢将器械从体前绕过头顶至体后。",
        "握距越窄难度越大，从宽握开始，逐步收窄。",
        "全程不耸肩、不塌腰，有牵拉感即可。",
    ],
    "Inchworm": [
        "站姿俯身，双手触地（可微屈膝）。",
        "双手交替向前爬行至平板支撑位。",
        "停顿 1 秒，再双脚小步走向双手。",
        "全程膝盖不锁死，核心保持收紧。",
    ],
    "Marching in Place": [
        "原地站立，交替抬起膝盖至髋部高度。",
        "手臂自然摆动，躯干保持直立。",
        "落地轻缓，由前脚掌过渡到全脚掌。",
        "持续 30-45 秒，呼吸均匀不憋气。",
    ],
    "World's Greatest Stretch": [
        "弓步姿势，前腿屈膝约 90°，后腿伸直。",
        "同侧手肘向下压向脚内侧，感受髋部打开。",
        "随后向上旋转胸椎，手臂指向天花板。",
        "每侧 5-6 次，动作缓慢连贯不弹震。",
    ],
    "Ankle Rocks": [
        "半跪姿或站姿，前脚掌踩实地面。",
        "膝盖缓慢向前推超过脚尖，脚跟不离地。",
        "感受踝关节前侧与小腿的牵拉。",
        "每侧 10 次，控制速度不借助惯性。",
    ],
    "Thoracic Rotation": [
        "四点跪姿，一手放在脑后。",
        "手肘向天花板方向打开，带动胸椎旋转。",
        "视线跟随手肘，骨盆保持不动。",
        "每侧 8-10 次，呼气时完成旋转。",
    ],
    "Standing Hamstring Stretch": [
        "单腿伸直置于台阶或地面，脚尖回勾。",
        "髋部折叠向前，背部保持平直不弓背。",
        "感受大腿后侧牵拉，不追求手碰脚。",
        "每侧保持 30 秒，呼吸均匀不憋气。",
    ],
    "Standing Quad Stretch": [
        "单手扶墙，另一手抓同侧脚踝。",
        "脚跟拉向臀部，两侧膝盖保持并拢。",
        "骨盆略后倾，感受大腿前侧牵拉。",
        "每侧 30 秒，膝关节不适立即停止。",
    ],
    "Wall Calf Stretch": [
        "面墙站立，双手扶墙，一侧腿后撤。",
        "后腿伸直、脚跟压地，前腿屈膝。",
        "重心缓慢前移，感受小腿后侧牵拉。",
        "每侧 30 秒，脚跟始终不离地。",
    ],
    "Doorway Chest Stretch": [
        "站在门框中间，前臂贴门框，手肘略高于肩。",
        "身体缓慢前倾，感受胸前牵拉。",
        "肩胛骨后缩下沉，不耸肩。",
        "每侧 30 秒，肩前侧出现刺痛立即退出。",
    ],
    "Figure-4 Glute Stretch": [
        "仰卧，一侧脚踝搭在对侧膝上呈「4」字。",
        "双手抱住下方大腿后侧，缓慢拉向胸口。",
        "感受臀部深层牵拉，腰部保持贴地。",
        "每侧 30 秒，髋部出现锐痛则减小幅度。",
    ],
    "Cross-Body Shoulder Stretch": [
        "一侧手臂横过胸前，另一手扶住肘部。",
        "轻拉向对侧肩膀，肩部保持下沉。",
        "感受肩后侧牵拉，躯干不跟着旋转。",
        "每侧 30 秒，力度以无痛为限。",
    ],
    "Neck Side Stretch": [
        "坐姿或站姿，双肩放松下沉。",
        "头部缓慢侧倾，耳朵靠近肩膀。",
        "可用同侧手轻压增加牵拉，力度极轻。",
        "每侧 30 秒，出现手臂麻木立即停止。",
    ],
    "Hip Flexor Stretch": [
        "半跪姿，后腿膝盖着地，前腿屈膝约 90°。",
        "骨盆后倾（尾骨内收），身体略微前移。",
        "感受后腿髋前侧牵拉，腰部不塌陷。",
        "每侧 30 秒，避免用腰部代偿。",
    ],
    "Kneeling Lat Stretch": [
        "跪姿，双手前伸放在地面或椅面上。",
        "臀部向后坐，胸口下沉靠近地面。",
        "感受背阔肌与体侧的牵拉。",
        "保持 30 秒，每次呼气时进一步放松。",
    ],
    "Clamshell": [
        "侧卧，髋膝各屈约 45°，双脚并拢。",
        "保持骨盆垂直地面，上方膝盖向上打开。",
        "顶端停顿 1 秒，感受臀部外侧发力。",
        "每侧 12-15 次，骨盆不向后倒。",
    ],
    "Wall Slide": [
        "背靠墙站立，后脑、上背、臀部贴墙。",
        "双臂贴墙呈「W」形，沿墙向上滑至「Y」形。",
        "全程手背不离墙，肩胛骨下沉后缩。",
        "10-12 次，颈部保持中立不探头。",
    ],
    "Pallof Press": [
        "侧对绳索站立，双手握把手置于胸前。",
        "核心收紧，双臂向前推出抵抗旋转。",
        "停顿 1-2 秒后收回，躯干始终朝前。",
        "每侧 10-12 次，避免身体被拉转。",
    ],
    "Suitcase Carry": [
        "单手提起哑铃，另一侧手臂自然下垂。",
        "保持躯干直立，不向负重侧倾斜。",
        "小步行走，肩部下沉不耸肩。",
        "每侧 20-30 米，两侧交替进行。",
    ],
    "Single-Leg Balance": [
        "单腿站立，另一腿抬起离地。",
        "保持骨盆水平，支撑脚三点均匀受力。",
        "稳定后可闭眼或加入手臂摆动提高难度。",
        "每侧 30 秒，支撑膝不锁死。",
    ],
    "Scapular Push-Up": [
        "平板支撑或跪姿撑地，手臂保持伸直。",
        "仅靠肩胛骨内收与外展完成小幅起伏。",
        "身体保持一条直线，手肘不弯曲。",
        "12-15 次，幅度小而可控。",
    ],
    "Barbell Back Squat": [
        "杠铃置于上背部（斜方肌上部），双手略宽于肩紧握。",
        "双脚与肩同宽，脚尖略外展 15°–30°，核心收紧。",
        "屈髋屈膝同步下蹲，膝盖顺着脚尖方向，下至大腿平行地面或以下。",
        "发力时蹬地推髋，保持脊柱中立，避免胸口过度前倾。",
        "整个过程保持腹内压，切勿驼背或膝内扣。",
    ],
    "Front Squat": [
        "杠铃架于锁骨/三角肌前束上，手肘高抬指向前方。",
        "双脚略宽于肩，脚尖外展，躯干尽量直立。",
        "屈膝下蹲至大腿平行地面，膝盖顺脚尖方向。",
        "起立时用腿推地，保持手肘高抬防止杠铃下滑。",
        "前蹲更强调股四头肌和躯干垂直度，对膝盖友好。",
    ],
    "Conventional Deadlift": [
        "双脚与髋同宽，杠铃贴近小腿胫骨前 2–3 cm。",
        "屈髋下蹲握杠，双手略宽于肩（或一正一反混合握）。",
        "挺胸收肩胛，背部呈自然生理曲度，不得弓背。",
        "蹬地伸髋同步拉起，杠铃沿大腿前侧贴身上行。",
        "站直时挺胸收臀，切勿过度后仰；下放时反向控制。",
    ],
    "Romanian Deadlift": [
        "站直持杠于大腿前，双脚与髋同宽，膝盖微屈保持固定角度。",
        "屈髋向后推，让杠铃沿大腿下滑至膝下（约胫骨中部）。",
        "感受腘绳肌明显拉伸，脊柱保持中立。",
        "发力收紧臀与腘绳肌回拉，伸髋至站立位。",
        "重点在屈髋而非屈膝，膝盖始终保持轻微屈曲。",
    ],
    "Sumo Deadlift": [
        "双脚远宽于肩，脚尖外展 30°–45°，双手握杠在双腿之间。",
        "屈髋下蹲，胸口前挺，膝盖与脚尖同向。",
        "挺胸收肩胛，核心收紧准备拉起。",
        "蹬地伸髋，杠铃贴身上行，膝盖主动外展发力。",
        "相扑硬拉腰椎受力较小，更依赖臀肌与内收肌。",
    ],
    "Barbell Bench Press": [
        "仰卧于卧推凳，双脚踏实地面，臀部不离凳。",
        "双手略宽于肩握杠，拇指绕杠（避免空握）。",
        "收肩胛下沉锁定肩胛骨，形成自然胸椎拱起。",
        "缓慢下放至乳头上方 1–2 cm 处轻触胸口，肘部约 45°–75°。",
        "蹬腿借力推起至手臂几乎伸直，避免锁死关节。",
    ],
    "Incline Dumbbell Press": [
        "将卧推凳设置为 30°–45° 上斜，双脚踏实地面。",
        "起始位双手哑铃置于胸部两侧略低位置。",
        "肘部夹角约 60°–75°，控制下放并感受上胸拉伸。",
        "呼气推起至几乎并拢，保持肩胛收紧。",
        "上斜角度越大越刺激三角肌前束，减小胸肌上部收益。",
    ],
    "Overhead Press": [
        "双脚与肩同宽站立，双手略宽于肩握杠于锁骨前。",
        "收紧核心与臀肌，肘部位于杠铃正下方稍偏前。",
        "吸气推起，杠铃沿面部前方过头顶后微收至正上方。",
        "锁定时耸肩，双臂伸直但不过度锁肘。",
        "下放时控制速度，切勿过度挺腰弯腰代偿。",
    ],
    "Arnold Press": [
        "坐姿，双手哑铃起始于胸前，掌心对自己。",
        "推起过程中手腕同步外旋 180°，至顶点掌心朝前。",
        "核心收紧，避免挺腰；肘部不锁死。",
        "下放时反向旋转回到起始位。",
        "该动作全方位刺激三角肌三个头，重量不宜过重。",
    ],
    "Lateral Raise": [
        "站姿或坐姿持哑铃于体侧，肘部微屈约 10°–15°。",
        "肩胛下沉固定，避免耸肩代偿。",
        "用三角肌侧束发力向两侧抬起至肘部略高于肩。",
        "顶点保持 1 秒再缓慢下放，全程控制节奏。",
        "重量偏轻，以质量为主，避免借力甩动。",
    ],
    "Barbell Row": [
        "双脚与肩同宽，屈髋让躯干前倾约 45°–60°。",
        "双手略宽于肩握杠，起始悬垂于膝下。",
        "收紧核心与脊柱中立，肩胛下沉。",
        "用背阔肌与斜方肌中下部将杠铃拉至下腹或肚脐位置。",
        "下放时控制，避免弓背或靠下蹲弹起代偿。",
    ],
    "T-Bar Row": [
        "双脚跨立于 T 杠两侧，屈髋下蹲至胸前略高于水平。",
        "双手握把手，脊柱中立、胸口挺起。",
        "收紧肩胛、肘部贴身将重量拉至胸下腹上区间。",
        "顶点夹紧背肌保持 1 秒，缓慢下放。",
        "切勿弓背，控制不借腰部摇摆。",
    ],
    "Seated Cable Row": [
        "坐姿脚踏踏板，双膝略屈；握 V 形把手。",
        "挺胸收肩胛，保持躯干约 90° 直立。",
        "肘部贴身后拉至腰腹，感受背阔肌中部收缩。",
        "缓慢放回至双臂几乎伸直，保持肩胛固定。",
        "切勿用腰部前后摆动借力。",
    ],
    "Lat Pulldown": [
        "坐姿将大腿固定于垫下，双手宽握横杠。",
        "挺胸收肩胛，躯干微后倾约 10°–20°。",
        "肘部指向地面，将杠下拉至锁骨或上胸位置。",
        "顶点背阔肌夹紧 1 秒，然后缓慢放回。",
        "避免把杠拉到脖子后方（易伤肩）。",
    ],
    "Pull-Up": [
        "双手略宽于肩正握单杠，身体悬挂至手臂伸直。",
        "收紧核心，肩胛下沉启动背阔肌。",
        "肘部向下向后拉，将身体拉至下巴过杠。",
        "缓慢控制下放至起始位，避免完全放松。",
        "初学者可借弹力带或辅助器械降低难度。",
    ],
    "Face Pull": [
        "将绳索调至与面部同高，双手反握绳头。",
        "后退一步拉紧，双臂水平伸直。",
        "拉向面部，双手向两侧外展分开，肘部高抬至肩高。",
        "感受三角肌后束和菱形肌收缩，保持 1 秒。",
        "全程无需大重量，重在控制肩胛后缩。",
    ],
    "Dumbbell Shrug": [
        "双手哑铃自然垂于体侧，挺胸站立。",
        "肩胛主动上提耸肩，如同试图触碰耳朵。",
        "顶点保持 1 秒感受斜方肌收缩，切勿前后转动肩膀。",
        "缓慢放下至起始位，全程手臂伸直。",
        "重量适中，避免耸肩幅度过小或甩动。",
    ],
    "Barbell Curl": [
        "站姿双手与肩同宽握杠（掌心朝前），杠铃置于大腿前。",
        "肘部固定贴身，核心收紧。",
        "仅用肱二头肌屈肘将杠铃卷起至胸前。",
        "顶点挤压二头肌 1 秒，缓慢放回。",
        "避免借腰部前后摆动代偿，肘部不要前后移动。",
    ],
    "Preacher Curl": [
        "调整牧师椅高度至腋下贴紧斜板。",
        "反手握杠铃或哑铃，双臂完全伸展为起始位。",
        "屈肘将重量卷至上方，感受二头肌顶峰收缩。",
        "缓慢放下至接近伸直（但不锁死肘关节）。",
        "牧师椅可最大限度隔离二头肌并防止借力。",
    ],
    "Dumbbell Hammer Curl": [
        "站姿双手哑铃垂于体侧，掌心相对（中立握）。",
        "肘部贴身固定，不前后移动。",
        "屈肘将哑铃卷至肩前，保持掌心相对。",
        "顶点挤压肱肌和肱桡肌，缓慢下放。",
        "该动作刺激肱肌和前臂肌群，弥补常规弯举。",
    ],
    "Tricep Pushdown": [
        "站姿面向绳索机，使用直杆或 V 杆在高位。",
        "双手握杆，肘部贴身固定在躯干两侧。",
        "从肘屈约 90° 起始，向下推杆至手臂完全伸直。",
        "顶点夹紧三头肌 1 秒，缓慢控制返回起始位。",
        "全程肘部不前后移动，避免肩膀代偿。",
    ],
    "Skull Crusher": [
        "仰卧卧推凳，双手握 EZ 杆于胸前正上方。",
        "肘部固定朝向正前方，前臂缓慢下放至额头上方。",
        "仅前臂移动，肘部不外展或前后移动。",
        "伸肘推回至起始位，顶点挤压三头肌。",
        "重量适中以免砸到头部，也可改用哑铃。",
    ],
    "Tricep Dip": [
        "双手撑于双杠，身体悬垂起始位，双腿屈膝。",
        "核心收紧，身体保持微前倾（侧重胸）或直立（侧重三头）。",
        "屈肘下放至肩与肘同高或略低。",
        "伸肘撑起至手臂几乎伸直（不锁死）。",
        "肩膀不适者应避免过深下放。",
    ],
    "Cable Crossover": [
        "站于龙门架中央，双手各握一条高位绳索把手。",
        "躯干微前倾，双脚前后错位以保持稳定。",
        "双臂肘部略屈，从身体两侧向胸前划弧合拢。",
        "顶点挤压胸肌中部，保持 1 秒。",
        "返回时控制速度，让胸肌充分拉伸。",
    ],
    "Dumbbell Fly": [
        "仰卧平板凳，双手哑铃举于胸前正上方，掌心相对。",
        "肘部保持约 10°–20° 微屈角度不变。",
        "两臂向两侧划弧下放，至胸部略下方感受拉伸。",
        "用胸肌发力将哑铃划弧合拢至起始位。",
        "重量不宜过大，注意肩关节安全。",
    ],
    "Push-Up": [
        "俯撑地面，双手略宽于肩，手腕位于肩下。",
        "身体从头到脚踝呈一条直线，核心绷紧。",
        "肘部约 45° 夹角下放，胸部轻触地面。",
        "推起至手臂几乎伸直，保持脊柱中立。",
        "新手可屈膝做跪姿俯卧撑。",
    ],
    "Leg Press": [
        "坐于腿举机，双脚与肩同宽置于踏板中部。",
        "背部与臀部贴紧靠垫，避免腰部离开。",
        "解锁后屈膝下放至大腿接近 90°。",
        "蹬地发力推起至膝盖几乎伸直（不锁死）。",
        "不宜重量过大、下放过深以免腰椎卷起。",
    ],
    "Leg Extension": [
        "坐于腿屈伸器械，小腿垫置于脚踝上方。",
        "大腿贴紧座垫，双手握把手稳定躯干。",
        "伸膝将重量抬起至腿几乎伸直。",
        "顶点股四头肌挤压 1 秒，缓慢放回。",
        "膝盖伤者慎用，避免大重量。",
    ],
    "Leg Curl": [
        "俯卧或坐姿于腿弯举器械，小腿垫卡在跟腱上方。",
        "保持骨盆贴紧靠垫，避免腰部代偿上抬。",
        "屈膝将垫拉向臀部，感受腘绳肌收缩。",
        "顶点保持 1 秒，缓慢控制下放。",
        "重量偏中，避免跳动和借力。",
    ],
    "Bulgarian Split Squat": [
        "后脚脚背搭于凳上，前脚向前迈一大步保持平衡。",
        "躯干保持直立或微前倾，核心收紧。",
        "屈前膝下蹲至后膝接近地面，前膝对齐脚尖。",
        "前脚跟发力蹬起回到起始位。",
        "可徒手或持哑铃增加负荷，注意膝盖稳定。",
    ],
    "Walking Lunge": [
        "站立持哑铃或杠铃，挺胸核心收紧。",
        "一步向前迈出，前膝屈至约 90°，后膝轻触地。",
        "前脚发力推起同时迈出另一腿向前。",
        "全程保持躯干直立，膝盖对齐脚尖。",
        "交替前进，核心与平衡能力要求较高。",
    ],
    "Hip Thrust": [
        "上背靠于凳边，杠铃置于髋部（垫软垫保护）。",
        "双脚与肩同宽，脚跟用力，膝盖约 90°。",
        "收紧臀肌将杠铃推起至躯干与大腿成一条直线。",
        "顶点最大化挤压臀肌 1 秒，避免过度腰椎伸展。",
        "缓慢下放至起始位，不完全放松。",
    ],
    "Calf Raise": [
        "双脚前掌站于台阶边缘，脚跟悬空。",
        "持哑铃或杠铃增加负荷。",
        "踮脚尖提踵至最高点，感受小腿顶峰收缩。",
        "缓慢下放让脚跟略低于台阶感受拉伸。",
        "每组 15–20 次效果更好，强调顶峰收缩。",
    ],
    "Good Morning": [
        "杠铃置于上背部（同深蹲位置），站姿与肩同宽。",
        "膝盖微屈固定角度，屈髋向前俯身。",
        "保持脊柱中立，背部呈一条直线（不弓背）。",
        "俯身至躯干近平行地面，感受腘绳肌拉伸。",
        "收紧臀肌与腘绳肌伸髋回到直立位。",
    ],
    "Back Extension": [
        "俯卧于罗马椅，脚踝固定，髋部卡于垫缘。",
        "双手交叉胸前或抱头，起始位躯干向下。",
        "收紧腰部竖脊肌将上身抬起至躯干与腿成一直线。",
        "避免过度伸展至后仰压迫腰椎。",
        "缓慢下放至起始位，动作匀速控制。",
    ],
    "Plank": [
        "俯撑地面，肘部垂直于肩下，前臂平放。",
        "脚尖着地，身体从头到脚踝呈一条直线。",
        "核心绷紧、臀肌收缩，避免塌腰或翘臀。",
        "目视地面保持颈椎中立，呼吸平稳。",
        "保持 30–60 秒，按能力延长时间。",
    ],
    "Crunch": [
        "仰卧屈膝，双脚贴地，双手抱头或交叉胸前。",
        "用腹直肌发力卷起肩胛骨离地约 30°。",
        "顶点挤压腹肌 1 秒后缓慢下放。",
        "不要用颈部发力或扯颈部。",
        "脊柱下段始终贴紧地面。",
    ],
    "Hanging Leg Raise": [
        "双手握单杠悬垂，肩胛下沉激活。",
        "核心绷紧，屈髋向前将腿抬起（初学可屈膝）。",
        "抬至大腿与地面平行或更高，感受下腹收缩。",
        "缓慢控制下放，避免摆动借力。",
        "切勿借惯性晃动躯干。",
    ],
    "Russian Twist": [
        "坐姿屈膝，脚跟轻触地或抬起增加难度。",
        "躯干后倾约 45°，脊柱中立不弓背。",
        "双手合拢或持重物在腹前。",
        "转动躯干将重物碰触身体两侧地面。",
        "用腹斜肌发力，切勿仅移动手臂。",
    ],
    "Wrist Curl": [
        "坐姿前臂置于大腿或长凳，手腕悬空。",
        "正握或反握哑铃，掌心朝上（掌心朝下训练伸腕肌）。",
        "仅手腕做屈伸动作，前臂始终不动。",
        "用前臂屈肌卷起至最高点，顶点保持 1 秒。",
        "重量偏轻，每组 15–20 次。",
    ],
    # 热身 / 激活 / 冷身动作
    "Glute Bridge": [
        "仰卧屈膝，双脚与髋同宽踏地。",
        "双臂置于体侧，肩胛贴地。",
        "收紧臀肌将髋部抬起至躯干与大腿成一条直线。",
        "顶点保持 1 秒后缓慢下放。",
        "全程腹部和臀部协同发力。",
    ],
    "Bird Dog": [
        "四点跪姿（双手、双膝撑地），脊柱中立。",
        "同时伸直对侧手臂和腿至平行地面。",
        "保持 1–2 秒，核心绷紧不晃动。",
        "缓慢回到起始位换另一侧。",
        "目的是训练核心抗旋转与动态稳定。",
    ],
    "Cat-Cow Stretch": [
        "四点跪姿开始，双手位于肩正下方，双膝位于髋下。",
        "猫式：拱背抬腹、低头呼气。",
        "牛式：塌腰沉腹、抬头吸气。",
        "两个姿势间缓慢交替 10–12 次。",
        "重点是脊柱节律性的屈伸流动。",
    ],
    "Light Treadmill Walk": [
        "跑步机速度设为轻松步行（约 4–5 km/h）。",
        "保持躯干直立，自然摆臂。",
        "持续 5 分钟，心率轻微上升即可。",
        "落地时脚跟先着地再过渡到前掌。",
        "为正式训练升高体温、润滑关节。",
    ],
    "Jumping Jacks": [
        "站姿双脚并拢，双臂自然垂于体侧。",
        "跳起同时双脚外展、双臂举过头顶击掌。",
        "再跳起回到起始位，保持节奏平稳。",
        "落地时膝盖微屈缓冲，避免僵硬着地。",
        "全程核心收紧，呼吸均匀。",
    ],
    "Arm Circles": [
        "站姿双脚与肩同宽，双臂侧平举。",
        "以肩关节为轴画小圈，先向前再向后。",
        "每方向 15–20 次，圈幅由小到大。",
        "肩胛下沉，避免耸肩。",
        "感受肩袖与三角肌轻度激活。",
    ],
    "Leg Swings": [
        "单手扶墙保持平衡，核心收紧。",
        "支撑腿微屈，摆动腿放松前后摆荡。",
        "摆幅逐渐增大，但不超过舒适范围。",
        "每侧 15 次，控制不借腰代偿。",
        "激活髋屈肌与腘绳肌，为下肢训练做准备。",
    ],
    "Hip Circles": [
        "站姿双手叉腰或扶固定物，单腿微抬。",
        "以髋关节为轴画圈，先顺时针再逆时针。",
        "每侧 10 圈，动作缓慢有控制。",
        "躯干保持稳定，不随腿晃动。",
        "提升髋关节活动度。",
    ],
    "Bodyweight Good Morning": [
        "站姿双手交叉胸前或置于脑后。",
        "双脚与髋同宽，膝盖微屈固定。",
        "屈髋向前俯身，保持脊柱中立。",
        "感受腘绳肌拉伸后收紧臀肌回位。",
        "无负重版本，适合热身激活后链。",
    ],
    "Dead Bug": [
        "仰卧，双臂指向天花板，双膝屈 90°。",
        "下背贴地，核心收紧。",
        "对侧手脚同时缓慢下放至接近地面。",
        "回到起始位换另一侧，避免腰部拱起。",
        "训练腹横肌与抗伸展能力。",
    ],
    "Band Pull-Apart": [
        "双手握弹力带于胸前，与肩同宽。",
        "双臂伸直前伸，肩胛下沉。",
        "向两侧拉开弹力带至胸前，肘部微屈。",
        "顶点夹紧肩胛后缩，缓慢回位。",
        "激活三角肌后束与菱形肌。",
    ],
    "Clamshells": [
        "侧卧屈膝，双脚并拢，头可枕手臂。",
        "保持脚跟接触，上侧膝向外打开如蚌壳。",
        "顶点挤压臀中肌 1 秒，缓慢合上。",
        "每侧 15 次，骨盆不后仰。",
        "强化髋外展肌群，稳定膝关节。",
    ],
    "Scapular Push-Ups": [
        "俯卧撑起始位，手臂伸直，身体呈直线。",
        "不弯肘，仅通过肩胛骨内收与外展移动躯干。",
        "下放时肩胛靠拢，推起时肩胛分开。",
        "动作幅度可控，核心始终绷紧。",
        "激活前锯肌与肩胛稳定肌群。",
    ],
    "Static Quad Stretch": [
        "站姿单腿站立，可扶墙保持平衡。",
        "屈膝将脚跟拉向臀部，同侧手抓脚踝。",
        "膝盖指向地面，骨盆中立不前倾。",
        "保持 30 秒，感受股四头肌拉伸。",
        "换另一侧重复。",
    ],
    "Hamstring Stretch": [
        "坐姿一腿伸直，另一腿屈膝脚贴大腿内侧。",
        "躯干从髋部前倾，双手伸向脚尖方向。",
        "保持背部平直，不要弓背。",
        "伸直腿后侧有明显拉伸感，保持 30 秒。",
        "换腿重复。",
    ],
    "Chest Doorway Stretch": [
        "站在门框旁，前臂贴门框，肘部与肩同高。",
        "一脚向前迈出，身体缓慢前倾。",
        "感受胸大肌与前三角肌拉伸。",
        "保持 30 秒，避免肩关节过度外旋疼痛。",
        "换另一侧手臂重复。",
    ],
    "Child's Pose": [
        "跪姿，臀部坐向脚跟，双臂向前伸展。",
        "额头轻触地面，放松肩颈。",
        "深呼吸，感受背部与髋部拉伸。",
        "保持 60 秒，促进副交感神经放松。",
        "训练后用于降低心率。",
    ],
    "Supine Twist": [
        "仰卧双臂侧平举呈 T 形。",
        "屈膝抬起，双膝倒向一侧，头转向对侧。",
        "双肩尽量贴地，感受脊柱旋转拉伸。",
        "保持 30 秒，缓慢回正换边。",
        "放松竖脊肌与腹斜肌。",
    ],
    "Foam Rolling - Full Body": [
        "选择泡沫轴，从大块肌群开始（背、腿）。",
        "以自身重量缓慢滚动，避开骨骼突起与关节。",
        "遇紧张点停留 20–30 秒，配合深呼吸。",
        "每部位 30–60 秒，全程控制疼痛在可忍受范围。",
        "训练后使用可促进恢复、缓解酸痛。",
    ],
}


def image_url(exercise_name: str) -> str | None:
    """返回动作对应的示意图 URL；若未录入则返回 None。"""
    path = _IMG_MAP.get(exercise_name)
    return f"{_IMG_BASE}{path}" if path else None


def animation_frames(exercise_name: str) -> list[str]:
    """返回起止位双帧图片 URL，前端可轮播模拟动图效果。"""
    path = _IMG_MAP.get(exercise_name)
    if not path:
        return []
    folder = path.rsplit("/", 1)[0]
    return [f"{_IMG_BASE}{folder}/0.jpg", f"{_IMG_BASE}{folder}/1.jpg"]


def technique_cn(exercise_name: str) -> list[str]:
    """返回动作的中文技术要领列表；若未录入则返回空列表。"""
    return _TECHNIQUE.get(exercise_name, [])


def has_meta(exercise_name: str) -> bool:
    return exercise_name in _IMG_MAP or exercise_name in _TECHNIQUE


def guide_for(exercise_name: str) -> dict:
    """返回单个动作的完整教程元数据（图片/动图帧/文字要领）。"""
    frames = animation_frames(exercise_name)
    tech = technique_cn(exercise_name)
    img = image_url(exercise_name)
    return {
        "name": exercise_name,
        "image_url": img,
        "animation_frames": frames,
        "technique_cn": tech,
        "has_guide": bool(frames or tech),
    }


def all_guides() -> dict[str, dict]:
    """返回所有已录入动作教程的字典，键为动作英文名。"""
    names = sorted(set(_IMG_MAP) | set(_TECHNIQUE))
    return {name: guide_for(name) for name in names}


def guided_exercise_names() -> frozenset[str]:
    """所有保证有动图教程的动作名称集合。"""
    return frozenset(_IMG_MAP.keys())


def sanitize_exercise_name(name: str, fallback_pool: list[str] | None = None) -> str:
    """确保动作名对应已录入教程；否则从备选池选取有教程的动作。"""
    if name in _IMG_MAP:
        return name
    pool = fallback_pool or []
    for candidate in pool:
        if candidate in _IMG_MAP:
            return candidate
    for guided in sorted(_IMG_MAP):
        if guided.lower() == (name or "").lower():
            return guided
    return sorted(_IMG_MAP)[0]


def sanitize_workout_phases(phases: dict, safe_exercises: list[str] | None = None) -> dict:
    """校正训练计划各阶段动作名，保证均有动图教程。"""
    pool = list(safe_exercises or []) + list(_IMG_MAP.keys())
    out = dict(phases)
    for phase_key, exercises in phases.items():
        if not isinstance(exercises, list):
            continue
        sanitized = []
        for ex in exercises:
            if not isinstance(ex, dict):
                sanitized.append(ex)
                continue
            item = dict(ex)
            item["name"] = sanitize_exercise_name(item.get("name", ""), pool)
            sanitized.append(item)
        out[phase_key] = sanitized
    return out


def sanitize_program_weeks(weeks: list, safe_exercises: list[str] | None = None) -> list:
    """校正周期训练计划中所有 key_exercises 的动作名。"""
    pool = list(safe_exercises or []) + list(_IMG_MAP.keys())
    out = []
    for week in weeks:
        wk = dict(week)
        sessions = []
        for session in week.get("sessions") or []:
            sess = dict(session)
            exercises = []
            for ex in session.get("key_exercises") or []:
                item = dict(ex)
                item["name"] = sanitize_exercise_name(item.get("name", ""), pool)
                exercises.append(item)
            sess["key_exercises"] = exercises
            sessions.append(sess)
        wk["sessions"] = sessions
        out.append(wk)
    return out
