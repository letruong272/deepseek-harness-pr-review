# Harness PR Review

Headless PR review chạy local dựa trên DeepSeek Harness SDK: deep-dive code,
xác minh PR description theo từng claim, kiểm tra docs trong repo có đúng với
thực tế không, phân tích tác động tới requirement, human-in-the-loop khi không
chắc (≤20 chữ/câu). Output: report tiếng Việt local + 1 comment tiếng Anh lên PR.

## Cài đặt

Yêu cầu: Python 3.10+ (khuyến nghị 3.11), `gh` CLI đã auth.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'   # zsh cần quote; SDK lấy từ PyPI (deepseek-harness-sdk)
gh auth login          # bắt buộc
export DEEPSEEK_API_KEY=sk-...   # xem .env.example
```

## Dùng

Chạy từ thư mục repo này (cần PYTHONPATH=src nếu không cài -e):

```bash
PYTHONPATH=src python -m src.run owner/repo 123              # interactive
PYTHONPATH=src python -m src.run owner/repo 123 --skip-human # batch, không hỏi
PYTHONPATH=src python -m src.run owner/repo 123 --no-post    # không post comment
PYTHONPATH=src python -m src.run owner/repo#123              # cú pháp rút gọn
```

Kết quả tại `sessions/<owner>/<repo>/pr-<n>/report.md` (đổi thư mục bằng `DSH_SESSION_ROOT`).

## Pipeline

1. **Snapshot** — fetch PR metadata, diff files, commits, review threads (GitHub REST + GraphQL)
2. **Claims** — LLM tách description thành claims kiểm chứng được
3. **Verify** — DeepSeek Harness agent deep-dive trong worktree disposable:
   verify từng claim, docs reality-check (MATCH/STALE/WRONG/FABRICATED),
   tác động requirement, trạng thái review threads
4. **Human gate** — hỏi xác nhận (≤20 chữ/câu) khi docs sai hoặc claim chưa chắc
5. **Synthesize** — report.md tiếng Việt + 1 comment tiếng Anh lên PR (idempotent)

## Chạy test

```bash
python -m pytest -v
```

## Cấu hình

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | API key DeepSeek |
| `DSH_MODEL` | `deepseek-v4-flash` | Model dùng cho agent + claim extraction |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | Endpoint OpenAI-compatible |
| `DSH_SESSION_ROOT` | `sessions` | Thư mục lưu kết quả từng phase |
