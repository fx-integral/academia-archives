# `/v1/docs` Endpoint Template for DRAIN Providers

Every provider MUST implement a `GET /v1/docs` endpoint. This is the primary way
AI agents learn how to use the provider. The marketplace falls back to
`{apiUrl}/v1/docs` when no custom `docsUrl` is stored in the database — if the
endpoint is missing, agents get a 404 and cannot use the service.

## Why it matters

- Agents call `/v1/docs` BEFORE their first paid request
- The response is injected into the agent's context window as plain text
- It must be complete enough that an agent can use the provider without any
  prior knowledge of it

---

## Required Sections

Every `/v1/docs` response MUST contain these sections in this order:

### 1. Title + Identity
```
# {Provider Name} — Agent Instructions
```
One sentence: what this provider does. If it is NOT a standard LLM chat
provider, state it explicitly ("This is NOT a chat/LLM provider.").

### 2. How to use via DRAIN
Standard two-step flow that is the same for every provider:
```
1. Open a payment channel to this provider (drain_open_channel)
2. Call drain_chat with:
   - model: <model ID or list>
   - messages: <what goes in the user message>
```

### 3. Available Models / Operations
Table or list of all model IDs the agent can pass in the `model` field.
Include a short description and price for each.

For single-model providers, show the one model ID.
For multi-model providers, show a table with columns: Model ID, Description, Price.

### 4. Input Format
Describe exactly what the agent should put in the **user message content**:
- Plain text prompt (LLM, Numinous, Vericore)
- JSON object with specific fields (Apify, CronJob, Resend)
- Code to execute (E2B)
- JSON or plain text with fallback (Replicate)

Be explicit about whether the content is JSON-stringified or plain text.

### 5. Example
At minimum one concrete, copy-paste-ready example showing the `model` and
`messages` array the agent should send. Use realistic values.

```
model: "example/model-id"
messages: [{"role": "user", "content": "..."}]
```

For providers with multiple operations/models, show one example per major
use case (max 3-4).

### 6. Response Format
Describe what the **assistant message content** will contain:
- For LLMs: standard text response
- For structured providers: JSON with specific fields (list the top-level keys)
- For media providers: URLs to generated assets

### 7. Pricing
State the pricing model:
- Per-token (LLM): "Pricing is per token. Check /v1/pricing for current rates."
- Flat rate: "$X.XXXX USDC per request."
- Tiered: Table of tiers with prices.

Always reference `/v1/pricing` for exact current prices.

### 8. Notes (optional but recommended)
Constraints, limits, and tips:
- Response time expectations
- Rate limits
- Max input/output sizes
- Streaming support (yes/no)
- Any gotchas agents should know

---

## Implementation

### Content Type
Always return `text/plain` with Markdown formatting:
```typescript
res.type('text/plain').send(`# ...`);
```

### Dynamic Values
Inject live data where possible:
- Current prices from config
- Available model IDs from the registry
- Timeout values from config

### Length
Keep it between 800–2500 characters. Agents have limited context windows.
Too short = missing info. Too long = wastes tokens.

---

## Template Code (TypeScript)

Copy this into your provider's `src/index.ts` and fill in the placeholders:

```typescript
app.get('/v1/docs', (_req, res) => {
  res.type('text/plain').send(`# {PROVIDER_NAME} — Agent Instructions

{One-sentence description of what this provider does.}

## How to use via DRAIN

1. Open a payment channel to this provider (drain_open_channel)
2. Call drain_chat with:
   - model: "{MODEL_ID}"
   - messages: ONE user message containing {DESCRIPTION_OF_INPUT}

## Available Models

{TABLE_OR_LIST_OF_MODELS}

## Input Format

{DETAILED_INPUT_FORMAT_DESCRIPTION}

## Example

model: "{MODEL_ID}"
messages: [{\"role\": \"user\", \"content\": \"{EXAMPLE_CONTENT}\"}]

## Response

{WHAT_THE_ASSISTANT_MESSAGE_CONTAINS}

## Pricing

{PRICING_DESCRIPTION}
Check /v1/pricing for current USDC rates.

## Notes

{CONSTRAINTS_LIMITS_TIPS}
`);
});
```

---

## Template Code — LLM Providers

LLM providers follow the standard OpenAI chat completions format.
Use this simpler template:

```typescript
app.get('/v1/docs', (_req, res) => {
  const models = getSupportedModels();
  const topModels = models.slice(0, 8).map(m => {
    const p = getModelPricing(m);
    return p
      ? `- ${m}: $${formatUnits(p.inputPer1k, 6)} input / $${formatUnits(p.outputPer1k, 6)} output per 1k tokens`
      : `- ${m}`;
  }).join('\n');

  res.type('text/plain').send(`# {PROVIDER_NAME} — Agent Instructions

Standard OpenAI-compatible LLM provider via DRAIN payments.
Supports ${models.length} models with per-token pricing.

## How to use via DRAIN

1. Open a payment channel to this provider (drain_open_channel)
2. Call drain_chat with:
   - model: any model ID from the list below
   - messages: standard chat messages array

## Example

model: "{DEFAULT_MODEL}"
messages: [{"role": "user", "content": "Explain quantum computing in simple terms"}]

Streaming is supported (stream: true).

## Top Models

${topModels}

Full list: GET /v1/models
Full pricing: GET /v1/pricing

## Pricing

Per-token pricing in USDC. Input and output tokens are priced separately.
Cost = (input_tokens × input_rate + output_tokens × output_rate) / 1000.

## Notes

- Standard OpenAI chat completions format (messages, max_tokens, temperature, etc.)
- Streaming supported via stream: true
- Responses include X-DRAIN-Cost, X-DRAIN-Remaining headers
`);
});
```

---

## Checklist Before Deploying

- [ ] `GET /v1/docs` returns 200 with `text/plain`
- [ ] Title includes provider name
- [ ] At least one complete, working example
- [ ] All model IDs are listed or referenced via /v1/models
- [ ] Pricing info is present (exact amounts or reference to /v1/pricing)
- [ ] Input format is unambiguous (JSON vs plain text vs code)
- [ ] Response format is described
- [ ] An agent with zero prior knowledge could use the provider from the docs alone
