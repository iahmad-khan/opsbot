const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json();
}

export const api = {
  // Tasks
  getTasks: (params?: Record<string, string>) =>
    apiFetch<any>(`/tasks?${new URLSearchParams(params || {})}`),
  getTask: (id: string) => apiFetch<any>(`/tasks/${id}`),
  getTaskAudit: (id: string) => apiFetch<any>(`/tasks/${id}/audit`),
  getAuditLogs: (params?: Record<string, string>) =>
    apiFetch<any>(`/tasks/audit/all?${new URLSearchParams(params || {})}`),

  // Approvals
  getApprovals: (params?: Record<string, string>) =>
    apiFetch<any>(`/approvals?${new URLSearchParams(params || {})}`),
  getApproval: (id: string) => apiFetch<any>(`/approvals/${id}`),
  approveRequest: (id: string, approverSlackId: string) =>
    apiFetch<any>(`/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approver_slack_id: approverSlackId }),
    }),
  denyRequest: (id: string, approverSlackId: string, reason?: string) =>
    apiFetch<any>(`/approvals/${id}/deny`, {
      method: "POST",
      body: JSON.stringify({ approver_slack_id: approverSlackId, denial_reason: reason }),
    }),

  // Health
  getHealth: () => apiFetch<any>("/health"),

  // SRE
  getSLOReports: (serviceName?: string) =>
    apiFetch<any>(`/sre/slo-reports${serviceName ? `?service_name=${serviceName}` : ""}`),
  getRCAReports: (serviceName?: string) =>
    apiFetch<any>(`/sre/rca-reports${serviceName ? `?service_name=${serviceName}` : ""}`),
};
