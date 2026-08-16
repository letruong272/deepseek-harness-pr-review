"""OpenAI-compatible chat completion qua stdlib (không cần thêm dependency)."""
import json
import time
import urllib.error
import urllib.request


def chat(messages: list[dict], *, model: str, api_key: str, base_url: str,
         max_tokens: int = 16384, retries: int = 3) -> str:
    """POST {base_url}/chat/completions. Retry tối đa `retries` lần (timeout/429/5xx).

    max_tokens mặc định 16384: deepseek-v4-flash là reasoning model, dành phần
    lớn tokens cho reasoning_content trước khi trả content thật — 4096 quá nhỏ
    (finish_reason=length, content rỗng).
    """
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
                content = data["choices"][0]["message"]["content"]
                if content is None:
                    raise RuntimeError("chat returned null content")
                return content
        except urllib.error.HTTPError as e:
            retryable = e.code >= 500 or e.code == 429
            if not retryable:
                raise RuntimeError(
                    f"chat failed (HTTP {e.code}): "
                    f"{e.read().decode(errors='replace')[:300]}"
                ) from e
            last_err = e
            retry_after = e.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 30))
                continue
        except urllib.error.URLError as e:
            last_err = e
        except KeyError as e:
            raise RuntimeError("chat returned malformed response: missing key "
                               f"{e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"chat returned non-JSON response: {e}") from e
        time.sleep(2 * attempt)
    raise RuntimeError(f"chat failed after {retries} retries: {last_err}")
