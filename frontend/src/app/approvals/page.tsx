"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import { api } from "@/lib/api";
import { CheckSquare, XSquare, Clock, AlertTriangle } from "lucide-react";

const RISK_COLORS: Record<string, string> = {
  DESTRUCTIVE: "bg-red-900 text-red-300 border-red-700",
  WRITE: "bg-yellow-900 text-yellow-300 border-yellow-700",
  READ: "bg-green-900 text-green-300 border-green-700",
};

export default function ApprovalsPage() {
  const [approverSlackId, setApproverSlackId] = useState("U_APPROVER");
  const { data, isLoading, error } = useSWR("/approvals", () => api.getApprovals({ status: "pending" }), {
    refreshInterval: 10000,
  });

  const handleApprove = async (approvalId: string) => {
    try {
      await api.approveRequest(approvalId, approverSlackId);
      mutate("/approvals");
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
  };

  const handleDeny = async (approvalId: string) => {
    const reason = prompt("Reason for denying (optional):");
    try {
      await api.denyRequest(approvalId, approverSlackId, reason || "");
      mutate("/approvals");
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Approval Queue</h1>
          {data && (
            <p className="text-gray-400 text-sm mt-1">
              {data.pending_count} pending · {data.total} total
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-400">Your Slack ID:</label>
          <input
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white w-36"
            value={approverSlackId}
            onChange={(e) => setApproverSlackId(e.target.value)}
          />
        </div>
      </div>

      {isLoading && <div className="text-gray-400">Loading approvals...</div>}
      {error && <div className="text-red-400">Error loading approvals: {error.message}</div>}

      {data?.items?.length === 0 && !isLoading && (
        <div className="text-center py-16 text-gray-500">
          <CheckSquare className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>No pending approvals. Your team is all clear!</p>
        </div>
      )}

      <div className="space-y-3">
        {(data?.items || []).map((approval: any) => (
          <div
            key={approval.id}
            className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3"
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs px-2 py-0.5 rounded border ${RISK_COLORS[approval.risk_level] || "bg-gray-800 text-gray-300 border-gray-700"}`}>
                    {approval.risk_level}
                  </span>
                  <code className="text-xs bg-gray-800 px-2 py-0.5 rounded text-gray-300">
                    {approval.tool_name}
                  </code>
                </div>
                <p className="text-white text-sm font-medium">{approval.description}</p>
              </div>
              <div className="flex items-center gap-1 text-xs text-gray-400 ml-4">
                <Clock className="h-3 w-3" />
                {approval.expires_at
                  ? new Date(approval.expires_at).toLocaleString()
                  : "No expiry"}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-400">
                Requested by{" "}
                <span className="text-blue-400 font-mono">@{approval.requester_slack_id}</span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleDeny(approval.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-red-900 hover:bg-red-800 text-red-200 transition-colors"
                >
                  <XSquare className="h-4 w-4" />
                  Deny
                </button>
                <button
                  onClick={() => handleApprove(approval.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-green-700 hover:bg-green-600 text-white transition-colors"
                >
                  <CheckSquare className="h-4 w-4" />
                  Approve
                </button>
              </div>
            </div>

            {approval.tool_args && (
              <details className="text-xs">
                <summary className="text-gray-500 cursor-pointer hover:text-gray-400">View arguments</summary>
                <pre className="mt-2 bg-gray-800 rounded p-2 text-gray-300 overflow-x-auto">
                  {JSON.stringify(approval.tool_args, null, 2)}
                </pre>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
