#!/usr/bin/env python3
"""
Kilo API Server - Exposes an OpenAI-compatible /v1/chat/completions endpoint
that uses Kilo CLI as the backend LLM.

Features:
- OpenAI-compatible chat completions API
- Streaming support (SSE)
- Vision/image support (via base64 or URL)
- Multi-turn conversation support

Usage:
    python kilo_api_server.py [--port 8000] [--host 127.0.0.1]

The server exposes:
    POST /v1/chat/completions - OpenAI-compatible chat completion endpoint
    GET /v1/models - List available models
    GET /health - Health check endpoint

Example curl request:
    curl -X POST http://localhost:8000/v1/chat/completions \\
        -H "Content-Type: application/json" \\
        -d '{"model": "kilo-default", "messages": [{"role": "user", "content": "Hello!"}]}'

Example with image (vision):
    curl -X POST http://localhost:8000/v1/chat/completions \\
        -H "Content-Type: application/json" \\
        -d '{"model": "kilo-default", "messages": [{"role": "user", "content": [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]}]}'
"""

import asyncio
import base64
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from typing import Optional, Union

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("kilo-api")

app = FastAPI(
    title="Kilo API Server",
    description="OpenAI-compatible API server using Kilo CLI as backend",
    version="1.0.0",
)

# Default model to use
DEFAULT_MODEL = "kilo-default"


# Pydantic models for OpenAI-compatible API
class ImageURL(BaseModel):
    url: str
    detail: Optional[str] = "auto"


class ContentText(BaseModel):
    type: str = "text"
    text: str


class ContentImage(BaseModel):
    type: str = "image_url"
    image_url: ImageURL


ContentPart = Union[ContentText, ContentImage]


class ChatMessage(BaseModel):
    role: str
    content: Union[str, list[ContentPart]]
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.0
    max_tokens: Optional[int] = 2048
    stream: Optional[bool] = False
    stop: Optional[list[str]] = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage


class DeltaMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class StreamChoice(BaseModel):
    index: int
    delta: DeltaMessage
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "kilo"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


