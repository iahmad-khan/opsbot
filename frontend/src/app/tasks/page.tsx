"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { ClipboardList } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
  running: "bg-blue-900 text-blue-300 animate-pulse",
  waiting_approval: "bg-yellow-900 text-yellow-300",
  pending: "bg-gray-700 text-gray-300",
  denied: "bg-red-900 text-red-400",
  timed_out: "bg-gray-700 text-gray-400",
};

export default function TasksPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const { data, isLoading, error } = useSWR(
    ["/tasks", page, statusFilter],
    () => api.getTasks({ page: String(page), page_size: "25", ...(statusFilter ? { status: statusFilter } : {}) }),
    { refreshInterval: 5000 }
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Task History</h1>
        <div className="flex gap-2">
          <select
            className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="running">Running</option>
            <option value="waiting_approval">Waiting Approval</option>
            <option value="denied">Denied</option>
          </select>
        </div>
      </div>

      {isLoading && <div className="text-gray-400">Loading tasks...</div>}
      {error && <div className="text-red-400">Error: {error.message}</div>}

      {data?.total !== undefined && (
        <p className="text-sm text-gray-400">{data.total} tasks total</p>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
              <th className="text-left px-4 py-3">Request</th>
              <th className="text-left px-4 py-3">Tool</th>
              <th className="text-left px-4 py-3">User</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Time</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items || []).map((task: any) => (
              <tr key={task.id} className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
                <td className="px-4 py-3">
                  <p className="text-white truncate max-w-xs" title={task.original_message}>
                    {task.original_message}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <code className="text-xs text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                    {task.tool_name || "—"}
                  </code>
                </td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                  @{task.requester_slack_id}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[task.status] || "bg-gray-700 text-gray-300"}`}>
                    {task.status?.replace("_", " ")}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {new Date(task.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(!data?.items || data.items.length === 0) && !isLoading && (
          <div className="text-center py-10 text-gray-500">
            <ClipboardList className="h-10 w-10 mx-auto mb-2 opacity-30" />
            No tasks found
          </div>
        )}
      </div>

      {/* Pagination */}
      {data && data.total > 25 && (
        <div className="flex justify-end gap-2">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 rounded bg-gray-800 text-sm text-white disabled:opacity-40"
          >
            ← Prev
          </button>
          <span className="px-3 py-1.5 text-sm text-gray-400">Page {page}</span>
          <button
            onClick={() => setPage(page + 1)}
            disabled={page * 25 >= data.total}
            className="px-3 py-1.5 rounded bg-gray-800 text-sm text-white disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
