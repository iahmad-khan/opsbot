import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";

// Cloud:  CONFLUENCE_URL=https://yoursite.atlassian.net/wiki
// Server: CONFLUENCE_URL=https://confluence.yourcompany.com
const CONFLUENCE_URL = (process.env.CONFLUENCE_URL || "").replace(/\/$/, "");
const CONFLUENCE_USERNAME = process.env.CONFLUENCE_USERNAME || process.env.CONFLUENCE_EMAIL || "";
const CONFLUENCE_TOKEN = process.env.CONFLUENCE_API_TOKEN || process.env.CONFLUENCE_PASSWORD || "";
const DEFAULT_SPACE = process.env.CONFLUENCE_DEFAULT_SPACE || "";

function createClient(): AxiosInstance {
  const creds = Buffer.from(`${CONFLUENCE_USERNAME}:${CONFLUENCE_TOKEN}`).toString("base64");
  return axios.create({
    baseURL: `${CONFLUENCE_URL}/rest/api`,
    headers: {
      Authorization: `Basic ${creds}`,
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Atlassian-Token": "no-check",
    },
    timeout: 30000,
  });
}

// Convert plain text to minimal Confluence storage format (XHTML-based)
function textToStorage(text: string): string {
  // If it already looks like storage format XML, pass through
  if (text.trimStart().startsWith("<")) return text;

  // Convert markdown-ish text to basic Confluence storage format
  return text
    .split("\n\n")
    .map((para) => {
      const trimmed = para.trim();
      if (!trimmed) return "";
      if (trimmed.startsWith("## ")) return `<h2>${trimmed.slice(3)}</h2>`;
      if (trimmed.startsWith("# ")) return `<h1>${trimmed.slice(2)}</h1>`;
      if (trimmed.startsWith("### ")) return `<h3>${trimmed.slice(4)}</h3>`;
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        const items = trimmed.split("\n").map((l) => `<li>${l.replace(/^[-*] /, "")}</li>`).join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${trimmed.replace(/\n/g, "<br/>")}</p>`;
    })
    .filter(Boolean)
    .join("\n");
}

const server = new Server(
  { name: "confluence-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_pages",
      description: "Search Confluence pages using CQL (Confluence Query Language) or simple text. Examples: 'space=SRE AND title~\"RCA\"', text~\"payment-service deployment\"",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "CQL query or plain text search (plain text is automatically wrapped in text~\"...\")" },
          space_key: { type: "string", description: "Limit search to a specific space" },
          max_results: { type: "number", default: 20 },
        },
        required: ["query"],
      },
    },
    {
      name: "get_page",
      description: "Get the content of a Confluence page by ID or title + space",
      inputSchema: {
        type: "object",
        properties: {
          page_id: { type: "string", description: "Numeric page ID (preferred)" },
          title: { type: "string", description: "Page title (used if page_id not provided)" },
          space_key: { type: "string", description: "Space key (required when searching by title)" },
          include_body: { type: "boolean", description: "Include page body content (default: true)", default: true },
        },
      },
    },
    {
      name: "create_page",
      description: "Create a new Confluence page. Content can be plain text, markdown, or Confluence storage format (XHTML). Use this to document RCAs, runbooks, deployment guides, etc.",
      inputSchema: {
        type: "object",
        properties: {
          space_key: { type: "string", description: `Space key (e.g. SRE, OPS, TEAM). Default: ${DEFAULT_SPACE}` },
          title: { type: "string", description: "Page title" },
          content: { type: "string", description: "Page body — plain text, markdown, or Confluence storage format XML" },
          parent_id: { type: "string", description: "Parent page ID (optional, to nest under another page)" },
          parent_title: { type: "string", description: "Parent page title (alternative to parent_id)" },
        },
        required: ["title", "content"],
      },
    },
    {
      name: "update_page",
      description: "Update the content or title of an existing Confluence page",
      inputSchema: {
        type: "object",
        properties: {
          page_id: { type: "string", description: "Numeric page ID" },
          title: { type: "string", description: "New title (keep the same title if not changing)" },
          content: { type: "string", description: "New page body content" },
          version_comment: { type: "string", description: "Comment describing what changed" },
        },
        required: ["page_id", "title", "content"],
      },
    },
    {
      name: "append_to_page",
      description: "Append content to an existing Confluence page without replacing it (useful for adding to runbooks or incident timelines)",
      inputSchema: {
        type: "object",
        properties: {
          page_id: { type: "string" },
          content_to_append: { type: "string", description: "Content to add at the bottom of the page" },
          version_comment: { type: "string" },
        },
        required: ["page_id", "content_to_append"],
      },
    },
    {
      name: "add_comment",
      description: "Add a comment to a Confluence page",
      inputSchema: {
        type: "object",
        properties: {
          page_id: { type: "string" },
          comment: { type: "string" },
        },
        required: ["page_id", "comment"],
      },
    },
    {
      name: "list_spaces",
      description: "List Confluence spaces accessible to the authenticated user",
      inputSchema: {
        type: "object",
        properties: {
          type: { type: "string", enum: ["global", "personal", "all"], default: "global" },
          query: { type: "string", description: "Filter spaces by name" },
        },
      },
    },
    {
      name: "get_space",
      description: "Get details and top-level pages of a Confluence space",
      inputSchema: {
        type: "object",
        properties: {
          space_key: { type: "string" },
        },
        required: ["space_key"],
      },
    },
    {
      name: "get_page_children",
      description: "List child pages of a Confluence page",
      inputSchema: {
        type: "object",
        properties: {
          page_id: { type: "string" },
          depth: { type: "string", enum: ["all", "1"], default: "1" },
        },
        required: ["page_id"],
      },
    },
    {
      name: "move_page",
      description: "Move a page under a different parent",
      inputSchema: {
        type: "object",
        properties: {
          page_id: { type: "string" },
          new_parent_id: { type: "string", description: "Target parent page ID" },
          position: { type: "string", enum: ["append", "before", "after"], default: "append" },
        },
        required: ["page_id", "new_parent_id"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const client = createClient();

  try {
    switch (name) {
      case "search_pages": {
        let cql = String(args!.query);
        // If it looks like plain text (no CQL operators), wrap it
        if (!cql.includes("=") && !cql.includes("~") && !cql.includes(" AND ") && !cql.includes(" OR ")) {
          cql = `text~"${cql}"`;
        }
        if (args?.space_key) cql = `space="${args.space_key}" AND (${cql})`;
        const { data } = await client.get("/content/search", {
          params: { cql, limit: args?.max_results || 20, expand: "space,version,ancestors" },
        });
        const pages = data.results?.map((p: any) => ({
          id: p.id,
          title: p.title,
          space: p.space?.key,
          last_updated: p.version?.when,
          by: p.version?.by?.displayName,
          url: `${CONFLUENCE_URL}${p._links?.webui || ""}`,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ total: data.totalSize, pages }, null, 2) }] };
      }

      case "get_page": {
        let page: any;
        if (args?.page_id) {
          const { data } = await client.get(`/content/${args.page_id}`, {
            params: { expand: "body.storage,version,space,ancestors" },
          });
          page = data;
        } else if (args?.title && args?.space_key) {
          const { data } = await client.get("/content", {
            params: { spaceKey: args.space_key, title: args.title, expand: "body.storage,version", limit: 1 },
          });
          if (!data.results?.length) {
            return { content: [{ type: "text", text: `Page "${args.title}" not found in space ${args.space_key}` }], isError: true };
          }
          page = data.results[0];
        } else {
          return { content: [{ type: "text", text: "Provide page_id or both title and space_key" }], isError: true };
        }
        const body = args?.include_body !== false
          ? page.body?.storage?.value?.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").slice(0, 2000)
          : undefined;
        return {
          content: [{
            type: "text", text: JSON.stringify({
              id: page.id,
              title: page.title,
              space: page.space?.key,
              version: page.version?.number,
              last_updated: page.version?.when,
              by: page.version?.by?.displayName,
              url: `${CONFLUENCE_URL}${page._links?.webui || ""}`,
              body_preview: body,
            }, null, 2),
          }],
        };
      }

      case "create_page": {
        const spaceKey = String(args?.space_key || DEFAULT_SPACE);
        if (!spaceKey) {
          return { content: [{ type: "text", text: "space_key is required" }], isError: true };
        }
        const body: Record<string, any> = {
          type: "page",
          title: args!.title,
          space: { key: spaceKey },
          body: {
            storage: {
              value: textToStorage(String(args!.content)),
              representation: "storage",
            },
          },
        };
        // Find parent page ID if parent_title provided
        if (args?.parent_id) {
          body.ancestors = [{ id: args.parent_id }];
        } else if (args?.parent_title) {
          const { data: parentData } = await client.get("/content", {
            params: { spaceKey, title: args.parent_title, limit: 1 },
          });
          if (parentData.results?.[0]) {
            body.ancestors = [{ id: parentData.results[0].id }];
          }
        }
        const { data } = await client.post("/content", body);
        return {
          content: [{
            type: "text",
            text: `✅ Page created: "${data.title}" (ID: ${data.id})\n${CONFLUENCE_URL}${data._links?.webui || ""}`,
          }],
        };
      }

      case "update_page": {
        // Get current version first
        const { data: current } = await client.get(`/content/${args!.page_id}`, {
          params: { expand: "version" },
        });
        const newVersion = (current.version?.number || 0) + 1;
        const body: Record<string, any> = {
          type: "page",
          title: args!.title,
          version: { number: newVersion },
          body: {
            storage: {
              value: textToStorage(String(args!.content)),
              representation: "storage",
            },
          },
        };
        if (args?.version_comment) body.version.message = args.version_comment;
        const { data } = await client.put(`/content/${args!.page_id}`, body);
        return {
          content: [{
            type: "text",
            text: `✅ Page updated to v${newVersion}: "${data.title}"\n${CONFLUENCE_URL}${data._links?.webui || ""}`,
          }],
        };
      }

      case "append_to_page": {
        // Get current content + version
        const { data: current } = await client.get(`/content/${args!.page_id}`, {
          params: { expand: "body.storage,version" },
        });
        const existingContent = current.body?.storage?.value || "";
        const appendedContent = existingContent + "\n" + textToStorage(String(args!.content_to_append));
        const newVersion = (current.version?.number || 0) + 1;
        const body: Record<string, any> = {
          type: "page",
          title: current.title,
          version: { number: newVersion },
          body: { storage: { value: appendedContent, representation: "storage" } },
        };
        if (args?.version_comment) body.version.message = args.version_comment;
        await client.put(`/content/${args!.page_id}`, body);
        return { content: [{ type: "text", text: `✅ Content appended to "${current.title}"` }] };
      }

      case "add_comment": {
        await client.post("/content", {
          type: "comment",
          container: { id: args!.page_id, type: "page" },
          body: {
            storage: {
              value: textToStorage(String(args!.comment)),
              representation: "storage",
            },
          },
        });
        return { content: [{ type: "text", text: `✅ Comment added to page ${args!.page_id}` }] };
      }

      case "list_spaces": {
        const params: Record<string, any> = { limit: 50 };
        if (args?.type && args.type !== "all") params.type = args.type;
        if (args?.query) params.spaceKey = args.query;
        const { data } = await client.get("/space", { params });
        const spaces = data.results?.map((s: any) => ({
          key: s.key, name: s.name, type: s.type,
          url: `${CONFLUENCE_URL}${s._links?.webui || ""}`,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ spaces, count: spaces?.length }, null, 2) }] };
      }

      case "get_space": {
        const [spaceRes, pagesRes] = await Promise.all([
          client.get(`/space/${args!.space_key}`),
          client.get("/content", {
            params: { spaceKey: args!.space_key, type: "page", limit: 20, expand: "version" },
          }),
        ]);
        return {
          content: [{
            type: "text", text: JSON.stringify({
              key: spaceRes.data.key,
              name: spaceRes.data.name,
              description: spaceRes.data.description?.plain?.value,
              homepage: spaceRes.data.homepage?.title,
              url: `${CONFLUENCE_URL}${spaceRes.data._links?.webui || ""}`,
              recent_pages: pagesRes.data.results?.map((p: any) => ({
                id: p.id, title: p.title,
                updated: p.version?.when,
                by: p.version?.by?.displayName,
              })),
            }, null, 2),
          }],
        };
      }

      case "get_page_children": {
        const { data } = await client.get(`/content/${args!.page_id}/child/page`, {
          params: { limit: 50, expand: "version" },
        });
        const children = data.results?.map((p: any) => ({
          id: p.id, title: p.title,
          updated: p.version?.when,
          url: `${CONFLUENCE_URL}${p._links?.webui || ""}`,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ children, count: children?.length }, null, 2) }] };
      }

      case "move_page": {
        // Confluence move API varies between Cloud and Server; use ancestors update approach
        const { data: current } = await client.get(`/content/${args!.page_id}`, {
          params: { expand: "version" },
        });
        const body = {
          type: "page",
          title: current.title,
          version: { number: (current.version?.number || 0) + 1 },
          ancestors: [{ id: args!.new_parent_id }],
        };
        await client.put(`/content/${args!.page_id}`, body);
        return { content: [{ type: "text", text: `✅ Page "${current.title}" moved under parent ${args!.new_parent_id}` }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.message || err.response?.data?.error || err.message;
    const status = err.response?.status;
    return {
      content: [{ type: "text", text: `Confluence error${status ? ` (HTTP ${status})` : ""}: ${msg}` }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Confluence MCP server running");
}

main().catch(console.error);
