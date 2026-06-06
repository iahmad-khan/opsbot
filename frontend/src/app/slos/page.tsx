import { api } from "@/lib/api";
import { BarChart2, TrendingDown } from "lucide-react";

export default async function SLOsPage() {
  let sloReports: any = null;
  let rcaReports: any = null;
  try {
    [sloReports, rcaReports] = await Promise.all([api.getSLOReports(), api.getRCAReports()]);
  } catch {}

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">SLO Health</h1>
        <p className="text-gray-400 text-sm mt-1">Service Level Objectives and RCA reports</p>
      </div>

      {/* SLO Reports */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-4">
          <BarChart2 className="h-5 w-5 text-blue-400" />
          <h2 className="font-semibold text-white">SLO Analysis Reports</h2>
          <span className="text-xs text-gray-400 ml-auto">{sloReports?.reports?.length || 0} reports</span>
        </div>

        {sloReports?.reports?.length > 0 ? (
          <div className="space-y-2">
            {sloReports.reports.map((r: any) => (
              <div key={r.id} className="flex items-center justify-between py-2 px-3 rounded bg-gray-800">
                <div>
                  <span className="text-white text-sm font-medium">{r.service_name}</span>
                  <span className="text-gray-400 text-xs ml-3">{new Date(r.created_at).toLocaleDateString()}</span>
                </div>
                {r.github_pr_url && (
                  <a
                    href={r.github_pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    View PR →
                  </a>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            <BarChart2 className="h-10 w-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No SLO reports yet.</p>
            <p className="text-xs mt-1">Ask OpsBot: <code className="bg-gray-800 px-1 rounded">@opsbot analyze checkout-service and propose SLOs</code></p>
          </div>
        )}
      </div>

      {/* RCA Reports */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-4">
          <TrendingDown className="h-5 w-5 text-red-400" />
          <h2 className="font-semibold text-white">RCA Reports</h2>
          <span className="text-xs text-gray-400 ml-auto">{rcaReports?.reports?.length || 0} reports</span>
        </div>

        {rcaReports?.reports?.length > 0 ? (
          <div className="space-y-2">
            {rcaReports.reports.map((r: any) => (
              <div key={r.id} className="py-2 px-3 rounded bg-gray-800">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-white text-sm font-medium">{r.service_name || "Unknown service"}</span>
                  <span className="text-gray-400 text-xs">{new Date(r.created_at).toLocaleDateString()}</span>
                </div>
                {r.root_cause && (
                  <p className="text-gray-300 text-xs">{r.root_cause}</p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            <TrendingDown className="h-10 w-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No RCA reports yet.</p>
            <p className="text-xs mt-1">Ask OpsBot: <code className="bg-gray-800 px-1 rounded">@opsbot investigate the 5xx spike in payment-service</code></p>
          </div>
        )}
      </div>
    </div>
  );
}
