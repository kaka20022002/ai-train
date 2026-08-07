"use client";

import { EQUIPMENT_LIST, EQUIPMENT_CN, EQUIPMENT_PRESETS } from "@/lib/constants";

interface Props {
  selected: string[];
  onChange: (equipment: string[]) => void;
}

export function EquipmentSelector({ selected, onChange }: Props) {
  const toggle = (item: string) => {
    onChange(
      selected.includes(item)
        ? selected.filter((e) => e !== item)
        : [...selected, item]
    );
  };

  const activePreset = EQUIPMENT_PRESETS.find(
    (p) =>
      p.equipment.length === selected.length &&
      p.equipment.every((e) => selected.includes(e))
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Presets */}
      <div className="flex flex-wrap gap-2">
        {EQUIPMENT_PRESETS.map((preset) => {
          const active = activePreset?.id === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              onClick={() => onChange([...preset.equipment])}
              className="text-xs px-3 py-1.5 rounded-lg border transition-colors"
              style={{
                borderColor: active ? "var(--accent)" : "var(--border)",
                background: active ? "var(--accent)" : "var(--surface2)",
                color: active ? "#fff" : "var(--text-muted)",
              }}
            >
              {preset.label}
            </button>
          );
        })}
      </div>

      {/* Individual toggles */}
      <div className="grid grid-cols-3 gap-2">
        {EQUIPMENT_LIST.map((item) => {
          const active = selected.includes(item);
          return (
            <button
              key={item}
              type="button"
              onClick={() => toggle(item)}
              className="text-xs px-3 py-2 rounded-lg border transition-colors text-left"
              style={{
                borderColor: active ? "var(--accent)" : "var(--border)",
                background: active ? "rgba(108,99,255,0.12)" : "var(--surface2)",
                color: active ? "var(--accent-light)" : "var(--text-muted)",
              }}
            >
              {active ? "✓ " : ""}{EQUIPMENT_CN[item]}
            </button>
          );
        })}
      </div>

      <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
        {selected.length === 0
          ? "未限制 → 默认全器材可用"
          : `已选 ${selected.filter((e) => e !== "bodyweight").length} 项器材（自重动作始终可用）`}
      </p>
    </div>
  );
}
