import type { components } from "./api/schema";

type EventState = components["schemas"]["EventState"];
type ClaimState = components["schemas"]["ClaimState"];
type Importance = components["schemas"]["BaseAnalysisImportance"];
type EvidenceVisibility = components["schemas"]["EvidenceVisibility"];

const eventStateLabels: Record<EventState, string> = {
  developing: "发展中",
  confirmed: "已确认",
  conflicting: "存在冲突",
  cooling: "降温中",
};

const claimStateLabels: Record<ClaimState, string> = {
  confirmed: "已确认",
  unresolved: "待确认",
  conflicting: "存在冲突",
  contradicted: "已反驳",
};

const importanceLabels: Record<Importance, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "关键",
};

const evidenceVisibilityLabels: Record<EvidenceVisibility, string> = {
  public: "公开",
  private_sanitized: "私密·已脱敏",
};

export function formatEventState(value: EventState) {
  return eventStateLabels[value];
}

export function formatClaimState(value: ClaimState) {
  return claimStateLabels[value];
}

export function formatImportance(value: Importance) {
  return importanceLabels[value];
}

export function formatEvidenceVisibility(value: EvidenceVisibility) {
  return evidenceVisibilityLabels[value];
}

export function formatUtcDateTime(value: string | null, missing = "时间未发布") {
  if (value === null) return missing;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}
