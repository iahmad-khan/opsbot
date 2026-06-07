import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios from "axios";

const PROMETHEUS_URL = process.env.PROMETHEUS_URL || "http://localhost:9090";
const ALERTMANAGER_URL = PROMETHEUS_URL.replace("9090", "9093");

const client = axios.create({ baseURL: PROMETHEUS_URL, timeout: 30000 });
const amClient = axios.create({ baseURL: ALERTMANAGER_URL, timeout: 10000 });

const server = new Server(
  { name: "prometheus-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "query_metrics",
      description: "Execute a PromQL instant query",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "PromQL expression" },
          time: { type: "string", description: "RFC3339 timestamp (optional, defaults to now)" },
        },
        required: ["query"],
      },
    },
    {
      name: "query_range",
      description: "Execute a PromQL range query",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
          start: { type: "string", description: "Start time RFC3339 or relative like '1h'" },
          end: { type: "string", description: "End time RFC3339 (default: now)" },
          step: { type: "string", description: "Step duration e.g. 60s, 5m", default: "60s" },
          lookback_hours: { type: "number", default: 1 },
        },
        required: ["query"],
      },
    },
    {
      name: "list_alerts",
      description: "List active Prometheus alerts",
      inputSchema: {
        type: "object",
        properties: {
          state: { type: "string", enum: ["firing", "pending", "all"], default: "firing" },
        },
      },
    },
    {
      name: "list_rules",
      description: "List all Prometheus recording and alerting rules",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "list_targets",
      description: "List all Prometheus scrape targets and their health",
      inputSchema: {
        type: "object",
        properties: {
          state: { type: "string", enum: ["active", "dropped"], default: "active" },
        },
      },
    },
    {
      name: "silence_alert",
      description: "Silence a Prometheus alert via Alertmanager",
      inputSchema: {
        type: "object",
        properties: {
          matchers: {
            type: "array",
            items: {
              type: "object",
              properties: {
                name: { type: "string" },
                value: { type: "string" },
                isRegex: { type: "boolean", default: false },
              },
            },
          },
          duration_hours: { type: "number", default: 1 },
          comment: { type: "string" },
          author: { type: "string", default: "opsbot" },
        },
        required: ["matchers"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "query_metrics": {
        const params: Record<string, string> = { query: String(args!.query) };
        if (args?.time) params.time = String(args.time);
        const { data } = await client.get("/api/v1/query", { params });
        const result = data.data?.result || [];
        const formatted = result.slice(0, 20).map((r: any) => ({
          labels: r.metric,
          value: r.value?.[1],
          timestamp: r.value?.[0],
        }));
        return { content: [{ type: "text", text: JSON.stringify(formatted, null, 2) }] };
      }

      case "query_range": {
        const now = new Date();
        const lookbackMs = (Number(args?.lookback_hours) || 1) * 3600 * 1000;
        const params: Record<string, string> = {
          query: String(args!.query),
          start: String(args?.start || new Date(now.getTime() - lookbackMs).toISOString()),
          end: String(args?.end || now.toISOString()),
          step: String(args?.step || "60s"),
        };
        const { data } = await client.get("/api/v1/query_range", { params });
        const result = data.data?.result || [];
        // Summarize: last value + min/max for brevity
        const summarized = result.slice(0, 10).map((r: any) => {
          const values = (r.values || []).map(([t, v]: [number, string]) => parseFloat(v)).filter(isFinite);
          return {
            labels: r.metric,
            last_value: values[values.length - 1],
            min: values.length ? Math.min(...values) : null,
            max: values.length ? Math.max(...values) : null,
            avg: values.length ? values.reduce((a: number, b: number) => a + b, 0) / values.length : null,
            data_points: values.length,
          };
        });
        return { content: [{ type: "text", text: JSON.stringify(summarized, null, 2) }] };
      }

      case "list_alerts": {
        const { data } = await client.get("/api/v1/alerts");
        let alerts = data.data?.alerts || [];
        const state = String(args?.state || "firing");
        if (state !== "all") alerts = alerts.filter((a: any) => a.state === state);
        const formatted = alerts.map((a: any) => ({
          name: a.labels?.alertname,
          state: a.state,
          severity: a.labels?.severity,
          summary: a.annotations?.summary || "",
          since: a.activeAt,
          labels: a.labels,
        }));
        return { content: [{ type: "text", text: `Found ${formatted.length} ${state} alerts:\n${JSON.stringify(formatted, null, 2)}` }] };
      }

      case "list_rules": {
        const { data } = await client.get("/api/v1/rules");
        const groups = data.data?.groups || [];
        const rules = groups.flatMap((g: any) =>
          (g.rules || []).map((r: any) => ({
            name: r.name,
            type: r.type,
            group: g.name,
            query: r.query || r.expr,
            state: r.state,
          }))
        );
        return { content: [{ type: "text", text: `${rules.length} rules:\n${JSON.stringify(rules.slice(0, 30), null, 2)}` }] };
      }

      case "list_targets": {
        const { data } = await client.get("/api/v1/targets");
        const targets = data.data?.activeTargets || [];
        const formatted = targets.map((t: any) => ({
          job: t.labels?.job,
          instance: t.labels?.instance,
          health: t.health,
          lastScrape: t.lastScrape,
        }));
        return { content: [{ type: "text", text: JSON.stringify(formatted.slice(0, 30), null, 2) }] };
      }

      case "silence_alert": {
        const now = new Date();
        const durationHours = Number(args?.duration_hours || 1);
        const payload = {
          matchers: args!.matchers,
          startsAt: now.toISOString(),
          endsAt: new Date(now.getTime() + durationHours * 3600 * 1000).toISOString(),
          comment: String(args?.comment || "Silenced by OpsBot"),
          createdBy: String(args?.author || "opsbot"),
        };
        const { data } = await amClient.post("/api/v2/silences", payload);
        return { content: [{ type: "text", text: `✅ Alert silenced for ${durationHours}h. Silence ID: ${data.silenceID}` }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.error || err.message;
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Prometheus MCP server running");
}

main().catch(console.error);
