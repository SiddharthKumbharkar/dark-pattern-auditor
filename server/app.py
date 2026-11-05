"""FastAPI relay deployed INSIDE the TCS workspace on port 8000, reached
by the auditor's TCSGPT4oBackend (llm/backends/tcs_gpt4o_backend.py)
through the code-server proxy:

    POST https://rniazure.tcsapps.com/dev-workspaces/<workspace-id>/proxy/8000/execute

A thin relay only -- it turns a multipart request into one GPT-4o chat
completion and relays the result back. It does NOT store prompts/text/
images: prompt_id is logged (see logger.info below), the request body
itself never touches disk. Prompts stay versioned in the client repo
(prompts/*.txt) so they're reusable against a future local-model backend
without this server knowing anything about their content.

Run from inside this directory (see README.md):
    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import base64
import json
import logging
import time
import uuid
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import openai_client
from models import ExecuteResponse, HealthResponse, UsageTokens

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tcs_llm_server")

app = FastAPI(title="TCS GPT-4o relay")

# Generous headroom over a tiled episode's worth of screenshots (see
# llm/image_tiling.py on the client side) -- not a published API limit,
# just this relay's own input-validation ceiling.
MAX_IMAGES_PER_REQUEST = 40
MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    status = openai_client.backend_status()
    return HealthResponse(
        ok=status["configured"], model=status["model"], backend=status["backend"], configured=status["configured"]
    )


@app.post("/execute", response_model=ExecuteResponse)
async def execute(
    prompt_id: str = Form(...),
    text: str = Form(...),
    system: Optional[str] = Form(None),
    response_schema: Optional[str] = Form(None),
    temperature: float = Form(0.0),
    seed: Optional[int] = Form(None),
    max_tokens: Optional[int] = Form(None),
    image_detail: str = Form("high"),
    images: List[UploadFile] = File(default=[]),
) -> ExecuteResponse:
    request_id = str(uuid.uuid4())

    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=413, detail=f"too many images ({len(images)} > {MAX_IMAGES_PER_REQUEST})"
        )

    total_bytes = 0
    images_b64 = []
    for upload in images:
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail=f"total upload size exceeds {MAX_TOTAL_UPLOAD_BYTES} bytes"
            )
        images_b64.append(base64.standard_b64encode(content).decode("ascii"))

    parsed_schema = None
    if response_schema:
        try:
            parsed_schema = json.loads(response_schema)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"response_schema is not valid JSON: {exc}")

    start = time.monotonic()
    try:
        result = openai_client.complete(
            text=text,
            system=system,
            images_b64=images_b64,
            response_schema=parsed_schema,
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
            image_detail=image_detail,
        )
    except openai_client.BackendNotConfiguredError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    duration_ms = (time.monotonic() - start) * 1000

    # prompt_id only -- never the prompt/evidence/image content itself.
    logger.info(
        "execute prompt_id=%s model=%s ok=%s tokens_in=%s tokens_out=%s latency_ms=%.1f",
        prompt_id, result.model, result.ok, result.prompt_tokens, result.completion_tokens, duration_ms,
    )

    return ExecuteResponse(
        ok=result.ok,
        output_text=result.output_text,
        output_json=result.output_json,
        model=result.model,
        system_fingerprint=result.system_fingerprint,
        usage=UsageTokens(prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens),
        latency_ms=result.latency_ms,
        request_id=result.request_id or request_id,
        error=result.error,
        used_json_object_fallback=result.used_json_object_fallback,
    )
