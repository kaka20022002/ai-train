import { useState } from "react";
import { View, Text, Input } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  type MedicalHistoryItem,
  type UserProfile,
} from "../../services/api";
import {
  EQUIPMENT_CN,
  EQUIPMENT_LIST,
  FITNESS_CN,
  GENDER_CN,
  GOAL_CN,
  INJURY_CONDITION_PRESETS,
  INJURY_LOCATIONS,
  JOINT_CN,
  SEVERITY_CN,
} from "../../utils/labels";
import "./index.scss";

interface InjuryDraft {
  location: string;
  condition: string;
  severity: string;
  /** 选「其他」时的自定义中文/英文描述 */
  customCondition?: string;
}

const emptyInjury = (): InjuryDraft => ({
  location: "knee",
  condition: "meniscus_tear",
  severity: "medium",
  customCondition: "",
});

function hydrateInjury(m: { location: string; condition: string; severity: string }): InjuryDraft {
  const known = INJURY_CONDITION_PRESETS.some((p) => p.value === m.condition);
  if (known) {
    return {
      location: m.location,
      condition: m.condition,
      severity: m.severity,
      customCondition: "",
    };
  }
  return {
    location: m.location,
    condition: "other",
    severity: m.severity,
    customCondition: m.condition,
  };
}

