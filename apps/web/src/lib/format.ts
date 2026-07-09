import { TERMINAL_CASE_STATUSES, type CaseStatus } from "./types";

export function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function isTerminalStatus(status: CaseStatus): boolean {
  return TERMINAL_CASE_STATUSES.has(status);
}
