import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.llm import chat


class _Handler(BaseHTTPRequestHandler):
    captured = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _Handler.captured["body"] = body
        response = {"choices": [{"message": {"content": "hello"}}]}
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


def test_chat_ok(server):
    port = server.server_address[1]
    out = chat([{"role": "user", "content": "hi"}], model="m",
               api_key="k", base_url=f"http://127.0.0.1:{port}/v1")
    assert out == "hello"
    assert _Handler.captured["body"]["model"] == "m"
    assert _Handler.captured["body"]["messages"][0]["content"] == "hi"


class _FlakyHandler(BaseHTTPRequestHandler):
    count = 0

    def do_POST(self):
        _FlakyHandler.count += 1
        if _FlakyHandler.count < 3:
            self.send_response(500)
            self.end_headers()
            return
        data = json.dumps({"choices": [{"message": {"content": "retried"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_chat_retries(monkeypatch):
    _FlakyHandler.count = 0
    srv = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        out = chat([{"role": "user", "content": "hi"}], model="m", api_key="k",
                   base_url=f"http://127.0.0.1:{port}/v1", retries=3)
        assert out == "retried"
        assert _FlakyHandler.count == 3
    finally:
        srv.shutdown()


def test_chat_gives_up(monkeypatch):
    class _AlwaysFail(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), _AlwaysFail)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        with pytest.raises(RuntimeError, match="chat failed after 3 retries"):
            chat([{"role": "user", "content": "hi"}], model="m", api_key="k",
                 base_url=f"http://127.0.0.1:{port}/v1", retries=3)
    finally:
        srv.shutdown()


class _UnauthorizedHandler(BaseHTTPRequestHandler):
    count = 0

    def do_POST(self):
        _UnauthorizedHandler.count += 1
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


def test_chat_does_not_retry_401():
    _UnauthorizedHandler.count = 0
    srv = HTTPServer(("127.0.0.1", 0), _UnauthorizedHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        with pytest.raises(RuntimeError, match="HTTP 401"):
            chat([{"role": "user", "content": "hi"}], model="m", api_key="bad",
                 base_url=f"http://127.0.0.1:{port}/v1", retries=3)
        assert _UnauthorizedHandler.count == 1
    finally:
        srv.shutdown()
