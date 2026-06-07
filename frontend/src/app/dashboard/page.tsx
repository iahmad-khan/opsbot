import { api } from "@/lib/api";
import { CheckSquare, ClipboardList, Activity, AlertTriangle } from "lucide-react";

async function getData() {
  try {
    const [tasks, approvals, health] = await Promise.allSettled([
      api.getTasks({ page_size: "5" }),
      api.getApprovals({ status: "pending" }),
      api.getHealth(),
    ]);
    return {
      tasks: tasks.status === "fulfilled" ? tasks.value : null,
      approvals: approvals.status === "fulfilled" ? approvals.value : null,
      health: health.status === "fulfilled" ? health.value : null,
    };
  } catch {
    return { tasks: null, approvals: null, health: null };
  }
}

export default async function DashboardPage() {
  const { tasks, approvals, health } = await getData();

  const statsCards = [
    {
      label: "Pending Approvals",
      value: approvals?.pending_count ?? "—",
      icon: CheckSquare,
      color: approvals?.pending_count > 0 ? "text-yellow-400" : "text-green-400",
      href: "/approvals",
    },
    {
      label: "Total Tasks Today",
      value: tasks?.total ?? "—",
      icon: ClipboardList,
      color: "text-blue-400",
      href: "/tasks",
    },
    {
      label: "MCP Servers",
      value: health
        ? Object.values(health.mcp_servers || {}).filter((s) => s === "connected").length +
          "/" +
          Object.keys(health.mcp_servers || {}).length
        : "—",
      icon: Activity,
      color: "text-purple-400",
      href: "/dashboard",
    },
    {
      label: "Active Alerts",
      value: "—",
      icon: AlertTriangle,
      color: "text-red-400",
      href: "/slos",
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">
          {health?.environment ? `Environment: ${health.environment}` : "OpsBot overview"}
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statsCards.map((card) => (
          <a key={card.label} href={card.href} className="block">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-600 transition-colors">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-400">{card.label}</span>
                <card.icon className={`h-5 w-5 ${card.color}`} />
              </div>
              <div className={`text-2xl font-bold ${card.color}`}>{card.value}</div>
            </div>
          </a>
        ))}
      </div>

      {/* MCP Server Status */}
      {health?.mcp_servers && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="font-semibold text-white mb-3">MCP Server Status</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {Object.entries(health.mcp_servers).map(([name, status]) => (
              <div key={name} className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    status === "connected" ? "bg-green-400" : "bg-red-400"
                  }`}
                />
                <span className="text-sm text-gray-300">{name}</span>
                <span className={`text-xs ${status === "connected" ? "text-green-400" : "text-red-400"}`}>
                  {status as string}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Tasks */}
      {tasks?.items && tasks.items.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="font-semibold text-white mb-3">Recent Tasks</h2>
          <div className="space-y-2">
            {tasks.items.map((task: any) => (
              <a key={task.id} href={`/tasks/${task.id}`} className="block">
                <div className="flex items-center justify-between py-2 px-3 rounded hover:bg-gray-800 transition-colors">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{task.original_message}</p>
                    <p className="text-xs text-gray-400">
                      @{task.requester_slack_id} · {new Date(task.created_at).toLocaleString()}
                    </p>
                  </div>
                  <StatusBadge status={task.status} />
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: "bg-green-900 text-green-300",
    failed: "bg-red-900 text-red-300",
    running: "bg-blue-900 text-blue-300",
    waiting_approval: "bg-yellow-900 text-yellow-300",
    pending: "bg-gray-700 text-gray-300",
    denied: "bg-red-900 text-red-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[status] || "bg-gray-700 text-gray-300"}`}>
      {status.replace("_", " ")}
    </span>
  );
}
