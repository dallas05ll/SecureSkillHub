export type TierLetter = "S" | "A" | "B" | "C" | "D" | "E";

export function computeTier(score: number): TierLetter {
  if (score >= 10000) return "S";
  if (score >= 1000) return "A";
  if (score >= 100) return "B";
  if (score >= 10) return "C";
  if (score >= 1) return "D";
  return "E";
}

export function computeScore(stars: number, installs: number): number {
  return Math.max(stars || 0, installs || 0);
}
