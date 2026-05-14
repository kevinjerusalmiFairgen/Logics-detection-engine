"""
Claude Opus 4.6 (Vertex AI) helper for Steps 3-6.

Provides call_opus_json() to run prompts with embedded JSON inputs.
Returns parsed JSON result and token usage for pricing.
"""

import json
import os
import re
import time
from typing import Any, Dict, List


def call_opus_json(
    prompt: str,
    json_blocks: Dict[str, Any],
    expected_keys: List[str] = None,
    show_progress: bool = True,
) -> tuple[Any, Dict[str, int]]:
    """
    Call Claude Opus 4.6 on Vertex AI with prompt + embedded JSON inputs.

    Args:
        prompt: Full instruction (references "INPUT DATA below" etc.)
        json_blocks: {"filename.json": data_dict, ...} - embedded in message
        expected_keys: Keys to extract from result (e.g. ["questions_mapped", "unmapped_vars"])
        show_progress: Print progress

    Returns:
        (parsed_result, {"input_tokens": N, "output_tokens": N})
    """
    from anthropic import AnthropicVertex

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "fairgen-common")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-east5")

    # Build user message: prompt + JSON blocks
    parts = [prompt, "\n\n" + "=" * 80 + "\nINPUT DATA (JSON)\n" + "=" * 80]
    for filename, data in json_blocks.items():
        parts.append(f"\n\n### {filename}\n```json\n")
        parts.append(json.dumps(data, indent=2))
        parts.append("\n```")

    user_text = "".join(parts)

    if show_progress:
        print("  Sending to Claude Opus 4.6 (Vertex AI, streaming)...")
    start = time.time()

    client = AnthropicVertex(project_id=project, region=location)

    text = ""
    usage = {"input_tokens": 0, "output_tokens": 0}
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=65536,
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        for text_delta in stream.text_stream:
            text += text_delta
        final = stream.get_final_message()
        if final and hasattr(final, "usage") and final.usage:
            u = final.usage
            usage["input_tokens"] = getattr(u, "input_tokens", 0)
            usage["output_tokens"] = getattr(u, "output_tokens", 0)

    elapsed = time.time() - start
    if show_progress:
        print(f"  Response received in {elapsed:.1f}s")

    result = _parse_json_response(text)

    return result, usage


def _parse_json_response(text: str) -> dict:
    """Extract JSON from model response (may be wrapped in markdown/code blocks)."""
    text = (text or "").strip()
    for pattern in [
        r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
        r"```json\s*(.*?)```",
    ]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            text = m.group(1).strip()
            break
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Failed to parse JSON from response: {e}") from e


def estimate_opus_cost(input_tokens: int, output_tokens: int) -> float:
    """Vertex AI pricing: $5/1M input, $25/1M output."""
    return (input_tokens / 1_000_000 * 5) + (output_tokens / 1_000_000 * 25)
