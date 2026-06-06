import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";
import { z } from "zod";

const ARGOCD_SERVER = process.env.ARGOCD_SERVER || "";
const ARGOCD_TOKEN = process.env.ARGOCD_TOKEN || "";
const ARGOCD_INSECURE = process.env.ARGOCD_INSECURE === "true";

function createClient(): AxiosInstance {
  return axios.create({
    baseURL: `${ARGOCD_SERVER}/api/v1`,
    headers: { Authorization: `Bearer ${ARGOCD_TOKEN}` },
    httpsAgent: ARGOCD_INSECURE
      ? new (require("https").Agent)({ rejectUnauthorized: false })
      : undefined,
    timeout: 30000,
  });
}

const server = new Server(
  { name: "argocd-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "list_apps",
      description: "List all ArgoCD applications",
      inputSchema: {
        type: "object",
        properties: {
          namespace: { type: "string", description: "App namespace filter" },
        },
      },
    },
    {
      name: "get_app",
      description: "Get detailed status of an ArgoCD application",
      inputSchema: {
        type: "object",
        properties: {
          app_name: { type: "string", description: "Application name" },
        },
        required: ["app_name"],
      },
    },
    {
      name: "sync_app",
      description: "Trigger a sync for an ArgoCD application",
      inputSchema: {
        type: "object",
        properties: {
          app_name: { type: "string" },
          revision: { type: "string" },
          prune: { type: "boolean", default: false },
          dry_run: { type: "boolean", default: false },
        },
        required: ["app_name"],
      },
    },
    {
      name: "rollback_app",
      description: "Rollback an ArgoCD application to a previous revision",
      inputSchema: {
        type: "object",
        properties: {
          app_name: { type: "string" },
          revision_id: { type: "number", description: "History revision ID (from get_app_history)" },
        },
        required: ["app_name", "revision_id"],
      },
    },
    {
      name: "get_app_history",
      description: "Get deployment history for an ArgoCD application",
      inputSchema: {
        type: "object",
        properties: {
          app_name: { type: "string" },
        },
        required: ["app_name"],
      },
    },
    {
      name: "refresh_app",
      description: "Refresh an ArgoCD application (re-fetch from source)",
      inputSchema: {
        type: "object",
        properties: {
          app_name: { type: "string" },
          hard: { type: "boolean", default: false },
        },
        required: ["app_name"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const client = createClient();

  try {
    switch (name) {
      case "list_apps": {
        const params: Record<string, string> = {};
        if (args?.namespace) params["appNamespace"] = String(args.namespace);
        const { data } = await client.get("/applications", { params });
        const apps = (data.items || []).map((a: any) => ({
          name: a.metadata.name,
          syncStatus: a.status.sync.status,
          healthStatus: a.status.health.status,
          revision: (a.status.sync.revision || "").substring(0, 8),
          source: a.spec?.source?.repoURL,
        }));
        return { content: [{ type: "text", text: JSON.stringify(apps, null, 2) }] };
      }

      case "get_app": {
        const { data } = await client.get(`/applications/${args!.app_name}`);
        const summary = {
          name: data.metadata.name,
          syncStatus: data.status.sync.status,
          healthStatus: data.status.health.status,
          revision: data.status.sync.revision,
          images: data.status?.summary?.images || [],
          conditions: data.status?.conditions || [],
          operationState: data.status?.operationState?.phase,
        };
        return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
      }

      case "sync_app": {
        const payload: Record<string, any> = {};
        if (args?.revision) payload.revision = args.revision;
        if (args?.prune) payload.prune = true;
        if (args?.dry_run) payload.dryRun = true;
        await client.post(`/applications/${args!.app_name}/sync`, payload);
        return { content: [{ type: "text", text: `✅ Sync triggered for ${args!.app_name}${args?.dry_run ? " (dry run)" : ""}` }] };
      }

      case "rollback_app": {
        await client.post(`/applications/${args!.app_name}/rollback`, { id: Number(args!.revision_id) });
        return { content: [{ type: "text", text: `✅ Rollback triggered for ${args!.app_name} to revision ${args!.revision_id}` }] };
      }

      case "get_app_history": {
        const { data } = await client.get(`/applications/${args!.app_name}/revisions`);
        const history = (data.items || []).slice(0, 10).map((h: any) => ({
          id: h.id,
          revision: (h.revision || "").substring(0, 8),
          deployedAt: h.deployedAt,
          initiatedBy: h.initiatedBy?.username,
        }));
        return { content: [{ type: "text", text: JSON.stringify(history, null, 2) }] };
      }

      case "refresh_app": {
        const params = { refresh: args?.hard ? "hard" : "normal" };
        await client.get(`/applications/${args!.app_name}`, { params });
        return { content: [{ type: "text", text: `✅ ${args!.app_name} refreshed` }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.message || err.message;
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("ArgoCD MCP server running");
}

main().catch(console.error);
