"""Deterministic stand-ins for the system's three external dependencies.

Shared by the test suite and by `eval/run_eval.py --offline`, so both exercise
the same code paths: real LangGraph, real Chroma, real MCP protocol, with only
the embedding API, the Anthropic API, and outbound HTTP replaced.
"""

import math
from contextlib import asynccontextmanager

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from app.mcp.server import mcp as mcp_app

EMBED_DIM = 16


def fake_embed_texts(texts, client=None):
    """Deterministic bag-of-characters embedding, unit-normalised.

    Not semantic, but stable, and similar strings do come out closer than
    dissimilar ones - which is all retrieval needs in order to be exercised.
    """
    vectors = []
    for text in texts:
        v = [0.0] * EMBED_DIM
        for i, ch in enumerate(text.lower()):
            v[(ord(ch) + i) % EMBED_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / norm for x in v])
    return vectors


@asynccontextmanager
async def in_memory_mcp_session():
    """An initialized ClientSession talking to the real MCPServer in-process.

    Same protocol path as production - initialize handshake, declared tool
    schemas, JSON-RPC framing - over the SDK's in-memory transport rather than
    a subprocess, so the tools' own dependencies stay patchable from here.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                mcp_app._lowlevel_server.run,
                server_read,
                server_write,
                mcp_app._lowlevel_server.create_initialization_options(),
            )
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                yield session
            tg.cancel_scope.cancel()


def flatten_exception(exc: BaseException) -> list[BaseException]:
    """Flatten anyio ExceptionGroups so a caller can inspect the real cause.

    A task group re-raises its children wrapped in a group, so a plain
    `isinstance` check would miss an error the code raised correctly.
    """
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for child in exc.exceptions for leaf in flatten_exception(child)]
    return [exc]
