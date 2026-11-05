# TCS GPT-4o relay server

A thin FastAPI relay meant to run **inside the TCS dev workspace**, on
port 8000, reached from outside through the code-server proxy:

```
POST https://rniazure.tcsapps.com/dev-workspaces/<workspace-id>/proxy/8000/execute
GET  https://rniazure.tcsapps.com/dev-workspaces/<workspace-id>/proxy/8000/health
```

It does not store prompts, evidence, or screenshots -- every request is
relayed straight to GPT-4o and the result relayed straight back. Only
`prompt_id` is logged (see `app.py`'s one `logger.info` call), never the
`text`/`images` content itself.

## Setup (inside the workspace)

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: fill in EITHER the Azure OpenAI block OR the OpenAI-compatible
# block, matching however GPT-4o is actually exposed in this workspace.
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Verify it's up

From inside the workspace:

```bash
curl -s http://localhost:8000/health
# {"ok": true, "model": "...", "backend": "azure_openai"|"openai_compatible", "configured": true}
```

From outside, through the proxy, with a valid `code-server-session` cookie:

```bash
curl -s --cookie "code-server-session=<your session cookie>" \
  https://rniazure.tcsapps.com/dev-workspaces/<workspace-id>/proxy/8000/health
```

If this returns HTML instead of JSON, the session cookie is expired or
wrong -- that's exactly the condition the client-side
`TCSGPT4oBackend` (in the main repo's `llm/backends/`) detects and raises
a clear "refresh TCS_SESSION_COOKIE" error for, rather than trying to
parse HTML as JSON.

## /execute contract

Multipart form fields:

| field             | required | notes                                              |
|-------------------|----------|-----------------------------------------------------|
| `prompt_id`       | yes      | logged only, never stored                          |
| `text`            | yes      | the full rendered prompt + evidence text            |
| `images`          | no       | repeated file fields, PNG                           |
| `system`          | no       | system prompt                                       |
| `response_schema` | no       | JSON Schema as a string; enables structured output  |
| `temperature`     | no       | default `0`                                         |
| `seed`            | no       |                                                       |
| `max_tokens`      | no       |                                                       |
| `image_detail`    | no       | default `"high"`                                    |

Response JSON: `ok, output_text, output_json, model, system_fingerprint,
usage{prompt_tokens, completion_tokens}, latency_ms, request_id, error,
used_json_object_fallback`.

When `response_schema` is given, structured output is requested via
`response_format={"type":"json_schema", "strict": true}`; if the
deployment rejects that, it falls back to `{"type":"json_object"}`
automatically and sets `used_json_object_fallback: true` so the caller
knows the shape wasn't strictly enforced.

## Running this server's own tests

```bash
cd server
pip install -r requirements.txt pytest
python -m pytest
```

No real OpenAI/Azure call is made in these tests -- `openai_client.complete`
is monkeypatched, mirroring the parent repo's own test convention
(hand-rolled fakes, no HTTP-mocking library).
