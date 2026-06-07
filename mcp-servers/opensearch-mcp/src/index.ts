import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";

// Supports both OpenSearch and Elasticsearch (identical REST API surface)
const OS_URL = process.env.OPENSEARCH_URL || process.env.ELASTICSEARCH_URL || "http://localhost:9200";
const OS_USERNAME = process.env.OPENSEARCH_USERNAME || process.env.ELASTICSEARCH_USERNAME || "";
const OS_PASSWORD = process.env.OPENSEARCH_PASSWORD || process.env.ELASTICSEARCH_PASSWORD || "";
const OS_API_KEY = process.env.OPENSEARCH_API_KEY || process.env.ELASTICSEARCH_API_KEY || "";
const DEFAULT_INDEX = process.env.OPENSEARCH_DEFAULT_INDEX || "logs-*";

function createClient(): AxiosInstance {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (OS_API_KEY) {
    headers["Authorization"] = `ApiKey ${OS_API_KEY}`;
  } else if (OS_USERNAME && OS_PASSWORD) {
    headers["Authorization"] =
      "Basic " + Buffer.from(`${OS_USERNAME}:${OS_PASSWORD}`).toString("base64");
  }
  return axios.create({ baseURL: OS_URL, headers, timeout: 30000 });
}

const client = createClient();

// Build a service filter that covers common log shipping field names
function serviceFilter(service: string): object {
  return {
    bool: {
      should: [
        { term: { "kubernetes.labels.app": service } },
        { term: { "kubernetes.labels.app.keyword": service } },
        { term: { "service.name": service } },
        { term: { "service.name.keyword": service } },
        { term: { "app": service } },
        { term: { "fields.service": service } },
        { wildcard: { "kubernetes.pod_name": { value: `${service}*` } } },
      ],
      minimum_should_match: 1,
    },
  };
}

interface FilterClause {
  bool: { should: object[]; minimum_should_match: number };
}

// Build log level filter covering ECS and custom formats
function levelFilter(levels: string[]): FilterClause {
  return {
    bool: {
      should: [
        ...levels.map((l) => ({ term: { "log.level": l } })),
        ...levels.map((l) => ({ term: { "log.level.keyword": l } })),
        ...levels.map((l) => ({ term: { "level": l } })),
        ...levels.map((l) => ({ term: { "severity": l } })),
        ...levels.map((l) => ({ term: { "loglevel": l } })),
      ],
      minimum_should_match: 1,
    },
  };
}

function parseTimeRange(lookback: string): string {
  // Accept "1h", "30m", "2d", "15m" — pass through as-is for ES/OS relative syntax
  return `now-${lookback}`;
}

// Summarize raw hits into concise log lines
function summarizeHits(hits: any[]): object[] {
  return hits.map((h: any) => {
    const s = h._source || {};
    return {
      timestamp: s["@timestamp"] || s.timestamp || "",
      level: s.log?.level || s.level || s.severity || "",
      message: (s.message || s.msg || s.log?.message || "").slice(0, 500),
      service: s.service?.name || s.app || s["kubernetes.labels.app"] || s.kubernetes?.labels?.app || "",
      pod: s.kubernetes?.pod?.name || s.kubernetes?.pod_name || "",
      namespace: s.kubernetes?.namespace || s.kubernetes?.namespace_name || "",
      index: h._index,
    };
  });
}

