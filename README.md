# Foundry Relay

Foundry Relay turns one Microsoft Foundry agent into a secure, OpenAI-compatible API. It ships as a single FastAPI service containing both the provider dashboard and API routes.

The included configuration targets:

- Project: `https://satviksingh-resource.services.ai.azure.com/api/projects/satviksingh`
- Agent: `jarvis`
- Version: `2`
- Public model ID: `jarvis-2`

## What it exposes

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/v1/responses` | Native Responses API with streaming |
| `POST` | `/v1/chat/completions` | Chat Completions compatibility adapter with streaming |
| `POST` | `/v1/audio/speech` | OpenAI-compatible Text-to-Speech (TTS) |
| `GET` | `/v1/models` | OpenAI-style model discovery |
| `GET` | `/reference` | Interactive API reference |
| `GET` | `/healthz` | Process health check |
| `GET` | `/readyz` | Configuration readiness check |

Every `/v1` route requires the provider key as `Authorization: Bearer ...`, `api-key`, or `x-api-key`.

## Local setup

Prerequisites: Python 3.10 or newer, Azure CLI, and access to the configured Microsoft Foundry project.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
az login
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

Before starting the service, replace both example keys in `.env`. Generate independent secrets with:

```powershell
python -c "import secrets; print('PROVIDER_API_KEY=frly_' + secrets.token_urlsafe(32)); print('ADMIN_API_KEY=frly_admin_' + secrets.token_urlsafe(32))"
```

The provider key authenticates client requests. The separate administrator key unlocks the real provider key in the dashboard. Neither key is included in the public configuration response or HTML.

## Azure authentication

`DefaultAzureCredential` follows the standard Azure credential chain.

- Locally, run `az login` with an account that can access the Foundry project.
- In Azure, prefer a managed identity and assign it the required project role.
- On another host, set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` for a service principal.

Do not put Azure credentials or either provider key in browser-side code.

## Use it with the OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_PROVIDER_API_KEY",
    base_url="https://your-provider.example/v1",
)

response = client.responses.create(
    model="jarvis-2",
    input="Tell me what you can help with.",
)

print(response.output_text)
```

Stream text as it is generated:

```python
stream = client.responses.create(
    model="jarvis-2",
    input="Tell me what you can help with.",
    stream=True,
)

for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="", flush=True)
```

Chat Completions clients work too:

```python
response = client.chat.completions.create(
    model="jarvis-2",
    messages=[{"role": "user", "content": "Hello, Jarvis."}],
)
print(response.choices[0].message.content)
```

Generate speech (Text-to-Speech):

```python
speech_response = client.audio.speech.create(
    model="tts-1",
    voice="onyx",  # onyx, alloy, echo, fable, nova, shimmer
    input="Hello! Azure Speech synthesis is now available via Foundry Relay.",
)
speech_response.stream_to_file("output.mp3")
```

## Docker deployment

Build the image:

```bash
docker build -t foundry-relay .
```

Run it with an environment file:

```bash
docker run --rm -p 8000:8000 --env-file .env foundry-relay
```

For production, set `PUBLIC_BASE_URL` to the public HTTPS origin, such as `https://provider.example.com`. The dashboard automatically appends `/v1`. Terminate TLS at your platform or reverse proxy, keep `.env` out of the image, and add platform-level rate limits appropriate for your Azure quota.

## Verify changes

```powershell
pip install -r requirements-dev.txt
ruff check .
pytest
```

Tests use a fake Foundry client and never send requests to Azure.
