import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios from "axios";

const DD_API_KEY = process.env.DD_API_KEY || "";
const DD_APP_KEY = process.env.DD_APP_KEY || "";
const DD_SITE = process.env.DD_SITE || "datadoghq.com";

const v1 = axios.create({
  baseURL: `https://api.${DD_SITE}/api/v1`,
  headers: { "DD-API-KEY": DD_API_KEY, "DD-APPLICATION-KEY": DD_APP_KEY },
});

const v2 = axios.create({
  baseURL: `https://api.${DD_SITE}/api/v2`,
  headers: { "DD-API-KEY": DD_API_KEY, "DD-APPLICATION-KEY": DD_APP_KEY },
});

const server = new Server(
  { name: "datadog-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "query_metrics",
      description: "Query DataDog metrics using a metric query",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Datadog metrics query e.g. avg:system.cpu.user{*}" },
          from_ts: { type: "number", description: "Unix timestamp start (default: 1 hour ago)" },
          to_ts: { type: "number", description: "Unix timestamp end (default: now)" },
        },
        required: ["query"],
      },
    },
    {
      name: "get_logs",
      description: "Search DataDog logs",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Log search query" },
          from: { type: "string", description: "ISO 8601 start time (default: 1h ago)" },
          to: { type: "string", description: "ISO 8601 end time (default: now)" },
          limit: { type: "number", default: 50 },
        },
        required: ["query"],
      },
    },
    {
      name: "list_monitors",
      description: "List DataDog monitors and their current state",
      inputSchema: {
        type: "object",
        properties: {
          tags: { type: "array", items: { type: "string" } },
          name_filter: { type: "string" },
        },
      },
    },
    {
      name: "get_monitor",
      description: "Get details of a specific DataDog monitor",
      inputSchema: {
        type: "object",
        properties: {
          monitor_id: { type: "number" },
        },
        required: ["monitor_id"],
      },
    },
    {
      name: "mute_monitor",
      description: "Mute a DataDog monitor for a duration",
      inputSchema: {
        type: "object",
        properties: {
          monitor_id: { type: "number" },
          end_ts: { type: "number", description: "Unix timestamp when mute expires" },
        },
        required: ["monitor_id"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "query_metrics": {
        const now = Math.floor(Date.now() / 1000);
        const { data } = await v1.get("/query", {
          params: {
            from: Number(args?.from_ts) || now - 3600,
            to: Number(args?.to_ts) || now,
            query: String(args!.query),
          },
        });
        const series = (data.series || []).map((s: any) => ({
          metric: s.metric,
          points: (s.pointlist || []).slice(-10).map(([t, v]: [number, number]) => ({
            t,
            v: Math.round(v * 100) / 100,
          })),
        }));
        return { content: [{ type: "text", text: JSON.stringify(series, null, 2) }] };
      }

      case "get_logs": {
        const now = new Date();
        const { data } = await v2.post("/logs/events/search", {
          filter: {
            query: String(args!.query),
            from: String(args?.from || new Date(now.getTime() - 3600000).toISOString()),
            to: String(args?.to || now.toISOString()),
          },
          sort: "timestamp",
          page: { limit: Number(args?.limit || 50) },
        });
        const logs = (data.data || []).map((l: any) => ({
          timestamp: l.attributes?.timestamp,
          service: l.attributes?.service,
          status: l.attributes?.status,
          message: (l.attributes?.message || "").substring(0, 200),
        }));
        return { content: [{ type: "text", text: `${logs.length} logs:\n${JSON.stringify(logs, null, 2)}` }] };
      }

      case "list_monitors": {
        const params: Record<string, string> = {};
        if (args?.tags) params.monitor_tags = (args.tags as string[]).join(",");
        if (args?.name_filter) params.name = String(args.name_filter);
        const { data } = await v1.get("/monitor", { params });
        const formatted = (data || []).slice(0, 30).map((m: any) => ({
          id: m.id,
          name: m.name,
          type: m.type,
          overall_state: m.overall_state,
          tags: m.tags,
        }));
        return { content: [{ type: "text", text: JSON.stringify(formatted, null, 2) }] };
      }

      case "get_monitor": {
        const { data: m } = await v1.get(`/monitor/${Number(args!.monitor_id)}`);
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              id: m.id, name: m.name, type: m.type, overall_state: m.overall_state,
              query: m.query, message: m.message, tags: m.tags,
            }, null, 2),
          }],
        };
      }

      case "mute_monitor": {
        const body: Record<string, number> = {};
        if (args?.end_ts) body.end = Number(args.end_ts);
        await v1.post(`/monitor/${Number(args!.monitor_id)}/mute`, body);
        return { content: [{ type: "text", text: `Monitor ${args!.monitor_id} muted` }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("DataDog MCP server running");
}

main().catch(console.error);
