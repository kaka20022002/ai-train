/** Boundary validation: reject unreadable responses before they reach the UI. */
import type { Connection, Overview, ReferencePlan } from "./api";

type ObjectValue = Record<string, unknown>;
const object = (value: unknown): value is ObjectValue =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) =>
  typeof value === "string" && value.trim().length > 0;
const positive = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value > 0;
const optionalNumber = (value: unknown, max = Infinity) =>
  value === null ||
  (typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= max);
const exercises = (value: unknown) =>
  Array.isArray(value) &&
  value.every(
    (item) =>
      object(item) &&
      text(item.name) &&
      positive(item.sets) &&
      (typeof item.reps === "string" || typeof item.reps === "number"),
  );
const reference = (value: unknown): boolean =>
  value === null ||
  (object(value) &&
    text(value.title) &&
    positive(value.source_week) &&
    exercises(value.key_exercises) &&
    (value.phases == null ||
      (object(value.phases) && Object.values(value.phases).every(exercises))));
const connection = (value: unknown): boolean =>
  object(value) &&
  text(value.id) &&
  text(value.device_name) &&
  positive(value.connected_at) &&
  reference(value.reference);
const pending = (value: unknown): boolean =>
  object(value) &&
  text(value.id) &&
  positive(value.expires_at) &&
  reference(value.reference);
const result = (value: unknown): boolean =>
  object(value) &&
  text(value.id) &&
  typeof value.started_at === "string" &&
  Number.isFinite(Date.parse(value.started_at)) &&
  typeof value.ended_at === "string" &&
  Number.isFinite(Date.parse(value.ended_at)) &&
  Date.parse(value.ended_at) >= Date.parse(value.started_at) &&
  positive(value.received_at) &&
  ["completed", "stopped"].includes(String(value.outcome)) &&
  Array.isArray(value.actions) &&
  value.actions.length > 0 &&
  value.actions.length <= 50 &&
  value.actions.every(
    (action) =>
      object(action) &&
      text(action.action_id) &&
      text(action.action_name) &&
      optionalNumber(action.completed_sets) &&
      optionalNumber(action.completed_reps) &&
      optionalNumber(action.duration_seconds) &&
      optionalNumber(action.quality_score_01, 1) &&
      optionalNumber(action.tracking_good_ratio_01, 1),
  );

function checked<T>(value: unknown, valid: boolean): T {
  if (!valid) throw new Error("服务返回的数据不完整，请刷新后重试。");
  return value as T;
}
export function parseOverview(value: unknown): Overview {
  return checked(
    value,
    object(value) &&
      (value.connection === null || connection(value.connection)) &&
      (value.pairing === null || pending(value.pairing)) &&
      reference(value.today_reference) &&
      Array.isArray(value.results) &&
      value.results.every(result),
  );
}
export function parseConnection(value: unknown): Connection {
  return checked(value, connection(value));
}
export function parsePairing(value: unknown): {
  id: string;
  code: string;
  expires_at: number;
  reference: ReferencePlan | null;
} {
  return checked(
    value,
    pending(value) &&
      object(value) &&
      typeof value.code === "string" &&
      /^[0-9]{6}$/.test(value.code),
  );
}