export default function ProfileEditPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(false);

  const [age, setAge] = useState("28");
  const [gender, setGender] = useState("male");
  const [height, setHeight] = useState("175");
  const [weight, setWeight] = useState("70");
  const [fitnessLevel, setFitnessLevel] = useState("beginner");
  const [fitnessGoal, setFitnessGoal] = useState("general_fitness");
  const [frequency, setFrequency] = useState("3");
  const [equipment, setEquipment] = useState<string[]>(["dumbbell", "bench"]);
  const [injuries, setInjuries] = useState<InjuryDraft[]>([]);

  const fillFromProfile = (p: UserProfile) => {
    setExists(true);
    setAge(String(p.basic_info?.age ?? 28));
    setGender(p.basic_info?.gender || "male");
    setHeight(String(p.basic_info?.height_cm ?? 175));
    setWeight(String(p.basic_info?.weight_kg ?? 70));
    setFitnessLevel(p.fitness_level || "beginner");
    setFitnessGoal(p.fitness_goal || "general_fitness");
    setFrequency(String(p.training_frequency ?? 3));
    setEquipment(p.available_equipment?.length ? [...p.available_equipment] : []);
    setInjuries(
      p.medical_history?.length
        ? p.medical_history.map((m) => hydrateInjury(m))
        : []
    );
  };

  useDidShow(() => {
    (async () => {
      setLoading(true);
      try {
        const uid = await ensureLoggedIn();
        try {
          const p = await api.getUser(uid);
          fillFromProfile(p);
        } catch {
          setExists(false);
        }
      } catch (e: any) {
        Taro.showToast({ title: e?.message?.slice(0, 40) || "加载失败", icon: "none" });
      } finally {
        setLoading(false);
      }
    })();
  });

  const toggleEquipment = (key: string) => {
    setEquipment((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]
    );
  };

  const updateInjury = (idx: number, patch: Partial<InjuryDraft>) => {
    setInjuries((prev) => prev.map((x, i) => (i === idx ? { ...x, ...patch } : x)));
  };

  const buildMedical = (): MedicalHistoryItem[] =>
    injuries
      .map((x) => {
        const condition =
          x.condition === "other"
            ? (x.customCondition || "").trim()
            : x.condition.trim();
        return {
          location: x.location,
          condition,
          severity: x.severity,
        };
      })
      .filter((x) => x.condition);

  const save = async () => {
    const ageN = Number(age);
    const heightN = Number(height);
    const weightN = Number(weight);
    const freqN = Number(frequency);
    if (!ageN || ageN < 10 || ageN > 90) {
      Taro.showToast({ title: "请填写合理年龄", icon: "none" });
      return;
    }
    if (!heightN || heightN < 100 || heightN > 250) {
      Taro.showToast({ title: "请填写合理身高(cm)", icon: "none" });
      return;
    }
    if (!weightN || weightN < 30 || weightN > 250) {
      Taro.showToast({ title: "请填写合理体重(kg)", icon: "none" });
      return;
    }

    setSaving(true);
    try {
      const uid = await ensureLoggedIn();
      const body = {
        basic_info: {
          age: ageN,
          gender,
          height_cm: heightN,
          weight_kg: weightN,
        },
        fitness_level: fitnessLevel,
        fitness_goal: fitnessGoal,
        training_frequency: freqN || 3,
        available_equipment: equipment,
        medical_history: buildMedical(),
      };

      let updated: UserProfile;
      if (exists) {
        updated = await api.updateUser(uid, body);
      } else {
        updated = await api.createUser({ user_id: uid, ...body });
        setExists(true);
      }

      const rv = updated.safety_revalidation;
      Taro.showToast({
        title: rv?.exercises_replaced
          ? `已保存，并替换 ${rv.exercises_replaced} 个高风险动作`
          : "档案已保存",
        icon: "success",
        duration: 2500,
      });
      setTimeout(() => Taro.navigateBack(), 600);
    } catch (e: any) {
      Taro.showToast({
        title: e?.message?.slice(0, 40) || "保存失败",
        icon: "none",
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View className="page">
        <View className="card">
          <Text className="muted">正在加载档案…</Text>
        </View>
      </View>
    );
  }

  const bmi =
    Number(height) > 0 && Number(weight) > 0
      ? (Number(weight) / (Number(height) / 100) ** 2).toFixed(1)
      : "—";

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">EDIT PROFILE</Text>
        <Text className="title">编辑档案</Text>
        <Text className="subtitle">身体数据、目标与伤病会直接影响计划与教练建议</Text>
      </View>

      <View className="card">
        <Text className="section-title">基础身体数据</Text>
        <Text className="field-label">年龄</Text>
        <Input className="input" type="number" value={age} onInput={(e) => setAge(e.detail.value)} />
        <Text className="field-label">性别</Text>
        <View className="chip-row">
          {Object.entries(GENDER_CN)
            .filter(([k]) => k !== "unknown")
            .map(([k, v]) => (
              <View
                key={k}
                className={gender === k ? "chip on" : "chip"}
                onClick={() => setGender(k)}
              >
                <Text>{v}</Text>
              </View>
            ))}
        </View>
        <Text className="field-label">身高 (cm)</Text>
        <Input
          className="input"
          type="digit"
          value={height}
          onInput={(e) => setHeight(e.detail.value)}
        />
        <Text className="field-label">体重 (kg)</Text>
        <Input
          className="input"
          type="digit"
          value={weight}
          onInput={(e) => setWeight(e.detail.value)}
        />
        <Text className="muted">估算 BMI：{bmi}</Text>
      </View>

      <View className="card">
        <Text className="section-title">健身水平与目标</Text>
        <Text className="field-label">水平</Text>
        <View className="chip-row">
          {Object.entries(FITNESS_CN).map(([k, v]) => (
            <View
              key={k}
              className={fitnessLevel === k ? "chip on" : "chip"}
              onClick={() => setFitnessLevel(k)}
            >
              <Text>{v}</Text>
            </View>
          ))}
        </View>
        <Text className="field-label">目标</Text>
        <View className="chip-row">
          {Object.entries(GOAL_CN).map(([k, v]) => (
            <View
              key={k}
              className={fitnessGoal === k ? "chip on" : "chip"}
              onClick={() => setFitnessGoal(k)}
            >
              <Text>{v}</Text>
            </View>
          ))}
        </View>
        <Text className="field-label">每周训练次数</Text>
        <View className="chip-row">
          {[2, 3, 4, 5, 6].map((n) => (
            <View
              key={n}
              className={frequency === String(n) ? "chip on" : "chip"}
              onClick={() => setFrequency(String(n))}
            >
              <Text>{n} 次</Text>
            </View>
          ))}
        </View>
      </View>

      <View className="card">
        <Text className="section-title">可用器械</Text>
        <View className="chip-row">
          {EQUIPMENT_LIST.map((key) => (
            <View
              key={key}
              className={equipment.includes(key) ? "chip on" : "chip"}
              onClick={() => toggleEquipment(key)}
            >
              <Text>{EQUIPMENT_CN[key] || key}</Text>
            </View>
          ))}
        </View>
      </View>

      <View className="card">
        <View className="row-between">
          <Text className="section-title">伤病史 / 身体状况</Text>
          <Text
            className="tag"
            onClick={() => setInjuries((prev) => [...prev, emptyInjury()])}
          >
            + 添加
          </Text>
        </View>
        {!injuries.length && <Text className="muted">暂无伤病，可点右上角添加</Text>}
        {injuries.map((inj, idx) => (
          <View className="injury-edit" key={idx}>
            <View className="row-between">
              <Text className="field-label">伤病 {idx + 1}</Text>
              <Text
                className="tag warn"
                onClick={() => setInjuries((prev) => prev.filter((_, i) => i !== idx))}
              >
                删除
              </Text>
            </View>
            <Text className="field-label">部位</Text>
            <View className="chip-row">
              {INJURY_LOCATIONS.map((loc) => (
                <View
                  key={loc}
                  className={inj.location === loc ? "chip on" : "chip"}
                  onClick={() => updateInjury(idx, { location: loc })}
                >
                  <Text>{JOINT_CN[loc]}</Text>
                </View>
              ))}
            </View>
            <Text className="field-label">严重程度</Text>
            <View className="chip-row">
              {Object.entries(SEVERITY_CN).map(([k, v]) => (
                <View
                  key={k}
                  className={inj.severity === k ? "chip on" : "chip"}
                  onClick={() => updateInjury(idx, { severity: k })}
                >
                  <Text>{v}</Text>
                </View>
              ))}
            </View>
            <Text className="field-label">情况描述</Text>
            <View className="chip-row">
              {INJURY_CONDITION_PRESETS.map((p) => (
                <View
                  key={p.value}
                  className={inj.condition === p.value ? "chip on" : "chip"}
                  onClick={() =>
                    updateInjury(idx, {
                      condition: p.value,
                      customCondition:
                        p.value === "other" ? inj.customCondition || "" : "",
                    })
                  }
                >
                  <Text>{p.label}</Text>
                </View>
              ))}
            </View>
            {inj.condition === "other" && (
              <Input
                className="input"
                value={inj.customCondition || ""}
                placeholder="请填写具体伤病情况"
                onInput={(e) =>
                  updateInjury(idx, { customCondition: e.detail.value })
                }
              />
            )}
          </View>
        ))}
      </View>

      <View className={`btn-primary ${saving ? "disabled" : ""}`} onClick={save}>
        <Text>{saving ? "保存中…" : "保存档案"}</Text>
      </View>
      <View className="btn-ghost stack-gap" onClick={() => Taro.navigateBack()}>
        <Text>取消</Text>
      </View>
    </View>
  );
}
