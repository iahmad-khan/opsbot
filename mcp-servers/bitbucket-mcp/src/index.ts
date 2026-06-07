import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";

// Bitbucket Cloud:  BITBUCKET_URL=https://api.bitbucket.org/2.0 (default)
// Bitbucket Server: BITBUCKET_URL=https://bitbucket.yourcompany.com  (auto-detects Server API path)
const BB_URL = (process.env.BITBUCKET_URL || "https://api.bitbucket.org/2.0").replace(/\/$/, "");
const BB_USERNAME = process.env.BITBUCKET_USERNAME || "";
const BB_PASSWORD = process.env.BITBUCKET_APP_PASSWORD || process.env.BITBUCKET_PASSWORD || "";
const BB_TOKEN = process.env.BITBUCKET_TOKEN || ""; // PAT for Server
const BB_WORKSPACE = process.env.BITBUCKET_WORKSPACE || "";

const IS_CLOUD = BB_URL.includes("api.bitbucket.org");

function createClient(): AxiosInstance {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (BB_TOKEN) {
    headers["Authorization"] = `Bearer ${BB_TOKEN}`;
  } else if (BB_USERNAME && BB_PASSWORD) {
    headers["Authorization"] =
      "Basic " + Buffer.from(`${BB_USERNAME}:${BB_PASSWORD}`).toString("base64");
  }
  // Cloud uses 2.0 API directly; Server uses /rest/api/1.0
  const baseURL = IS_CLOUD ? BB_URL : `${BB_URL}/rest/api/1.0`;
  return axios.create({ baseURL, headers, timeout: 30000 });
}

function repoPath(workspace: string, repo: string): string {
  if (IS_CLOUD) return `/repositories/${workspace}/${repo}`;
  return `/projects/${workspace}/repos/${repo}`;
}