async def download_image(url: str) -> bytes:
    """Download image from URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def extract_base64_data(url: str) -> tuple[bytes, str]:
    """Extract base64 data from data URL."""
    # data:image/png;base64,xxxxx
    match = re.match(r"data:([^;]+);base64,(.+)", url)
    if not match:
        raise ValueError(f"Invalid data URL format")
    
    media_type = match.group(1)
    base64_data = match.group(2)
    return base64.b64decode(base64_data), media_type


async def process_image(image_url: ImageURL) -> tuple[str, bytes]:
    """
    Process an image from URL or base64 data.
    Returns (temp_file_path, image_bytes).
    """
    url = image_url.url
    
    if url.startswith("data:"):
        # Base64 encoded image
        image_bytes, media_type = extract_base64_data(url)
    else:
        # URL to download
        image_bytes = await download_image(url)
        # Try to determine media type from URL or default to png
        media_type = "image/png"
        if url.endswith(".jpg") or url.endswith(".jpeg"):
            media_type = "image/jpeg"
        elif url.endswith(".gif"):
            media_type = "image/gif"
        elif url.endswith(".webp"):
            media_type = "image/webp"
    
    # Determine extension
    ext = media_type.split("/")[-1] if "/" in media_type else "png"
    if ext == "jpeg":
        ext = "jpg"
    
    # Write to temp file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
    temp_file.write(image_bytes)
    temp_file.close()
    
    return temp_file.name, image_bytes


def format_content(content: Union[str, list[ContentPart]]) -> tuple[str, list[str]]:
    """
    Format message content into text prompt and list of image file paths.
    
    Returns:
        tuple of (text_prompt, image_file_paths)
    """
    if isinstance(content, str):
        return content, []
    
    text_parts = []
    image_files = []
    
    for part in content:
        if part.type == "text":
            text_parts.append(part.text)
        elif part.type == "image_url":
            # Image will be processed separately
            text_parts.append("[IMAGE ATTACHED]")
    
    return "\n".join(text_parts), image_files


async def process_content(content: Union[str, list[ContentPart]]) -> tuple[str, list[str]]:
    """
    Process message content, downloading images and creating temp files.
    
    Returns:
        tuple of (text_prompt, image_file_paths)
    """
    if isinstance(content, str):
        return content, []
    
    text_parts = []
    image_files = []
    
    for part in content:
        if part.type == "text":
            text_parts.append(part.text)
        elif part.type == "image_url":
            # Process image synchronously for now
            try:
                file_path, _ = await process_image(part.image_url)
                image_files.append(file_path)
                text_parts.append("[IMAGE ATTACHED]")
            except Exception as e:
                logger.error(f"Failed to process image: {e}")
                text_parts.append(f"[IMAGE ERROR: {e}]")
    
    return "\n".join(text_parts), image_files


def format_messages_as_prompt(messages: list[ChatMessage]) -> str:
    """Format OpenAI-style messages into a single prompt for Kilo."""
    parts = []
    for msg in messages:
        role = msg.role.upper()
        content = msg.content
        if isinstance(content, list):
            # Extract just text for the prompt
            text_parts = [p.text for p in content if p.type == "text"]
            content = "\n".join(text_parts)
        
        if role == "SYSTEM":
            parts.append(f"[SYSTEM]: {content}")
        elif role == "USER":
            parts.append(f"[USER]: {content}")
        elif role == "ASSISTANT":
            parts.append(f"[ASSISTANT]: {content}")
        else:
            parts.append(f"[{role}]: {content}")
    return "\n".join(parts)


async def run_kilo(
    prompt: str,
    model: Optional[str] = None,
    image_files: Optional[list[str]] = None,
) -> tuple[str, dict]:
    """
    Run Kilo CLI with the given prompt and return the response.
    
    Returns:
        tuple of (response_text, metadata) where metadata includes tokens, etc.
    """
    cmd = ["kilo", "run", prompt, "--format", "json", "--auto"]
    
    if model and model != DEFAULT_MODEL:
        cmd.extend(["-m", model])
    
    # Add image files if provided
    if image_files:
        for img_file in image_files:
            cmd.extend(["-f", img_file])
    
    logger.debug(f"Running command: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await process.communicate()
    
    # Clean up temp image files
    if image_files:
        for img_file in image_files:
            try:
                os.unlink(img_file)
            except Exception:
                pass
    
    if process.returncode != 0:
        logger.error(f"Kilo CLI error: {stderr.decode()}")
        raise RuntimeError(f"Kilo CLI failed with code {process.returncode}: {stderr.decode()}")
    
    # Parse JSON events from stdout
    response_text = ""
    metadata = {"tokens": {"input": 0, "output": 0, "total": 0}}
    
    for line in stdout.decode().strip().split("\n"):
        if not line:
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "text":
                response_text += event.get("part", {}).get("text", "")
            elif event.get("type") == "step_finish":
                part = event.get("part", {})
                tokens = part.get("tokens", {})
                metadata["tokens"] = {
                    "input": tokens.get("input", 0),
                    "output": tokens.get("output", 0),
                    "total": tokens.get("total", 0),
                }
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON line: {line[:100]}... Error: {e}")
    
    return response_text, metadata


async def run_kilo_stream(
    prompt: str,
    model: Optional[str] = None,
    image_files: Optional[list[str]] = None,
):
    """
    Run Kilo CLI and yield response chunks for streaming.
    """
    cmd = ["kilo", "run", prompt, "--format", "json", "--auto"]
    
    if model and model != DEFAULT_MODEL:
        cmd.extend(["-m", model])
    
    # Add image files if provided
    if image_files:
        for img_file in image_files:
            cmd.extend(["-f", img_file])
    
    logger.debug(f"Running streaming command: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    
    # Send initial chunk with role
    initial_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model or DEFAULT_MODEL,
        choices=[StreamChoice(index=0, delta=DeltaMessage(role="assistant", content=""))],
    )
    yield f"data: {initial_chunk.model_dump_json()}\n\n"
    
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        
        line_str = line.decode().strip()
        if not line_str:
            continue
        
        try:
            event = json.loads(line_str)
            if event.get("type") == "text":
                text = event.get("part", {}).get("text", "")
                if text:
                    chunk = ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=model or DEFAULT_MODEL,
                        choices=[StreamChoice(index=0, delta=DeltaMessage(content=text))],
                    )
                    yield f"data: {chunk.model_dump_json()}\n\n"
            elif event.get("type") == "step_finish":
                # Send final chunk
                final_chunk = ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=model or DEFAULT_MODEL,
                    choices=[StreamChoice(index=0, delta=DeltaMessage(), finish_reason="stop")],
                )
                yield f"data: {final_chunk.model_dump_json()}\n\n"
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON line: {line_str[:100]}... Error: {e}")
    
    yield "data: [DONE]\n\n"
    
    # Clean up temp image files
    if image_files:
        for img_file in image_files:
            try:
                os.unlink(img_file)
            except Exception:
                pass
    
    # Check for errors
    stderr = await process.stderr.read()
    if process.returncode and process.returncode != 0:
        logger.error(f"Kilo CLI error: {stderr.decode()}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "backend": "kilo-cli"}


@app.get("/v1/models")
async def list_models():
    """List available models."""
    # Return a default model - Kilo CLI handles model selection
    return ModelList(
        data=[
            ModelInfo(
                id=DEFAULT_MODEL,
                created=int(time.time()),
                owned_by="kilo",
            )
        ]
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completion endpoint.
    
    Accepts messages in OpenAI format and returns completions from Kilo CLI.
    Supports both streaming and non-streaming responses.
    Supports vision/image inputs via base64 or URL.
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages cannot be empty")
    
    # Process all messages to extract text and images
    all_text_parts = []
    all_image_files = []
    
    for msg in request.messages:
        text_content, image_files = await process_content(msg.content)
        role = msg.role.upper()
        
        if role == "SYSTEM":
            all_text_parts.append(f"[SYSTEM]: {text_content}")
        elif role == "USER":
            all_text_parts.append(f"[USER]: {text_content}")
        elif role == "ASSISTANT":
            all_text_parts.append(f"[ASSISTANT]: {text_content}")
        else:
            all_text_parts.append(f"[{role}]: {text_content}")
        
        all_image_files.extend(image_files)
    
    prompt = "\n".join(all_text_parts)
    
    # Extract model (remove prefix if provided as "kilo/model")
    model = request.model
    if model.startswith("kilo/"):
        model = model[5:]
    
    if request.stream:
        # Streaming response
        return StreamingResponse(
            run_kilo_stream(prompt, model, all_image_files if all_image_files else None),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    else:
        # Non-streaming response
        try:
            response_text, metadata = await run_kilo(
                prompt, model, all_image_files if all_image_files else None
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        
        return ChatCompletionResponse(
            id=completion_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=response_text),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=metadata["tokens"]["input"],
                completion_tokens=metadata["tokens"]["output"],
                total_tokens=metadata["tokens"]["total"],
            ),
        )


@app.on_event("startup")
async def startup_event():
    """Verify Kilo CLI is available on startup."""
    try:
        process = await asyncio.create_subprocess_exec(
            "kilo", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        if process.returncode == 0:
            logger.info("Kilo CLI is available")
        else:
            logger.warning("Kilo CLI returned non-zero exit code")
    except FileNotFoundError:
        logger.error("Kilo CLI not found! Make sure 'kilo' is in your PATH")
        sys.exit(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Kilo API Server - OpenAI-compatible API using Kilo CLI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()
    
    import uvicorn
    uvicorn.run(
        "kilo_api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
