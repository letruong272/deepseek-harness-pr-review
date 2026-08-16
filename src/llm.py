"""OpenAI-compatible chat completion qua stdlib (không cần thêm dependency)."""
import json
import time
import urllib.error
import urllib.request


def chat(messages: list[dict], *, model: str, api_key: str, base_url: str,
         max_tokens: int = 4096, retries: int = 3) -> str:
    """POST {base_url}/chat/completions. Retry tối đa `retries` lần (timeout/429/5xx)."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()

    last_err = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"chat failed after {retries} retries: {last_err}")