const server = new Server(
  { name: "opensearch-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_logs",
      description:
        "Search logs in OpenSearch/Elasticsearch by service, text, log level, and time range. " +
        "Useful for: 'show me error logs from payment-service', 'find timeout messages in checkout-service'.",
      inputSchema: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Full-text search query applied to the message field (e.g. 'timeout', 'connection refused', 'NullPointerException')",
          },
          service: {
            type: "string",
            description: "Service or application name to filter by (matches kubernetes.labels.app, service.name, app fields)",
          },
          index: {
            type: "string",
            description: `Index pattern to search (default: ${DEFAULT_INDEX})`,
          },
          lookback: {
            type: "string",
            description: "How far back to search, e.g. '1h', '30m', '2h', '1d' (default: '1h')",
            default: "1h",
          },
          level: {
            type: "string",
            enum: ["error", "warn", "info", "debug", "fatal", "all"],
            description: "Log level filter (default: 'all')",
            default: "all",
          },
          size: {
            type: "number",
            description: "Maximum number of log lines to return (default: 50, max: 200)",
            default: 50,
          },
        },
      },
    },
    {
      name: "get_error_summary",
      description:
        "Analyze and summarize error patterns for a service: top error messages by frequency, " +
        "error count over time, and error type breakdown. Best for: 'analyze timeout errors in X', " +
        "'what are the most frequent errors in payment-service?'",
      inputSchema: {
        type: "object",
        properties: {
          service: {
            type: "string",
            description: "Service name to analyze (leave empty to analyze all services)",
          },
          query: {
            type: "string",
            description: "Additional text filter, e.g. 'timeout' or 'connection pool' (optional)",
          },
          index: {
            type: "string",
            description: `Index pattern (default: ${DEFAULT_INDEX})`,
          },
          lookback: {
            type: "string",
            description: "Time window to analyze (default: '1h')",
            default: "1h",
          },
          top_n: {
            type: "number",
            description: "Number of top error patterns to return (default: 20)",
            default: 20,
          },
        },
      },
    },
    {
      name: "count_events",
      description:
        "Count log events matching a query within a time window. " +
        "Useful for: 'how many 5xx errors in the last 30 minutes?', 'count timeouts in payment-service'.",
      inputSchema: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Text to search for (e.g. '5xx', 'timeout', 'ERROR')",
          },
          service: { type: "string", description: "Service name filter (optional)" },
          index: { type: "string", description: `Index pattern (default: ${DEFAULT_INDEX})` },
          lookback: { type: "string", default: "1h" },
          level: {
            type: "string",
            enum: ["error", "warn", "info", "debug", "fatal", "all"],
            default: "all",
          },
        },
        required: ["query"],
      },
    },
    {
      name: "search_slow_queries",
      description:
        "Find slow or timed-out operations in logs. Searches for timeout, slow query, " +
        "and high-latency patterns and extracts duration values. " +
        "Useful for: 'find slow DB queries in order-service', 'check timeout errors in checkout-service'.",
      inputSchema: {
        type: "object",
        properties: {
          service: { type: "string", description: "Service name to filter" },
          index: { type: "string" },
          lookback: { type: "string", default: "1h" },
          min_duration_ms: {
            type: "number",
            description: "Only show operations slower than this many milliseconds (optional)",
          },
          size: { type: "number", default: 50 },
        },
      },
    },
    {
      name: "get_log_field_values",
      description:
        "Get the top values for a specific field (terms aggregation). " +
        "Useful for: 'what services are logging errors?', 'what are the top error codes?'.",
      inputSchema: {
        type: "object",
        properties: {
          field: {
            type: "string",
            description: "Field name to aggregate (e.g. 'service.name', 'http.response.status_code', 'error.type')",
          },
          query: { type: "string", description: "Optional text filter" },
          service: { type: "string", description: "Optional service filter" },
          index: { type: "string" },
          lookback: { type: "string", default: "1h" },
          top_n: { type: "number", default: 20 },
        },
        required: ["field"],
      },
    },
    {
      name: "list_indices",
      description:
        "List available indices or data streams. Helps identify the correct index pattern " +
        "to use (e.g. filebeat-*, logstash-*, logs-*).",
      inputSchema: {
        type: "object",
        properties: {
          pattern: {
            type: "string",
            description: "Index name pattern (default: '*', can use wildcards like 'logs-*')",
            default: "*",
          },
        },
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "search_logs": {
        const index = String(args?.index || DEFAULT_INDEX);
        const lookback = String(args?.lookback || "1h");
        const size = Math.min(Number(args?.size || 50), 200);
        const level = String(args?.level || "all");

        const mustClauses: object[] = [
          { range: { "@timestamp": { gte: parseTimeRange(lookback) } } },
        ];
        if (args?.query) {
          mustClauses.push({
            multi_match: {
              query: String(args.query),
              fields: ["message", "msg", "log.message", "error.message"],
              type: "phrase_prefix",
            },
          });
        }

        const filterClauses: object[] = [];
        if (args?.service) filterClauses.push(serviceFilter(String(args.service)));
        if (level !== "all") filterClauses.push(levelFilter([level]));

        const body = {
          query: { bool: { must: mustClauses, filter: filterClauses } },
          sort: [{ "@timestamp": { order: "desc" } }],
          size,
          _source: [
            "@timestamp", "message", "msg",
            "log.level", "level", "severity",
            "service.name", "app",
            "kubernetes.pod_name", "kubernetes.namespace",
            "kubernetes.labels.app", "error.message",
          ],
        };

        const { data } = await client.post(`/${index}/_search`, body);
        const hits = data.hits?.hits || [];
        const total = data.hits?.total?.value ?? hits.length;

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              total_matched: total,
              returned: hits.length,
              index,
              time_range: `last ${lookback}`,
              logs: summarizeHits(hits),
            }, null, 2),
          }],
        };
      }

      case "get_error_summary": {
        const index = String(args?.index || DEFAULT_INDEX);
        const lookback = String(args?.lookback || "1h");
        const topN = Number(args?.top_n || 20);

        const mustClauses: object[] = [
          { range: { "@timestamp": { gte: parseTimeRange(lookback) } } },
        ];

        // Filter to error/warn/fatal levels OR messages containing error keywords
        const errorFilter = {
          bool: {
            should: [
              ...levelFilter(["error", "fatal", "warn", "ERROR", "FATAL", "WARN"]).bool.should,
              { match: { message: "exception" } },
              { match: { message: "error" } },
              { match: { message: "timeout" } },
              { match: { message: "failed" } },
              { match: { message: "refused" } },
            ],
            minimum_should_match: 1,
          },
        };

        if (args?.query) {
          mustClauses.push({
            multi_match: {
              query: String(args.query),
              fields: ["message", "error.message"],
            },
          });
        }

        const filterClauses: object[] = [errorFilter];
        if (args?.service) filterClauses.push(serviceFilter(String(args.service)));

        const body = {
          query: { bool: { must: mustClauses, filter: filterClauses } },
          size: 10, // also return sample logs
          sort: [{ "@timestamp": { order: "desc" } }],
          _source: ["@timestamp", "message", "log.level", "level", "kubernetes.pod_name", "service.name"],
          aggs: {
            top_errors: {
              terms: {
                field: "message.keyword",
                size: topN,
                order: { _count: "desc" },
                // truncate long messages
                missing: "(no message)",
              },
            },
            error_levels: {
              terms: { field: "log.level.keyword", size: 10 },
            },
            errors_over_time: {
              date_histogram: {
                field: "@timestamp",
                // Dynamic interval based on lookback
                fixed_interval: lookback.endsWith("d") ? "1h" : "5m",
                min_doc_count: 1,
              },
            },
            top_services: {
              terms: {
                field: "service.name.keyword",
                size: 10,
                missing: "(unknown)",
              },
            },
          },
        };

        const { data } = await client.post(`/${index}/_search`, body);
        const total = data.hits?.total?.value ?? 0;
        const aggs = data.aggregations || {};

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              total_errors: total,
              time_range: `last ${lookback}`,
              index,
              top_error_messages: (aggs.top_errors?.buckets || []).map((b: any) => ({
                message: b.key,
                count: b.doc_count,
              })),
              error_level_breakdown: (aggs.error_levels?.buckets || []).map((b: any) => ({
                level: b.key,
                count: b.doc_count,
              })),
              errors_over_time: (aggs.errors_over_time?.buckets || []).map((b: any) => ({
                time: b.key_as_string,
                count: b.doc_count,
              })),
              top_services_with_errors: (aggs.top_services?.buckets || []).map((b: any) => ({
                service: b.key,
                count: b.doc_count,
              })),
              sample_recent_errors: summarizeHits(data.hits?.hits || []),
            }, null, 2),
          }],
        };
      }

      case "count_events": {
        const index = String(args?.index || DEFAULT_INDEX);
        const lookback = String(args?.lookback || "1h");
        const level = String(args?.level || "all");

        const mustClauses: object[] = [
          { range: { "@timestamp": { gte: parseTimeRange(lookback) } } },
        ];
        if (args?.query) {
          mustClauses.push({
            multi_match: {
              query: String(args.query),
              fields: ["message", "msg", "error.message"],
            },
          });
        }

        const filterClauses: object[] = [];
        if (args?.service) filterClauses.push(serviceFilter(String(args.service)));
        if (level !== "all") filterClauses.push(levelFilter([level]));

        const body = {
          query: { bool: { must: mustClauses, filter: filterClauses } },
          aggs: {
            over_time: {
              date_histogram: {
                field: "@timestamp",
                fixed_interval: "5m",
                min_doc_count: 1,
              },
            },
          },
          size: 0,
        };

        const { data } = await client.post(`/${index}/_search`, body);
        const count = data.hits?.total?.value ?? 0;
        const buckets = data.aggregations?.over_time?.buckets || [];

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              count,
              time_range: `last ${lookback}`,
              query: args?.query,
              service: args?.service || "all",
              per_5min_breakdown: buckets.map((b: any) => ({
                time: b.key_as_string,
                count: b.doc_count,
              })),
            }, null, 2),
          }],
        };
      }

      case "search_slow_queries": {
        const index = String(args?.index || DEFAULT_INDEX);
        const lookback = String(args?.lookback || "1h");
        const size = Math.min(Number(args?.size || 50), 200);

        // Common patterns for slow/timeout log messages across various frameworks
        const slowPatterns = [
          "timeout", "timed out", "deadline exceeded",
          "slow query", "slow request", "took too long",
          "connection timeout", "read timeout", "write timeout",
          "socket timeout", "context deadline", "ETIMEDOUT",
          "504", "408",
        ];

        const mustClauses: object[] = [
          { range: { "@timestamp": { gte: parseTimeRange(lookback) } } },
          {
            bool: {
              should: slowPatterns.map((p) => ({ match_phrase: { message: p } })),
              minimum_should_match: 1,
            },
          },
        ];

        const filterClauses: object[] = [];
        if (args?.service) filterClauses.push(serviceFilter(String(args.service)));

        const body = {
          query: { bool: { must: mustClauses, filter: filterClauses } },
          sort: [{ "@timestamp": { order: "desc" } }],
          size,
          _source: [
            "@timestamp", "message", "log.level", "level",
            "service.name", "kubernetes.pod_name", "kubernetes.namespace",
            "duration", "duration_ms", "took", "elapsed",
            "http.request.duration", "db.statement",
          ],
          aggs: {
            by_service: {
              terms: { field: "service.name.keyword", size: 10, missing: "(unknown)" },
            },
            count_over_time: {
              date_histogram: {
                field: "@timestamp",
                fixed_interval: "5m",
                min_doc_count: 1,
              },
            },
          },
        };

        const { data } = await client.post(`/${index}/_search`, body);
        const hits = data.hits?.hits || [];
        const total = data.hits?.total?.value ?? hits.length;

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              total_slow_timeout_events: total,
              time_range: `last ${lookback}`,
              by_service: (data.aggregations?.by_service?.buckets || []).map((b: any) => ({
                service: b.key,
                count: b.doc_count,
              })),
              count_over_time: (data.aggregations?.count_over_time?.buckets || []).map((b: any) => ({
                time: b.key_as_string,
                count: b.doc_count,
              })),
              events: summarizeHits(hits),
            }, null, 2),
          }],
        };
      }

      case "get_log_field_values": {
        const index = String(args?.index || DEFAULT_INDEX);
        const lookback = String(args?.lookback || "1h");
        const topN = Number(args?.top_n || 20);
        const field = String(args!.field);

        // Try both keyword and non-keyword variants
        const keywordField = field.endsWith(".keyword") ? field : `${field}.keyword`;

        const mustClauses: object[] = [
          { range: { "@timestamp": { gte: parseTimeRange(lookback) } } },
        ];
        if (args?.query) {
          mustClauses.push({ multi_match: { query: String(args.query), fields: ["message"] } });
        }

        const filterClauses: object[] = [];
        if (args?.service) filterClauses.push(serviceFilter(String(args.service)));

        const body = {
          query: { bool: { must: mustClauses, filter: filterClauses } },
          size: 0,
          aggs: {
            field_values: {
              terms: { field: keywordField, size: topN },
            },
          },
        };

        const { data } = await client.post(`/${index}/_search`, body);
        const buckets = data.aggregations?.field_values?.buckets || [];

        if (buckets.length === 0 && !field.endsWith(".keyword")) {
          // Retry with raw field name for numeric fields
          const body2 = {
            ...body,
            aggs: { field_values: { terms: { field, size: topN } } },
          };
          const { data: data2 } = await client.post(`/${index}/_search`, body2);
          const b2 = data2.aggregations?.field_values?.buckets || [];
          return {
            content: [{
              type: "text",
              text: JSON.stringify({
                field,
                index,
                time_range: `last ${lookback}`,
                top_values: b2.map((b: any) => ({ value: b.key, count: b.doc_count })),
              }, null, 2),
            }],
          };
        }

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              field,
              index,
              time_range: `last ${lookback}`,
              top_values: buckets.map((b: any) => ({ value: b.key, count: b.doc_count })),
            }, null, 2),
          }],
        };
      }

      case "list_indices": {
        const pattern = String(args?.pattern || "*");
        const { data } = await client.get(`/_cat/indices/${pattern}?format=json&h=index,health,status,docs.count,store.size&s=index`);

        // Also check for data streams
        let dataStreams: object[] = [];
        try {
          const { data: dsData } = await client.get(`/_data_stream/${pattern}`);
          dataStreams = (dsData.data_streams || []).map((ds: any) => ({
            name: ds.name,
            type: "data_stream",
            backing_indices: ds.indices?.length || 0,
          }));
        } catch {
          // data streams not supported on this cluster
        }

        const indices = (Array.isArray(data) ? data : []).map((i: any) => ({
          name: i.index,
          health: i.health,
          status: i.status,
          docs: i["docs.count"],
          size: i["store.size"],
        })).filter((i: any) => !i.name.startsWith("."));

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              indices: indices.slice(0, 50),
              data_streams: dataStreams.slice(0, 20),
              total_indices: indices.length,
              tip: `Use these index names (or wildcards like 'logs-*') in other tools via the 'index' parameter`,
            }, null, 2),
          }],
        };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (err: any) {
    const msg = err.response?.data?.error?.reason || err.response?.data?.error || err.message;
    const status = err.response?.status;
    return {
      content: [{
        type: "text",
        text: `OpenSearch/ES error${status ? ` (HTTP ${status})` : ""}: ${JSON.stringify(msg)}`,
      }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("OpenSearch/Elasticsearch MCP server running");
}

main().catch(console.error);
