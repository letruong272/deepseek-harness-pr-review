# Design: Headless PR Review Automation với DeepSeek Harness

- Ngày: 2026-08-16
- Trạng thái: Approved (3 phần thiết kế đã duyệt)

## Mục tiêu

Headless automation chạy local trên máy, dùng DeepSeek Harness (Python SDK) để:

1. Review code / business logic bằng deep-dive: hiểu rõ change tác động tới requirement như thế nào.
2. Kiểm tra PR description có mô tả đúng thực tế hay không (tách claims và verify từng claim).
3. Xem xét các comments khác trong PR (review threads, inline comments, trạng thái resolved).

## Nền tảng & Ràng buộc

- GitHub (dùng `gh` CLI / REST API), chạy local trên máy (không chạy trong CI).
- Requirement nằm trong docs của repo — nhưng **docs có thể sai (ước tính ~60%)**: cần xác minh docs có đang phản ánh đúng thực tế không; không tin docs mù quáng.
- Khi docs sai hoặc không chắc chắn → **human-in-the-loop**: hỏi câu ≤20 chữ, tổng hợp hoàn chỉnh, cô đọng, dễ hiểu.
- Report local bằng **tiếng Việt**, comment post lên PR bằng **tiếng Anh**.
- Chế độ mặc định: **interactive** (dừng hỏi khi cần); có `--skip-human` để chạy batch.

## Kiến trúc

```
harness-pr-review/
├── src/
│   ├── snapshot.py      # Phase 1: fetch PR data từ GitHub (gh CLI)
│   ├── claims.py        # Phase 2: tách claim từ description (LLM)
│   ├── verify.py        # Phase 3: deep-dive agent (DeepSeekHarness SDK)
│   ├── human_gate.py    # Phase 4: hỏi confirm interactive (≤20 chữ/câu)
│   ├── synthesize.py    # Phase 5: tổng hợp report VN + comment EN
│   └── run.py           # CLI entry: orchestrates các phase
├── sessions/<owner>/<repo>/pr-<n>/
│   ├── snapshot.json    # PR metadata + diff + review threads
│   ├── claims.json      # claim đã tách
│   ├── workspace/       # worktree (disposable, agent sửa được)
│   ├── findings.json    # kết quả verify từng claim + doc check
│   ├── answers.json     # câu trả lời human-in-loop
│   └── report.md        # report tiếng Việt
└── config (.env)        # DEEPSEEK_API_KEY, DSH_MODEL, repo mặc định
```

### Các khối

**`snapshot.py` (Phase 1)** — Gọi `gh api` lấy:
- PR metadata: title, body (description), base/head branch, author, labels, danh sách commits.
- Diff đầy đủ (`/pulls/{n}/files` hoặc `.diff`).
- Review threads: GraphQL `reviewThreads` (inline comments + trạng thái resolved/outdated). Review summary bodies và discussion chung trên PR (`/pulls/{n}/reviews`, `/issues/{n}/comments`) không nằm trong snapshot (scoped down so với draft đầu — chấp nhận được).
- Lưu vào `snapshot.json`.

**`claims.py` (Phase 2)** — Gọi LLM tách PR description thành claims có cấu trúc:
```json
{"id": "C1", "text": "...", "category": "feature|bugfix|refactor|perf|ux|docs",
 "files": ["..."], "docs": ["..."]}
```

**`verify.py` (Phase 3)** — Khởi tạo `DeepSeekHarness(cwd=workspace, ...)`, agent:
1. Verify từng claim vs code thực tế → `PASS / FAIL / PARTIAL / UNVERIFIED` + trích dẫn `file:line`.
2. Docs reality-check: đối chiếu docs với code → `MATCH / STALE / WRONG / FABRICATED`.
3. Impact analysis: thay đổi chạm requirement nào, có vỡ chỗ khác không (callers, tests, configs, data flow).
4. Review threads: comment chưa resolved còn đúng không, đã được fix trong commit mới chưa.
- Xuất `findings.json` có cấu trúc.

**`human_gate.py` (Phase 4)** — Đọc `findings.json`, **chỉ hỏi**:
- Claim `UNVERIFIED`.
- Docs `WRONG / FABRICATED` (bắt buộc confirm trước khi ghi nhận trong report).
- Mỗi câu hỏi ≤20 chữ, 1 câu hỏi 1 lúc, ghi `answers.json`.

**`synthesize.py` (Phase 5)** — Gom tất cả:
- `report.md` (tiếng Việt): bảng verdict từng claim, trạng thái docs, tác động requirement, thread chưa resolve, log confirm.
- Post **1 comment tiếng Anh duy nhất** lên PR (gh CLI): verdict, docs sai, action cần làm. Không spam.

**`run.py`** — CLI: `python -m src.run <owner>/<repo> <pr-number> [--skip-human] [--force] [--no-post] [--dry-run] [--fixtures DIR]`.
- Chạy tuần tự các phase; mỗi phase kết quả lưu file riêng.
- Phase lỗi → ghi `report.md` đánh dấu `FAILED` kèm lỗi + danh sách artifact đã có, exit 1. Do các phase sau phụ thuộc cứng vào phase trước (claims cần snapshot, verify cần claims+workspace), pipeline abort thay vì chạy tiếp với dữ liệu rác.

## Nguyên tắc

- Không đoán: claim không verify được → `UNVERIFIED`, đưa vào danh sách hỏi human.
- Docs `WRONG/FABRICATED` → bắt buộc qua human gate trước khi ghi nhận.
- Diff luôn xử lý theo từng file (files summary vào prompt; agent đọc code thực tế trong workspace, không nhét toàn bộ diff vào prompt) — áp dụng cho mọi kích thước diff.
- Re-run: phase đã có kết quả file → cần `--force` mới chạy lại (tiết kiệm token).

## Error Handling

- `gh` chưa auth / PR không tồn tại → báo lỗi rõ ràng, dừng ngay (không chạy agent).
- Model API lỗi (timeout, 429) → retry 3 lần; hết retry → phase đó đánh dấu `FAILED` trong report.

## Testing

- Unit test `claims.py`: fixture description → assert JSON schema + loại claim.
- Unit test `snapshot.py`: mock `gh api` (fixture JSON) → assert cấu trúc snapshot.
- Unit test `human_gate.py`: pipe stdin scripted → assert `answers.json`.
- Unit test `synthesize.py`: fixture findings → assert report.md có bảng verdict + comment EN đủ mục.
- E2E (opt-in, `--e2e`): chạy pipeline hết trên PR sample với fixture — không gọi model.

## Stack

- Python 3.10+.
- `deepseek-harness-sdk` (bundled runtime, không cần Node).
- `gh` CLI (đã auth).
- `pytest`. Không dependency nặng khác.
