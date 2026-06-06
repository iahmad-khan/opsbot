import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";

// Cloud:  JIRA_URL=https://yoursite.atlassian.net   auth: email + API token
// Server: JIRA_URL=https://jira.yourcompany.com     auth: username + password/PAT
const JIRA_URL = (process.env.JIRA_URL || "").replace(/\/$/, "");
const JIRA_USERNAME = process.env.JIRA_USERNAME || process.env.JIRA_EMAIL || "";
const JIRA_TOKEN = process.env.JIRA_API_TOKEN || process.env.JIRA_PASSWORD || "";
const DEFAULT_PROJECT = process.env.JIRA_DEFAULT_PROJECT || "";

function createClient(): AxiosInstance {
  const creds = Buffer.from(`${JIRA_USERNAME}:${JIRA_TOKEN}`).toString("base64");
  return axios.create({
    // Use API v2 — works on both Cloud and Server, accepts plain text for descriptions
    baseURL: `${JIRA_URL}/rest/api/2`,
    headers: {
      Authorization: `Basic ${creds}`,
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    timeout: 30000,
  });
}

const server = new Server(
  { name: "jira-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_issues",
      description: "Search Jira issues using JQL (Jira Query Language). Examples: project=PROJ AND status='In Progress', assignee=currentUser() AND priority=High",
      inputSchema: {
        type: "object",
        properties: {
          jql: { type: "string", description: "JQL query string" },
          fields: { type: "array", items: { type: "string" }, description: "Fields to return (default: summary, status, assignee, priority, labels)" },
          max_results: { type: "number", default: 25 },
        },
        required: ["jql"],
      },
    },
    {
      name: "get_issue",
      description: "Get full details of a Jira issue including description, comments, and history",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string", description: "Issue key (e.g. PROJ-123)" },
        },
        required: ["issue_key"],
      },
    },
    {
      name: "create_issue",
      description: "Create a new Jira issue/ticket. Use this when asked to 'create a ticket', 'open a bug', 'log an incident', etc.",
      inputSchema: {
        type: "object",
        properties: {
          project_key: { type: "string", description: `Project key (e.g. PROJ). Default: ${DEFAULT_PROJECT}` },
          summary: { type: "string", description: "Issue title/summary" },
          description: { type: "string", description: "Detailed description of the issue" },
          issue_type: { type: "string", description: "Issue type: Bug, Task, Story, Epic, Incident, etc.", default: "Task" },
          priority: { type: "string", enum: ["Highest", "High", "Medium", "Low", "Lowest"], default: "Medium" },
          assignee: { type: "string", description: "Assignee account ID or username" },
          labels: { type: "array", items: { type: "string" } },
          components: { type: "array", items: { type: "string" } },
          epic_link: { type: "string", description: "Epic issue key (e.g. PROJ-10)" },
        },
        required: ["summary"],
      },
    },
    {
      name: "update_issue",
      description: "Update fields of an existing Jira issue",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string" },
          summary: { type: "string" },
          description: { type: "string" },
          priority: { type: "string", enum: ["Highest", "High", "Medium", "Low", "Lowest"] },
          assignee: { type: "string" },
          labels: { type: "array", items: { type: "string" } },
        },
        required: ["issue_key"],
      },
    },
    {
      name: "add_comment",
      description: "Add a comment to a Jira issue",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string" },
          body: { type: "string", description: "Comment text (supports Jira markdown/wiki markup)" },
        },
        required: ["issue_key", "body"],
      },
    },
    {
      name: "transition_issue",
      description: "Move a Jira issue to a different status (e.g. 'In Progress', 'Done', 'In Review', 'Blocked')",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string" },
          transition_name: { type: "string", description: "Target status name (e.g. 'In Progress', 'Done', 'In Review')" },
          comment: { type: "string", description: "Optional comment to add during transition" },
          resolution: { type: "string", description: "Resolution when closing: 'Done', 'Won\\'t Fix', 'Duplicate'" },
        },
        required: ["issue_key", "transition_name"],
      },
    },
    {
      name: "assign_issue",
      description: "Assign a Jira issue to a user",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string" },
          username: { type: "string", description: "Username or account ID. Use '-1' to unassign." },
        },
        required: ["issue_key", "username"],
      },
    },
    {
      name: "list_projects",
      description: "List all accessible Jira projects",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Filter projects by name or key" },
        },
      },
    },
    {
      name: "list_transitions",
      description: "List available status transitions for a Jira issue (shows what statuses you can move it to)",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string" },
        },
        required: ["issue_key"],
      },
    },
    {
      name: "link_issues",
      description: "Create a link between two Jira issues (e.g. 'blocks', 'is blocked by', 'relates to', 'duplicates')",
      inputSchema: {
        type: "object",
        properties: {
          inward_issue: { type: "string", description: "Source issue key" },
          outward_issue: { type: "string", description: "Target issue key" },
          link_type: { type: "string", description: "Link type name: 'blocks', 'is blocked by', 'relates to', 'duplicates', 'is duplicated by'", default: "relates to" },
        },
        required: ["inward_issue", "outward_issue"],
      },
    },
    {
      name: "get_my_issues",
      description: "Get issues currently assigned to the authenticated user",
      inputSchema: {
        type: "object",
        properties: {
          project_key: { type: "string", description: "Filter by project (optional)" },
          status: { type: "string", description: "Filter by status (optional)" },
          max_results: { type: "number", default: 25 },
        },
      },
    },
    {
      name: "search_users",
      description: "Search for Jira users by name or email (useful to find account IDs for assignment)",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Name, display name, or email to search" },
        },
        required: ["query"],
      },
    },
    {
      name: "get_issue_changelog",
      description: "Get the change history of a Jira issue (who changed what and when)",
      inputSchema: {
        type: "object",
        properties: {
          issue_key: { type: "string" },
        },
        required: ["issue_key"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const client = createClient();

  try {
    switch (name) {
      case "search_issues": {
        const fields = (args?.fields as string[]) || ["summary", "status", "assignee", "priority", "labels", "issuetype", "updated", "description"];
        const { data } = await client.get("/search", {
          params: { jql: args!.jql, maxResults: args?.max_results || 25, fields: fields.join(",") },
        });
        const issues = data.issues?.map((i: any) => ({
          key: i.key,
          summary: i.fields.summary,
          status: i.fields.status?.name,
          assignee: i.fields.assignee?.displayName,
          priority: i.fields.priority?.name,
          issue_type: i.fields.issuetype?.name,
          labels: i.fields.labels,
          updated: i.fields.updated,
          url: `${JIRA_URL}/browse/${i.key}`,
        }));
        return {
          content: [{ type: "text", text: JSON.stringify({ total: data.total, issues }, null, 2) }],
        };
      }

      case "get_issue": {
        const { data } = await client.get(`/issue/${args!.issue_key}`);
        const comments = (data.fields.comment?.comments || []).slice(-5).map((c: any) => ({
          author: c.author?.displayName,
          body: c.body?.substring(0, 500),
          created: c.created,
        }));
        return {
          content: [{
            type: "text", text: JSON.stringify({
              key: data.key,
              summary: data.fields.summary,
              status: data.fields.status?.name,
              issue_type: data.fields.issuetype?.name,
              priority: data.fields.priority?.name,
              assignee: data.fields.assignee?.displayName,
              reporter: data.fields.reporter?.displayName,
              labels: data.fields.labels,
              description: data.fields.description?.substring(0, 1000),
              created: data.fields.created,
              updated: data.fields.updated,
              recent_comments: comments,
              url: `${JIRA_URL}/browse/${data.key}`,
            }, null, 2),
          }],
        };
      }

      case "create_issue": {
        const projectKey = String(args?.project_key || DEFAULT_PROJECT);
        if (!projectKey) {
          return { content: [{ type: "text", text: "project_key is required" }], isError: true };
        }
        const fields: Record<string, any> = {
          project: { key: projectKey },
          summary: args!.summary,
          issuetype: { name: String(args?.issue_type || "Task") },
          priority: { name: String(args?.priority || "Medium") },
        };
        if (args?.description) fields.description = args.description;
        if (args?.labels) fields.labels = args.labels;
        if (args?.assignee) fields.assignee = { name: args.assignee };
        if (args?.components) {
          fields.components = (args.components as string[]).map((c) => ({ name: c }));
        }
        const { data } = await client.post("/issue", { fields });
        return {
          content: [{
            type: "text",
            text: `✅ Created ${data.key}: ${JIRA_URL}/browse/${data.key}`,
          }],
        };
      }

      case "update_issue": {
        const fields: Record<string, any> = {};
        if (args?.summary) fields.summary = args.summary;
        if (args?.description) fields.description = args.description;
        if (args?.priority) fields.priority = { name: args.priority };
        if (args?.assignee) fields.assignee = { name: args.assignee };
        if (args?.labels) fields.labels = args.labels;
        await client.put(`/issue/${args!.issue_key}`, { fields });
        return { content: [{ type: "text", text: `✅ ${args!.issue_key} updated` }] };
      }

      case "add_comment": {
        await client.post(`/issue/${args!.issue_key}/comment`, { body: String(args!.body) });
        return { content: [{ type: "text", text: `✅ Comment added to ${args!.issue_key}` }] };
      }

      case "transition_issue": {
        // First get available transitions
        const { data: transData } = await client.get(`/issue/${args!.issue_key}/transitions`);
        const transitionName = String(args!.transition_name).toLowerCase();
        const match = transData.transitions?.find(
          (t: any) => t.name.toLowerCase().includes(transitionName) || t.to?.name?.toLowerCase().includes(transitionName)
        );
        if (!match) {
          const available = transData.transitions?.map((t: any) => t.name).join(", ");
          return {
            content: [{ type: "text", text: `Transition "${args!.transition_name}" not found. Available: ${available}` }],
            isError: true,
          };
        }
        const body: Record<string, any> = { transition: { id: match.id } };
        if (args?.resolution) {
          body.fields = { resolution: { name: args.resolution } };
        }
        if (args?.comment) {
          body.update = { comment: [{ add: { body: args.comment } }] };
        }
        await client.post(`/issue/${args!.issue_key}/transitions`, body);
        return { content: [{ type: "text", text: `✅ ${args!.issue_key} transitioned to "${match.to?.name || match.name}"` }] };
      }

      case "assign_issue": {
        const username = String(args!.username);
        const assignee = username === "-1" ? null : { name: username };
        await client.put(`/issue/${args!.issue_key}/assignee`, assignee);
        return { content: [{ type: "text", text: `✅ ${args!.issue_key} assigned to ${username === "-1" ? "nobody" : username}` }] };
      }

      case "list_projects": {
        const params: Record<string, any> = { maxResults: 50 };
        if (args?.query) params.query = args.query;
        const { data } = await client.get("/project", { params });
        const projects = (Array.isArray(data) ? data : data.values || []).map((p: any) => ({
          key: p.key, name: p.name, type: p.projectTypeKey, lead: p.lead?.displayName,
        }));
        return { content: [{ type: "text", text: JSON.stringify(projects, null, 2) }] };
      }

      case "list_transitions": {
        const { data } = await client.get(`/issue/${args!.issue_key}/transitions`);
        const transitions = data.transitions?.map((t: any) => ({
          id: t.id, name: t.name, to_status: t.to?.name, to_category: t.to?.statusCategory?.name,
        }));
        return { content: [{ type: "text", text: JSON.stringify(transitions, null, 2) }] };
      }

      case "link_issues": {
        // First look up available link types
        const { data: linkTypes } = await client.get("/issueLinkType");
        const linkTypeName = String(args?.link_type || "relates to").toLowerCase();
        const match = linkTypes.issueLinkTypes?.find(
          (l: any) =>
            l.name.toLowerCase().includes(linkTypeName) ||
            l.inward.toLowerCase().includes(linkTypeName) ||
            l.outward.toLowerCase().includes(linkTypeName)
        );
        const linkType = match || linkTypes.issueLinkTypes?.[0];
        await client.post("/issueLink", {
          type: { name: linkType?.name || "Relates" },
          inwardIssue: { key: args!.inward_issue },
          outwardIssue: { key: args!.outward_issue },
        });
        return { content: [{ type: "text", text: `✅ Linked ${args!.inward_issue} → ${args!.outward_issue} (${linkType?.name})` }] };
      }

      case "get_my_issues": {
        const conditions = ["assignee = currentUser()"];
        if (args?.project_key) conditions.push(`project = ${args.project_key}`);
        if (args?.status) conditions.push(`status = "${args.status}"`);
        conditions.push('statusCategory != Done');
        const jql = conditions.join(" AND ") + " ORDER BY updated DESC";
        const { data } = await client.get("/search", {
          params: { jql, maxResults: args?.max_results || 25, fields: "summary,status,priority,project,updated" },
        });
        const issues = data.issues?.map((i: any) => ({
          key: i.key, summary: i.fields.summary,
          status: i.fields.status?.name,
          priority: i.fields.priority?.name,
          project: i.fields.project?.key,
          updated: i.fields.updated,
          url: `${JIRA_URL}/browse/${i.key}`,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ total: data.total, issues }, null, 2) }] };
      }

      case "search_users": {
        const { data } = await client.get("/user/search", {
          params: { query: args!.query, maxResults: 10 },
        });
        const users = (Array.isArray(data) ? data : []).map((u: any) => ({
          account_id: u.accountId || u.name,
          display_name: u.displayName,
          email: u.emailAddress,
          active: u.active,
        }));
        return { content: [{ type: "text", text: JSON.stringify(users, null, 2) }] };
      }

      case "get_issue_changelog": {
        const { data } = await client.get(`/issue/${args!.issue_key}/changelog`);
        const history = (data.values || []).slice(-20).map((h: any) => ({
          author: h.author?.displayName,
          created: h.created,
          changes: h.items?.map((i: any) => ({
            field: i.field,
            from: i.fromString,
            to: i.toString,
          })),
        }));
        return { content: [{ type: "text", text: JSON.stringify(history, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.errorMessages?.join("; ") ||
      JSON.stringify(err.response?.data?.errors) ||
      err.message;
    const status = err.response?.status;
    return {
      content: [{ type: "text", text: `Jira error${status ? ` (HTTP ${status})` : ""}: ${msg}` }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Jira MCP server running");
}

main().catch(console.error);
