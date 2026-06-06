import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";

const GITLAB_URL = (process.env.GITLAB_URL || "https://gitlab.com").replace(/\/$/, "");
const GITLAB_TOKEN = process.env.GITLAB_TOKEN || "";
const DEFAULT_GROUP = process.env.GITLAB_DEFAULT_GROUP || "";

function createClient(): AxiosInstance {
  return axios.create({
    baseURL: `${GITLAB_URL}/api/v4`,
    headers: {
      "PRIVATE-TOKEN": GITLAB_TOKEN,
      "Content-Type": "application/json",
    },
    timeout: 30000,
  });
}

// Encode project path: "group/subgroup/repo" → "group%2Fsubgroup%2Frepo"
function encodeProject(project: string): string {
  return encodeURIComponent(project);
}

const server = new Server(
  { name: "gitlab-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "list_projects",
      description: "List GitLab projects (repos) for a group or the authenticated user",
      inputSchema: {
        type: "object",
        properties: {
          group: { type: "string", description: `Group or namespace path (default: ${DEFAULT_GROUP})` },
          search: { type: "string", description: "Search projects by name" },
          owned: { type: "boolean", description: "Only list projects owned by the user" },
        },
      },
    },
    {
      name: "get_project",
      description: "Get details of a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string", description: "Project path (e.g. 'group/repo') or numeric ID" },
        },
        required: ["project"],
      },
    },
    {
      name: "list_mrs",
      description: "List merge requests for a project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          state: { type: "string", enum: ["opened", "closed", "locked", "merged", "all"], default: "opened" },
          author: { type: "string", description: "Filter by author username" },
          assignee: { type: "string", description: "Filter by assignee username" },
          labels: { type: "string", description: "Comma-separated label names" },
        },
        required: ["project"],
      },
    },
    {
      name: "get_mr",
      description: "Get details of a specific merge request",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          mr_iid: { type: "number", description: "Merge request internal ID (IID, not the global ID)" },
        },
        required: ["project", "mr_iid"],
      },
    },
    {
      name: "create_mr",
      description: "Create a merge request in GitLab",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          title: { type: "string" },
          source_branch: { type: "string" },
          target_branch: { type: "string", default: "main" },
          description: { type: "string" },
          assignee: { type: "string", description: "Assignee username" },
          labels: { type: "string", description: "Comma-separated labels" },
          remove_source_branch: { type: "boolean", default: false },
          squash: { type: "boolean", default: false },
        },
        required: ["project", "title", "source_branch"],
      },
    },
    {
      name: "merge_mr",
      description: "Merge a merge request (must be approved and pipeline passing)",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          mr_iid: { type: "number" },
          squash: { type: "boolean", default: false },
          should_remove_source_branch: { type: "boolean", default: false },
          merge_commit_message: { type: "string" },
        },
        required: ["project", "mr_iid"],
      },
    },
    {
      name: "list_issues",
      description: "List issues in a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          state: { type: "string", enum: ["opened", "closed", "all"], default: "opened" },
          assignee: { type: "string" },
          labels: { type: "string" },
          milestone: { type: "string" },
          search: { type: "string" },
        },
        required: ["project"],
      },
    },
    {
      name: "get_issue",
      description: "Get details of a GitLab issue",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          issue_iid: { type: "number" },
        },
        required: ["project", "issue_iid"],
      },
    },
    {
      name: "create_issue",
      description: "Create a new issue in a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          title: { type: "string" },
          description: { type: "string" },
          assignees: { type: "array", items: { type: "string" }, description: "Assignee usernames" },
          labels: { type: "string", description: "Comma-separated labels" },
          milestone_id: { type: "number" },
          due_date: { type: "string", description: "Due date in YYYY-MM-DD format" },
        },
        required: ["project", "title"],
      },
    },
    {
      name: "update_issue",
      description: "Update a GitLab issue (title, description, assignee, labels, state)",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          issue_iid: { type: "number" },
          title: { type: "string" },
          description: { type: "string" },
          state_event: { type: "string", enum: ["close", "reopen"] },
          assignees: { type: "array", items: { type: "string" } },
          labels: { type: "string" },
        },
        required: ["project", "issue_iid"],
      },
    },
    {
      name: "add_issue_comment",
      description: "Add a comment (note) to a GitLab issue",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          issue_iid: { type: "number" },
          body: { type: "string" },
        },
        required: ["project", "issue_iid", "body"],
      },
    },
    {
      name: "list_pipelines",
      description: "List recent pipelines for a project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          ref: { type: "string", description: "Branch, tag, or commit SHA" },
          status: { type: "string", enum: ["running", "pending", "success", "failed", "canceled", "skipped", "all"] },
        },
        required: ["project"],
      },
    },
    {
      name: "get_pipeline",
      description: "Get details and job statuses for a specific pipeline",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          pipeline_id: { type: "number" },
        },
        required: ["project", "pipeline_id"],
      },
    },
    {
      name: "trigger_pipeline",
      description: "Trigger a new pipeline run for a branch or tag",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          ref: { type: "string", description: "Branch name, tag, or commit SHA" },
          variables: {
            type: "array",
            items: { type: "object", properties: { key: { type: "string" }, value: { type: "string" } } },
            description: "CI/CD variables to pass to the pipeline",
          },
        },
        required: ["project", "ref"],
      },
    },
    {
      name: "retry_pipeline",
      description: "Retry all failed jobs in a pipeline",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          pipeline_id: { type: "number" },
        },
        required: ["project", "pipeline_id"],
      },
    },
    {
      name: "cancel_pipeline",
      description: "Cancel a running pipeline",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          pipeline_id: { type: "number" },
        },
        required: ["project", "pipeline_id"],
      },
    },
    {
      name: "list_branches",
      description: "List branches in a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          search: { type: "string" },
        },
        required: ["project"],
      },
    },
    {
      name: "create_branch",
      description: "Create a new branch in a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          branch: { type: "string", description: "New branch name" },
          ref: { type: "string", description: "Source branch, tag, or commit (default: main)" },
        },
        required: ["project", "branch"],
      },
    },
    {
      name: "add_member",
      description: "Add a member to a GitLab project. Access levels: 10=Guest, 20=Reporter, 30=Developer, 40=Maintainer, 50=Owner",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          username: { type: "string" },
          access_level: { type: "number", enum: [10, 20, 30, 40, 50], default: 30 },
        },
        required: ["project", "username"],
      },
    },
    {
      name: "list_tags",
      description: "List tags in a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          search: { type: "string" },
        },
        required: ["project"],
      },
    },
    {
      name: "create_tag",
      description: "Create a new tag in a GitLab project",
      inputSchema: {
        type: "object",
        properties: {
          project: { type: "string" },
          tag_name: { type: "string" },
          ref: { type: "string", description: "Commit SHA, branch name, or another tag" },
          message: { type: "string", description: "Creates an annotated tag when provided" },
          release_description: { type: "string", description: "Creates a release alongside the tag" },
        },
        required: ["project", "tag_name", "ref"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const client = createClient();

  try {
    switch (name) {
      case "list_projects": {
        const group = String(args?.group || DEFAULT_GROUP);
        let data: any;
        if (group) {
          const params: Record<string, any> = { per_page: 25, include_subgroups: true };
          if (args?.search) params.search = args.search;
          const res = await client.get(`/groups/${encodeProject(group)}/projects`, { params });
          data = res.data;
        } else {
          const params: Record<string, any> = { per_page: 25, membership: true };
          if (args?.owned) params.owned = true;
          if (args?.search) params.search = args.search;
          const res = await client.get("/projects", { params });
          data = res.data;
        }
        const projects = data.map((p: any) => ({
          id: p.id, name: p.name, path_with_namespace: p.path_with_namespace,
          visibility: p.visibility, default_branch: p.default_branch,
          web_url: p.web_url, last_activity_at: p.last_activity_at,
          open_issues_count: p.open_issues_count,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ projects, count: projects.length }, null, 2) }] };
      }

      case "get_project": {
        const { data } = await client.get(`/projects/${encodeProject(String(args!.project))}`);
        return {
          content: [{
            type: "text", text: JSON.stringify({
              id: data.id, name: data.name, path: data.path_with_namespace,
              description: data.description, visibility: data.visibility,
              default_branch: data.default_branch, web_url: data.web_url,
              ssh_url: data.ssh_url_to_repo, clone_url: data.http_url_to_repo,
              open_issues: data.open_issues_count, stars: data.star_count,
            }, null, 2),
          }],
        };
      }

      case "list_mrs": {
        const project = encodeProject(String(args!.project));
        const params: Record<string, any> = { state: args?.state || "opened", per_page: 25 };
        if (args?.author) params.author_username = args.author;
        if (args?.assignee) params.assignee_username = args.assignee;
        if (args?.labels) params.labels = args.labels;
        const { data } = await client.get(`/projects/${project}/merge_requests`, { params });
        const mrs = data.map((mr: any) => ({
          iid: mr.iid, title: mr.title, state: mr.state,
          author: mr.author?.username,
          assignee: mr.assignee?.username,
          source_branch: mr.source_branch,
          target_branch: mr.target_branch,
          pipeline_status: mr.pipeline?.status,
          web_url: mr.web_url,
          created_at: mr.created_at,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ mrs, count: mrs.length }, null, 2) }] };
      }

      case "get_mr": {
        const project = encodeProject(String(args!.project));
        const { data } = await client.get(`/projects/${project}/merge_requests/${args!.mr_iid}`);
        return {
          content: [{
            type: "text", text: JSON.stringify({
              iid: data.iid, title: data.title, state: data.state,
              description: data.description,
              author: data.author?.username,
              assignees: data.assignees?.map((a: any) => a.username),
              source_branch: data.source_branch,
              target_branch: data.target_branch,
              pipeline: { status: data.pipeline?.status, web_url: data.pipeline?.web_url },
              approvals_required: data.approvals_required,
              web_url: data.web_url,
              diff_stats: data.diff_stats,
            }, null, 2),
          }],
        };
      }

      case "create_mr": {
        const project = encodeProject(String(args!.project));
        const body: Record<string, any> = {
          title: args!.title,
          source_branch: args!.source_branch,
          target_branch: args?.target_branch || "main",
          description: args?.description || "",
          remove_source_branch: args?.remove_source_branch || false,
          squash: args?.squash || false,
        };
        if (args?.labels) body.labels = args.labels;
        if (args?.assignee) {
          const { data: user } = await client.get(`/users`, { params: { username: args.assignee } });
          if (user[0]) body.assignee_id = user[0].id;
        }
        const { data } = await client.post(`/projects/${project}/merge_requests`, body);
        return { content: [{ type: "text", text: `✅ MR !${data.iid} created: ${data.web_url}` }] };
      }

      case "merge_mr": {
        const project = encodeProject(String(args!.project));
        const body: Record<string, any> = {
          squash: args?.squash || false,
          should_remove_source_branch: args?.should_remove_source_branch || false,
        };
        if (args?.merge_commit_message) body.merge_commit_message = args.merge_commit_message;
        await client.put(`/projects/${project}/merge_requests/${args!.mr_iid}/merge`, body);
        return { content: [{ type: "text", text: `✅ MR !${args!.mr_iid} merged in ${args!.project}` }] };
      }

      case "list_issues": {
        const project = encodeProject(String(args!.project));
        const params: Record<string, any> = { state: args?.state || "opened", per_page: 25 };
        if (args?.assignee) params.assignee_username = args.assignee;
        if (args?.labels) params.labels = args.labels;
        if (args?.milestone) params.milestone = args.milestone;
        if (args?.search) params.search = args.search;
        const { data } = await client.get(`/projects/${project}/issues`, { params });
        const issues = data.map((i: any) => ({
          iid: i.iid, title: i.title, state: i.state,
          assignees: i.assignees?.map((a: any) => a.username),
          labels: i.labels, milestone: i.milestone?.title,
          web_url: i.web_url, created_at: i.created_at,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ issues, count: issues.length }, null, 2) }] };
      }

      case "get_issue": {
        const project = encodeProject(String(args!.project));
        const { data } = await client.get(`/projects/${project}/issues/${args!.issue_iid}`);
        return {
          content: [{
            type: "text", text: JSON.stringify({
              iid: data.iid, title: data.title, state: data.state,
              description: data.description,
              assignees: data.assignees?.map((a: any) => a.username),
              labels: data.labels, milestone: data.milestone?.title,
              web_url: data.web_url, created_at: data.created_at,
            }, null, 2),
          }],
        };
      }

      case "create_issue": {
        const project = encodeProject(String(args!.project));
        const body: Record<string, any> = {
          title: args!.title,
          description: args?.description || "",
        };
        if (args?.labels) body.labels = args.labels;
        if (args?.milestone_id) body.milestone_id = args.milestone_id;
        if (args?.due_date) body.due_date = args.due_date;
        if (args?.assignees) {
          const ids: number[] = [];
          for (const u of (args.assignees as string[])) {
            const { data: user } = await client.get(`/users`, { params: { username: u } });
            if (user[0]) ids.push(user[0].id);
          }
          body.assignee_ids = ids;
        }
        const { data } = await client.post(`/projects/${project}/issues`, body);
        return { content: [{ type: "text", text: `✅ Issue #${data.iid} created: ${data.web_url}` }] };
      }

      case "update_issue": {
        const project = encodeProject(String(args!.project));
        const body: Record<string, any> = {};
        if (args?.title) body.title = args.title;
        if (args?.description) body.description = args.description;
        if (args?.state_event) body.state_event = args.state_event;
        if (args?.labels) body.labels = args.labels;
        if (args?.assignees) {
          const ids: number[] = [];
          for (const u of (args.assignees as string[])) {
            const { data: user } = await client.get(`/users`, { params: { username: u } });
            if (user[0]) ids.push(user[0].id);
          }
          body.assignee_ids = ids;
        }
        const { data } = await client.put(`/projects/${project}/issues/${args!.issue_iid}`, body);
        return { content: [{ type: "text", text: `✅ Issue #${data.iid} updated` }] };
      }

      case "add_issue_comment": {
        const project = encodeProject(String(args!.project));
        await client.post(`/projects/${project}/issues/${args!.issue_iid}/notes`, {
          body: String(args!.body),
        });
        return { content: [{ type: "text", text: `✅ Comment added to issue #${args!.issue_iid}` }] };
      }

      case "list_pipelines": {
        const project = encodeProject(String(args!.project));
        const params: Record<string, any> = { per_page: 10, order_by: "id", sort: "desc" };
        if (args?.ref) params.ref = args.ref;
        if (args?.status && args.status !== "all") params.status = args.status;
        const { data } = await client.get(`/projects/${project}/pipelines`, { params });
        const pipelines = data.map((p: any) => ({
          id: p.id, status: p.status, ref: p.ref,
          sha: p.sha?.substring(0, 8),
          created_at: p.created_at, updated_at: p.updated_at,
          web_url: p.web_url,
        }));
        return { content: [{ type: "text", text: JSON.stringify(pipelines, null, 2) }] };
      }

      case "get_pipeline": {
        const project = encodeProject(String(args!.project));
        const [pipelineRes, jobsRes] = await Promise.all([
          client.get(`/projects/${project}/pipelines/${args!.pipeline_id}`),
          client.get(`/projects/${project}/pipelines/${args!.pipeline_id}/jobs`, { params: { per_page: 50 } }),
        ]);
        const p = pipelineRes.data;
        return {
          content: [{
            type: "text", text: JSON.stringify({
              id: p.id, status: p.status, ref: p.ref,
              sha: p.sha?.substring(0, 8),
              duration: p.duration, web_url: p.web_url,
              jobs: jobsRes.data.map((j: any) => ({
                id: j.id, name: j.name, stage: j.stage,
                status: j.status, duration: j.duration,
              })),
            }, null, 2),
          }],
        };
      }

      case "trigger_pipeline": {
        const project = encodeProject(String(args!.project));
        const body: Record<string, any> = { ref: args!.ref };
        if (args?.variables) {
          body.variables = (args.variables as any[]).map((v: any) => ({
            key: v.key, value: v.value, variable_type: "env_var",
          }));
        }
        const { data } = await client.post(`/projects/${project}/pipeline`, body);
        return { content: [{ type: "text", text: `✅ Pipeline #${data.id} triggered on ${data.ref} — status: ${data.status}` }] };
      }

      case "retry_pipeline": {
        const project = encodeProject(String(args!.project));
        const { data } = await client.post(`/projects/${project}/pipelines/${args!.pipeline_id}/retry`);
        return { content: [{ type: "text", text: `✅ Pipeline #${data.id} retried — status: ${data.status}` }] };
      }

      case "cancel_pipeline": {
        const project = encodeProject(String(args!.project));
        await client.post(`/projects/${project}/pipelines/${args!.pipeline_id}/cancel`);
        return { content: [{ type: "text", text: `✅ Pipeline #${args!.pipeline_id} cancelled` }] };
      }

      case "list_branches": {
        const project = encodeProject(String(args!.project));
        const params: Record<string, any> = { per_page: 50 };
        if (args?.search) params.search = args.search;
        const { data } = await client.get(`/projects/${project}/repository/branches`, { params });
        return {
          content: [{
            type: "text", text: JSON.stringify(
              data.map((b: any) => ({ name: b.name, commit: b.commit?.short_id, protected: b.protected })),
              null, 2,
            ),
          }],
        };
      }

      case "create_branch": {
        const project = encodeProject(String(args!.project));
        const { data } = await client.post(`/projects/${project}/repository/branches`, {
          branch: args!.branch,
          ref: args?.ref || "main",
        });
        return { content: [{ type: "text", text: `✅ Branch "${data.name}" created in ${args!.project}` }] };
      }

      case "add_member": {
        const project = encodeProject(String(args!.project));
        const { data: users } = await client.get(`/users`, { params: { username: args!.username } });
        if (!users[0]) {
          return { content: [{ type: "text", text: `User "${args!.username}" not found` }], isError: true };
        }
        await client.post(`/projects/${project}/members`, {
          user_id: users[0].id,
          access_level: args?.access_level || 30,
        });
        return { content: [{ type: "text", text: `✅ ${args!.username} added to ${args!.project} with access level ${args?.access_level || 30}` }] };
      }

      case "list_tags": {
        const project = encodeProject(String(args!.project));
        const params: Record<string, any> = { per_page: 20 };
        if (args?.search) params.search = args.search;
        const { data } = await client.get(`/projects/${project}/repository/tags`, { params });
        return {
          content: [{
            type: "text", text: JSON.stringify(
              data.map((t: any) => ({ name: t.name, commit: t.commit?.short_id, message: t.message, release: t.release?.description })),
              null, 2,
            ),
          }],
        };
      }

      case "create_tag": {
        const project = encodeProject(String(args!.project));
        const body: Record<string, any> = { tag_name: args!.tag_name, ref: args!.ref };
        if (args?.message) body.message = args.message;
        if (args?.release_description) body.release_description = args.release_description;
        const { data } = await client.post(`/projects/${project}/repository/tags`, body);
        return { content: [{ type: "text", text: `✅ Tag "${data.name}" created at ${data.commit?.short_id}` }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.message || err.response?.data?.error || err.message;
    const status = err.response?.status;
    return {
      content: [{ type: "text", text: `GitLab error${status ? ` (HTTP ${status})` : ""}: ${JSON.stringify(msg)}` }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("GitLab MCP server running");
}

main().catch(console.error);
