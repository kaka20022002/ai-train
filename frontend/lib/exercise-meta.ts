const IMG_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/";

const IMG_MAP: Record<string, string> = {
  "Barbell Back Squat": "Barbell_Full_Squat/0.jpg",
  "Front Squat": "Front_Barbell_Squat/0.jpg",
  "Conventional Deadlift": "Barbell_Deadlift/0.jpg",
  "Romanian Deadlift": "Romanian_Deadlift/0.jpg",
  "Sumo Deadlift": "Sumo_Deadlift/0.jpg",
  "Barbell Bench Press": "Barbell_Bench_Press_-_Medium_Grip/0.jpg",
  "Incline Dumbbell Press": "Incline_Dumbbell_Press/0.jpg",
  "Overhead Press": "Standing_Military_Press/0.jpg",
  "Arnold Press": "Arnold_Dumbbell_Press/0.jpg",
  "Lateral Raise": "Side_Lateral_Raise/0.jpg",
  "Barbell Row": "Bent_Over_Barbell_Row/0.jpg",
  "T-Bar Row": "T-Bar_Row_with_Handle/0.jpg",
  "Seated Cable Row": "Seated_Cable_Rows/0.jpg",
  "Lat Pulldown": "Wide-Grip_Lat_Pulldown/0.jpg",
  "Pull-Up": "Pullups/0.jpg",
  "Face Pull": "Face_Pull/0.jpg",
  "Barbell Curl": "Barbell_Curl/0.jpg",
  "Leg Press": "Leg_Press/0.jpg",
  "Leg Extension": "Leg_Extensions/0.jpg",
  "Leg Curl": "Seated_Leg_Curl/0.jpg",
  "Hip Thrust": "Barbell_Hip_Thrust/0.jpg",
  "Push-Up": "Pushups/0.jpg",
  "Plank": "Plank/0.jpg",
  "Good Morning": "Good_Morning/0.jpg",
  "Bulgarian Split Squat": "Dumbbell_Lunges/0.jpg",
};

export function exerciseImageUrl(name: string): string | null {
  const path = IMG_MAP[name];
  return path ? `${IMG_BASE}${path}` : null;
}
