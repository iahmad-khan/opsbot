# Multi-LLM Configuration

OpsBot uses LiteLLM as its LLM abstraction layer, so you can switch between Claude, OpenAI, Gemini, Bedrock, and Ollama without code changes.

---

## Setting the Default Model

```env
LITELLM_DEFAULT_MODEL=claude-sonnet-4-6     # Anthropic Claude (default)
# LITELLM_DEFAULT_MODEL=gpt-4o              # OpenAI GPT-4o
# LITELLM_DEFAULT_MODEL=gemini/gemini-1.5-pro  # Google Gemini
# LITELLM_DEFAULT_MODEL=bedrock/claude-3-5-sonnet-20241022  # AWS Bedrock
# LITELLM_DEFAULT_MODEL=ollama/llama3.1       # Local Ollama
```

---

## Provider Credentials

Set only the API key for the provider you're using:

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
OPENAI_API_KEY=sk-...

# Google Gemini
GOOGLE_API_KEY=AIzaSy...

# AWS Bedrock (uses boto3 — credentials from ~/.aws or IAM role)
# No API key env var needed; ensure AWS_REGION is set
AWS_REGION=us-east-1

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
LITELLM_DEFAULT_MODEL=ollama/llama3.1
```

---

## LLM Parameters

```env
LITELLM_MAX_TOKENS=8192        # Max tokens per LLM response
LITELLM_TEMPERATURE=0.0        # 0 = deterministic, good for ops tasks
LITELLM_MAX_RETRIES=3          # Retry on transient errors
LITELLM_TIMEOUT=120            # Seconds to wait for LLM response
```

---

## Token Budget

Limit per-user daily LLM token consumption to prevent runaway costs:

```env
LITELLM_DAILY_TOKEN_LIMIT=50000    # 0 = unlimited
```

Token usage is tracked in Redis per user per day (key: `opsbot:tokens:{user_id}:{date}`). Users who hit their limit see: *"Daily token budget exceeded — budget resets at midnight UTC."*

Administrators can check consumption:

```
@opsbot how many tokens have I used today?
```

---

## Model Comparison for Ops Use

| Model | Tool calling | Quality | Speed | Cost |
|---|---|---|---|---|
| `claude-sonnet-4-6` | Excellent | High | Fast | Medium |
| `claude-opus-4-8` | Excellent | Highest | Slow | High |
| `gpt-4o` | Excellent | High | Fast | Medium |
| `gpt-4o-mini` | Good | Medium | Very fast | Low |
| `gemini/gemini-1.5-pro` | Good | High | Fast | Medium |
| `ollama/llama3.1` | Basic | Medium | Varies | Free |

For production ops use, `claude-sonnet-4-6` and `gpt-4o` provide the best balance of quality and reliability on tool-heavy chains.

---

## Caveats

- **SRE modules ignore `LITELLM_DEFAULT_MODEL`.** `sre/slo_analyzer.py`, `sre/rca_engine.py`, and `sre/fix_generator.py` currently hardcode `claude-sonnet-4-6`. A future fix should read from settings.
- **Token counting is provider-dependent.** Some providers (Bedrock, Ollama) return approximate token counts. The daily budget counter may drift slightly.
- **Tool calling format varies.** LiteLLM normalizes tool/function calling across providers, but not all models handle complex multi-step tool chains equally well. Test thoroughly before switching providers.
- **Streaming is not implemented.** The agent loop uses non-streaming LLM calls and waits for the full response before processing tool calls. For very long responses, this adds latency. A progress indicator (`🔧 Running tool...`) is shown in Slack while tools execute.
- **Ollama requires local setup.** `ollama serve` must be running and the model pulled (`ollama pull llama3.1`) before OpsBot can use it. Ollama is not included in the docker-compose stack.
