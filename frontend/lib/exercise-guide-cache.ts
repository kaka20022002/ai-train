/**
 * Exercise guide metadata cache
 * Bulk-fetches all guides once and shares across components.
 */
import { exercisesApi, type ExerciseGuideMeta } from "@/lib/api";

let cache: Record<string, ExerciseGuideMeta> | null = null;
let loading: Promise<Record<string, ExerciseGuideMeta>> | null = null;

export async function getExerciseGuides(): Promise<Record<string, ExerciseGuideMeta>> {
  if (cache) return cache;
  if (!loading) {
    loading = exercisesApi
      .guideMeta()
      .then((res) => {
        cache = res.guides ?? {};
        return cache;
      })
      .catch(() => {
        cache = {};
        return cache!;
      });
  }
  return loading;
}

export function getCachedGuide(name: string): ExerciseGuideMeta | null {
  return cache?.[name] ?? null;
}
