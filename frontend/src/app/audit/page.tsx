"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { ScrollText, CheckCircle, XCircle } from "lucide-react";

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [actorFilter, setActorFilter] = useState("");
  const { data, isLoading } = useSWR(
    ["/audit", page, actorFilter],
    () => api.getAuditLogs({
      page: String(page),
      page_size: "50",
      ...(actorFilter ? { actor_slack_id: actorFilter } : {}),
    }),
    { refreshInterval: 15000 }
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Audit Log</h1>
          <p className="text-gray-400 text-sm mt-1">All operations with actor, tool, and outcome</p>
        </div>
        <input
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-500 w-48"
          placeholder="Filter by Slack ID..."
          value={actorFilter}
          onChange={(e) => { setActorFilter(e.target.value); setPage(1); }}
        />
      </div>

      {data?.total !== undefined && (
        <p className="text-sm text-gray-400">{data.total} audit entries</p>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
              <th className="text-left px-4 py-3 w-6"></th>
              <th className="text-left px-4 py-3">Actor</th>
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3">Tool</th>
              <th className="text-left px-4 py-3">Risk</th>
              <th className="text-left px-4 py-3">Time</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items || []).map((log: any) => (
              <tr key={log.id} className="border-b border-gray-800 hover:bg-gray-800">
                <td className="px-4 py-3">
                  {log.success
                    ? <CheckCircle className="h-4 w-4 text-green-400" />
                    : <XCircle className="h-4 w-4 text-red-400" />
                  }
                </td>
                <td className="px-4 py-3 font-mono text-xs text-gray-300">@{log.actor_slack_id}</td>
                <td className="px-4 py-3 text-white text-xs">{log.action}</td>
                <td className="px-4 py-3">
                  <code className="text-xs text-gray-400 bg-gray-800 px-1 py-0.5 rounded">
                    {log.tool_name || "—"}
                  </code>
                </td>
                <td className="px-4 py-3">
                  {log.risk_level && (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      log.risk_level === "DESTRUCTIVE" ? "bg-red-900 text-red-300" :
                      log.risk_level === "WRITE" ? "bg-yellow-900 text-yellow-300" :
                      "bg-green-900 text-green-300"
                    }`}>
                      {log.risk_level}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                  {new Date(log.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(!data?.items || data.items.length === 0) && !isLoading && (
          <div className="text-center py-10 text-gray-500">
            <ScrollText className="h-10 w-10 mx-auto mb-2 opacity-30" />
            No audit entries found
          </div>
        )}
      </div>

      {data && data.total > 50 && (
        <div className="flex justify-end gap-2">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1}
            className="px-3 py-1.5 rounded bg-gray-800 text-sm text-white disabled:opacity-40">← Prev</button>
          <span className="px-3 py-1.5 text-sm text-gray-400">Page {page}</span>
          <button onClick={() => setPage(page + 1)} disabled={page * 50 >= data.total}
            className="px-3 py-1.5 rounded bg-gray-800 text-sm text-white disabled:opacity-40">Next →</button>
        </div>
      )}
    </div>
  );
}