const server = new Server(
  { name: "bitbucket-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "list_repos",
      description: "List repositories in a Bitbucket workspace or project",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string", description: `Workspace/project key (default: ${BB_WORKSPACE})` },
          query: { type: "string", description: "Filter repos by name substring" },
        },
      },
    },
    {
      name: "get_repo",
      description: "Get details about a Bitbucket repository",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string", description: "Repository slug/name" },
        },
        required: ["repo"],
      },
    },
    {
      name: "list_prs",
      description: "List pull requests in a Bitbucket repository",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          state: { type: "string", enum: ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"], default: "OPEN" },
          author: { type: "string", description: "Filter by author username" },
        },
        required: ["repo"],
      },
    },
    {
      name: "get_pr",
      description: "Get details of a specific pull request including reviewers, diff stats, and approval status",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          pr_id: { type: "number" },
        },
        required: ["repo", "pr_id"],
      },
    },
    {
      name: "create_pr",
      description: "Create a new pull request in Bitbucket",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          title: { type: "string" },
          source_branch: { type: "string" },
          destination_branch: { type: "string", default: "main" },
          description: { type: "string" },
          reviewers: { type: "array", items: { type: "string" }, description: "Reviewer usernames" },
          close_source_branch: { type: "boolean", default: false },
        },
        required: ["repo", "title", "source_branch"],
      },
    },
    {
      name: "merge_pr",
      description: "Merge a pull request",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          pr_id: { type: "number" },
          merge_strategy: { type: "string", enum: ["merge_commit", "squash", "fast_forward"], default: "merge_commit" },
          message: { type: "string", description: "Commit message for the merge" },
        },
        required: ["repo", "pr_id"],
      },
    },
    {
      name: "decline_pr",
      description: "Decline (reject) a pull request",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          pr_id: { type: "number" },
        },
        required: ["repo", "pr_id"],
      },
    },
    {
      name: "add_pr_comment",
      description: "Add a comment to a pull request",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          pr_id: { type: "number" },
          comment: { type: "string" },
        },
        required: ["repo", "pr_id", "comment"],
      },
    },
    {
      name: "list_branches",
      description: "List branches in a repository",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          query: { type: "string", description: "Filter branches by name" },
        },
        required: ["repo"],
      },
    },
    {
      name: "create_branch",
      description: "Create a new branch from a source branch or commit",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          branch_name: { type: "string" },
          source: { type: "string", description: "Source branch or commit hash (default: main)" },
        },
        required: ["repo", "branch_name"],
      },
    },
    {
      name: "get_pipeline_status",
      description: "Get the latest pipeline/build status for a repository branch or commit",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          branch: { type: "string", description: "Branch name (default: main)" },
        },
        required: ["repo"],
      },
    },
    {
      name: "trigger_pipeline",
      description: "Trigger a Bitbucket Pipeline run",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          branch: { type: "string" },
          pattern: { type: "string", description: "Pipeline selector pattern (optional, e.g. 'custom:deploy-staging')" },
          variables: {
            type: "array",
            items: { type: "object", properties: { key: { type: "string" }, value: { type: "string" } } },
            description: "Pipeline variables to inject",
          },
        },
        required: ["repo", "branch"],
      },
    },
    {
      name: "add_user_to_repo",
      description: "Add or update a user's permission on a repository",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          username: { type: "string" },
          permission: { type: "string", enum: ["read", "write", "admin"], default: "read" },
        },
        required: ["repo", "username"],
      },
    },
    {
      name: "list_tags",
      description: "List release tags in a Bitbucket repository — for release management, shows available versions",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string", description: "Repository slug" },
          query: { type: "string", description: "Filter tags by name substring" },
          limit: { type: "number", default: 30 },
        },
        required: ["repo"],
      },
    },
    {
      name: "compare_commits",
      description: "Show the diff between two branches, tags, or commits in a Bitbucket repository",
      inputSchema: {
        type: "object",
        properties: {
          workspace: { type: "string" },
          repo: { type: "string" },
          from_ref: { type: "string", description: "Base ref (older tag/branch/commit)" },
          to_ref: { type: "string", description: "Target ref (newer tag/branch/commit)" },
        },
        required: ["repo", "from_ref", "to_ref"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const client = createClient();
  const ws = String(args?.workspace || BB_WORKSPACE);

  try {
    switch (name) {
      case "list_repos": {
        let repos: any[];
        if (IS_CLOUD) {
          const params: Record<string, string> = { pagelen: "25" };
          if (args?.query) params.q = `name~"${args.query}"`;
          const { data } = await client.get(`/repositories/${ws}`, { params });
          repos = (data.values || []).map((r: any) => ({
            name: r.slug,
            full_name: r.full_name,
            description: r.description,
            language: r.language,
            updated_on: r.updated_on,
            clone_url: r.links?.clone?.find((l: any) => l.name === "https")?.href,
          }));
        } else {
          const { data } = await client.get(`/projects/${ws}/repos`, { params: { limit: 25 } });
          repos = (data.values || []).map((r: any) => ({
            name: r.slug,
            description: r.description,
            clone_url: r.links?.clone?.find((l: any) => l.name === "http")?.href,
          }));
        }
        return { content: [{ type: "text", text: JSON.stringify({ repos, count: repos.length }, null, 2) }] };
      }

      case "get_repo": {
        const { data } = await client.get(repoPath(ws, String(args!.repo)));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
      }

      case "list_prs": {
        const repo = String(args!.repo);
        const state = String(args?.state || "OPEN");
        let prs: any[];
        if (IS_CLOUD) {
          const params: Record<string, string> = { state, pagelen: "25" };
          const { data } = await client.get(`${repoPath(ws, repo)}/pullrequests`, { params });
          prs = (data.values || []).map((pr: any) => ({
            id: pr.id,
            title: pr.title,
            state: pr.state,
            author: pr.author?.display_name,
            source: pr.source?.branch?.name,
            destination: pr.destination?.branch?.name,
            created: pr.created_on,
            updated: pr.updated_on,
            url: pr.links?.html?.href,
          }));
        } else {
          const params: Record<string, string | number> = { limit: 25, state };
          if (args?.author) Object.assign(params, { username: args.author });
          const { data } = await client.get(`${repoPath(ws, repo)}/pull-requests`, { params });
          prs = (data.values || []).map((pr: any) => ({
            id: pr.id,
            title: pr.title,
            state: pr.state,
            author: pr.author?.displayName,
            source: pr.fromRef?.displayId,
            destination: pr.toRef?.displayId,
            created: pr.createdDate,
            updated: pr.updatedDate,
          }));
        }
        return { content: [{ type: "text", text: JSON.stringify({ prs, count: prs.length }, null, 2) }] };
      }

      case "get_pr": {
        const repo = String(args!.repo);
        const prId = Number(args!.pr_id);
        const endpoint = IS_CLOUD
          ? `${repoPath(ws, repo)}/pullrequests/${prId}`
          : `${repoPath(ws, repo)}/pull-requests/${prId}`;
        const { data } = await client.get(endpoint);
        const pr = IS_CLOUD
          ? {
              id: data.id, title: data.title, state: data.state,
              author: data.author?.display_name,
              source: data.source?.branch?.name,
              destination: data.destination?.branch?.name,
              description: data.description,
              reviewers: data.reviewers?.map((r: any) => ({ user: r.user?.display_name, approved: r.approved })),
              url: data.links?.html?.href,
            }
          : {
              id: data.id, title: data.title, state: data.state,
              author: data.author?.displayName,
              source: data.fromRef?.displayId,
              destination: data.toRef?.displayId,
              description: data.description,
              reviewers: data.reviewers?.map((r: any) => ({ user: r.user?.displayName, approved: r.approved })),
            };
        return { content: [{ type: "text", text: JSON.stringify(pr, null, 2) }] };
      }

      case "create_pr": {
        const repo = String(args!.repo);
        let body: Record<string, any>;
        if (IS_CLOUD) {
          body = {
            title: args!.title,
            description: args?.description || "",
            source: { branch: { name: args!.source_branch } },
            destination: { branch: { name: args?.destination_branch || "main" } },
            close_source_branch: args?.close_source_branch || false,
            reviewers: ((args?.reviewers as string[]) || []).map((u) => ({ uuid: u })),
          };
          const { data } = await client.post(`${repoPath(ws, repo)}/pullrequests`, body);
          return { content: [{ type: "text", text: `✅ PR #${data.id} created: ${data.links?.html?.href}` }] };
        } else {
          body = {
            title: args!.title,
            description: args?.description || "",
            fromRef: { id: `refs/heads/${args!.source_branch}` },
            toRef: { id: `refs/heads/${args?.destination_branch || "main"}` },
            reviewers: ((args?.reviewers as string[]) || []).map((u) => ({ user: { name: u } })),
          };
          const { data } = await client.post(`${repoPath(ws, repo)}/pull-requests`, body);
          return { content: [{ type: "text", text: `✅ PR #${data.id} created: "${data.title}"` }] };
        }
      }

      case "merge_pr": {
        const repo = String(args!.repo);
        const prId = Number(args!.pr_id);
        if (IS_CLOUD) {
          const body: Record<string, any> = {};
          if (args?.merge_strategy) body.merge_strategy = args.merge_strategy;
          if (args?.message) body.message = args.message;
          await client.post(`${repoPath(ws, repo)}/pullrequests/${prId}/merge`, body);
        } else {
          const { data: pr } = await client.get(`${repoPath(ws, repo)}/pull-requests/${prId}`);
          await client.post(`${repoPath(ws, repo)}/pull-requests/${prId}/merge`, {
            version: pr.version,
            message: args?.message,
          });
        }
        return { content: [{ type: "text", text: `✅ PR #${prId} merged in ${ws}/${args!.repo}` }] };
      }

      case "decline_pr": {
        const repo = String(args!.repo);
        const prId = Number(args!.pr_id);
        const endpoint = IS_CLOUD
          ? `${repoPath(ws, repo)}/pullrequests/${prId}/decline`
          : `${repoPath(ws, repo)}/pull-requests/${prId}/decline`;
        await client.post(endpoint);
        return { content: [{ type: "text", text: `✅ PR #${prId} declined` }] };
      }

      case "add_pr_comment": {
        const repo = String(args!.repo);
        const prId = Number(args!.pr_id);
        if (IS_CLOUD) {
          await client.post(`${repoPath(ws, repo)}/pullrequests/${prId}/comments`, {
            content: { raw: String(args!.comment) },
          });
        } else {
          await client.post(`${repoPath(ws, repo)}/pull-requests/${prId}/comments`, {
            text: String(args!.comment),
          });
        }
        return { content: [{ type: "text", text: `✅ Comment added to PR #${prId}` }] };
      }

      case "list_branches": {
        const repo = String(args!.repo);
        let branches: any[];
        if (IS_CLOUD) {
          const params: Record<string, string> = { pagelen: "50" };
          if (args?.query) params.q = `name~"${args.query}"`;
          const { data } = await client.get(`${repoPath(ws, repo)}/refs/branches`, { params });
          branches = (data.values || []).map((b: any) => ({
            name: b.name,
            target: b.target?.hash?.substring(0, 8),
          }));
        } else {
          const params: Record<string, string | number> = { limit: 50 };
          if (args?.query) Object.assign(params, { filterText: args.query });
          const { data } = await client.get(`${repoPath(ws, repo)}/branches`, { params });
          branches = (data.values || []).map((b: any) => ({
            name: b.displayId,
            target: b.latestCommit?.substring(0, 8),
          }));
        }
        return { content: [{ type: "text", text: JSON.stringify({ branches, count: branches.length }, null, 2) }] };
      }

      case "create_branch": {
        const repo = String(args!.repo);
        const branchName = String(args!.branch_name);
        const source = String(args?.source || "main");
        if (IS_CLOUD) {
          await client.post(`${repoPath(ws, repo)}/refs/branches`, {
            name: branchName,
            target: { hash: source },
          });
        } else {
          await client.post(`${repoPath(ws, repo)}/branches`, {
            name: branchName,
            startPoint: source,
          });
        }
        return { content: [{ type: "text", text: `✅ Branch "${branchName}" created from "${source}" in ${ws}/${repo}` }] };
      }

      case "get_pipeline_status": {
        const repo = String(args!.repo);
        const branch = String(args?.branch || "main");
        if (!IS_CLOUD) {
          return { content: [{ type: "text", text: "Pipelines API is only available on Bitbucket Cloud" }], isError: true };
        }
        const { data } = await client.get(`${repoPath(ws, repo)}/pipelines/`, {
          params: { "target.branch": branch, sort: "-created_on", pagelen: "5" },
        });
        const pipelines = (data.values || []).map((p: any) => ({
          uuid: p.uuid,
          state: p.state?.name,
          result: p.state?.result?.name,
          trigger: p.trigger?.name,
          created: p.created_on,
          duration_seconds: p.duration_in_seconds,
          target_commit: p.target?.commit?.hash?.substring(0, 8),
        }));
        return { content: [{ type: "text", text: JSON.stringify(pipelines, null, 2) }] };
      }

      case "trigger_pipeline": {
        const repo = String(args!.repo);
        const branch = String(args!.branch);
        if (!IS_CLOUD) {
          return { content: [{ type: "text", text: "Pipelines API is only available on Bitbucket Cloud" }], isError: true };
        }
        const body: Record<string, any> = {
          target: { type: "pipeline_ref_target", ref_type: "branch", ref_name: branch },
        };
        if (args?.pattern) {
          body.target.selector = { type: "custom", pattern: args.pattern };
        }
        if (args?.variables) {
          body.variables = args.variables;
        }
        const { data } = await client.post(`${repoPath(ws, repo)}/pipelines/`, body);
        return { content: [{ type: "text", text: `✅ Pipeline triggered. UUID: ${data.uuid}, state: ${data.state?.name}` }] };
      }

      case "add_user_to_repo": {
        const repo = String(args!.repo);
        const username = String(args!.username);
        const permission = String(args?.permission || "read");
        if (IS_CLOUD) {
          await client.put(`${repoPath(ws, repo)}/permissions/users/${username}`, null, {
            params: { permission },
          });
        } else {
          await client.put(`${repoPath(ws, repo)}/permissions/users`, {
            user: { name: username },
            permission: permission.toUpperCase(),
          });
        }
        return { content: [{ type: "text", text: `✅ ${username} given ${permission} access to ${ws}/${repo}` }] };
      }

      case "list_tags": {
        const repo = String(args!.repo);
        let tags: any[];
        if (IS_CLOUD) {
          const params: Record<string, string> = { pagelen: String(args?.limit || 30) };
          if (args?.query) params.q = `name~"${args.query}"`;
          const { data } = await client.get(`${repoPath(ws, repo)}/refs/tags`, { params });
          tags = (data.values || []).map((t: any) => ({
            name: t.name,
            target: t.target?.hash?.substring(0, 12),
            date: t.target?.date,
            message: t.message,
          }));
        } else {
          const params: Record<string, string | number> = { limit: Number(args?.limit || 30) };
          if (args?.query) Object.assign(params, { filterText: args.query });
          const { data } = await client.get(`${repoPath(ws, repo)}/tags`, { params });
          tags = (data.values || []).map((t: any) => ({
            name: t.displayId,
            target: t.latestCommit?.substring(0, 12),
            hash: t.hash?.substring(0, 12),
          }));
        }
        return { content: [{ type: "text", text: JSON.stringify({ tags, count: tags.length }, null, 2) }] };
      }

      case "compare_commits": {
        const repo = String(args!.repo);
        // Cloud: GET /repositories/{ws}/{repo}/diff/{from}..{to}
        // Server: GET /projects/{ws}/repos/{repo}/compare/diff?from={from}&to={to}
        if (IS_CLOUD) {
          const spec = `${args!.from_ref}..${args!.to_ref}`;
          const { data } = await client.get(`${repoPath(ws, repo)}/diff/${spec}`);
          return { content: [{ type: "text", text: String(data).substring(0, 8000) }] };
        } else {
          const { data } = await client.get(`${repoPath(ws, repo)}/compare/diff`, {
            params: { from: args!.from_ref, to: args!.to_ref },
          });
          return { content: [{ type: "text", text: String(data).substring(0, 8000) }] };
        }
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.error?.message || err.response?.data?.message || err.message;
    const status = err.response?.status;
    return {
      content: [{ type: "text", text: `Bitbucket error${status ? ` (HTTP ${status})` : ""}: ${msg}` }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Bitbucket MCP server running");
}

main().catch(console.error);
