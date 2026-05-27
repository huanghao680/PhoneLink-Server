#!/usr/bin/env python3
"""
PicoClaw PhoneLink 接收服务器 v2
支持 WebSocket (8766) + HTTP (8765) 双通道

WebSocket 连接方式：
    ws://服务器IP:8766
    客户端发送 JSON → 服务器存储并回复确认

HTTP API 保持不变，用于查询数据。
"""

import json
import os
import sys
import time
import asyncio
import argparse
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

try:
    import websockets
    import websockets.sync.client
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    print("⚠️  websockets 未安装，仅支持 HTTP 模式")

# === 配置 ===

DATA_DIR = Path(__file__).parent / "data"
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.json"
MAX_HISTORY = 100

# === 数据存储 ===

def ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)

def save_data(data: dict) -> dict:
    """保存最新数据和历史记录"""
    ensure_data_dir()
    data["_received_at"] = datetime.now().isoformat()

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            history = []

    history.append(data)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    return data

def get_latest() -> dict:
    if LATEST_FILE.exists():
        with open(LATEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_history(limit: int = 20) -> list:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data[-limit:]
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return []

def print_data_summary(saved: dict):
    """打印收到数据的摘要"""
    print("\n" + "=" * 50)
    print(f"📥 收到数据 [{saved.get('timestampReadable', '?')}]")
    print(f"   设备: {saved.get('deviceBrand', '?')} {saved.get('deviceModel', '?')}")
    print(f"   应用: {saved.get('foregroundLabel', 'unknown')}")
    print(f"   电量: {saved.get('batteryLevel', '?')}%")
    print(f"   位置: {saved.get('latitude', 0):.6f}, {saved.get('longitude', 0):.6f}")
    if saved.get("locationAddress"):
        print(f"   地址: {saved['locationAddress']}")
    print("=" * 50)

def format_phone_data(data: dict) -> str:
    if not data:
        return "暂无数据"
    lines = [
        f"📱 手机数据 ({data.get('timestampReadable', 'unknown')})",
        f"",
        f"📍 位置: {data.get('latitude', 0):.6f}, {data.get('longitude', 0):.6f}",
        f"   地址: {data.get('locationAddress', 'N/A')}",
        f"   精度: ±{data.get('accuracy', 0)}m",
        f"",
        f"📱 应用: {data.get('foregroundLabel', 'unknown')}",
        f"   包名: {data.get('foregroundPackage', 'unknown')}",
        f"",
        f"🔋 电量: {data.get('batteryLevel', '?')}% ({data.get('batteryStatus', '?')})",
        f"   充电: {'是' if data.get('isCharging') else '否'}",
        f"   温度: {data.get('batteryTemperature', 0)}°C",
        f"",
        f"📲 设备: {data.get('deviceBrand', '?')} {data.get('deviceModel', '?')}",
        f"   系统: Android {data.get('androidVersion', '?')} (API {data.get('sdkInt', '?')})",
        f"",
        f"📶 WiFi: {'已连接' if data.get('isWifiConnected') else '未连接'}",
        f"   网络: {data.get('mobileNetworkType', 'unknown')}",
    ]
    return "\n".join(lines)

# === PicoClaw 转发 ===

forward_to_picoclaw = False

def forward_data(data: dict):
    try:
        workspace = Path(os.environ.get("PICOCRAWL_WORKSPACE",
            Path(__file__).parent.parent.parent))
        phone_data_dir = workspace / "phone_data"
        phone_data_dir.mkdir(exist_ok=True)
        with open(phone_data_dir / "latest.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"   ↳ 已转发到 PicoClaw workspace")
    except Exception as e:
        print(f"   ↳ 转发失败: {e}")

# === WebSocket 服务器 ===

ws_connections = set()

async def ws_handler(websocket):
    """处理 WebSocket 连接"""
    ws_connections.add(websocket)
    remote = websocket.remote_address
    print(f"🔌 WebSocket 已连接: {remote[0]}:{remote[1]}")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                saved = save_data(data)

                # 回复确认
                await websocket.send(json.dumps({
                    "ok": True,
                    "received": saved.get("timestampReadable"),
                    "device": f"{saved.get('deviceBrand', '?')} {saved.get('deviceModel', '?')}"
                }, ensure_ascii=False))

                print_data_summary(saved)

                if forward_to_picoclaw:
                    forward_data(saved)

            except json.JSONDecodeError as e:
                await websocket.send(json.dumps({
                    "ok": False,
                    "error": f"invalid json: {e}"
                }))
            except Exception as e:
                await websocket.send(json.dumps({
                    "ok": False,
                    "error": str(e)
                }))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_connections.discard(websocket)
        print(f"🔌 WebSocket 断开: {remote[0]}:{remote[1]}")

def start_ws_server(host: str, port: int):
    """在单独线程中启动 WebSocket 服务器"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        async with websockets.serve(ws_handler, host, port):
            print(f"   WebSocket: ws://{host}:{port}")
            await asyncio.Future()  # 永久运行

    loop.run_until_complete(run())

# === HTTP 服务器 ===

class PhoneDataHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/status":
            ws_count = len(ws_connections)
            self.send_json(200, {
                "service": "PicoClaw PhoneLink Server v2",
                "status": "running",
                "has_data": LATEST_FILE.exists(),
                "history_count": len(get_history(999)),
                "ws_connections": ws_count,
                "channels": {
                    "websocket": f"ws://0.0.0.0:8766",
                    "http_post": "POST /api/phone-data",
                    "http_get": "GET /api/phone-data",
                }
            })
        elif self.path == "/api/phone-data" or self.path.startswith("/api/phone-data?"):
            data = get_latest()
            if "format=text" in self.path:
                self.send_text(200, format_phone_data(data))
            else:
                self.send_json(200, data)
        elif self.path.startswith("/api/history"):
            limit = 20
            if "limit=" in self.path:
                try:
                    limit = int(self.path.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            history = get_history(limit)
            self.send_json(200, {"count": len(history), "data": history})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/phone-data":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_json(400, {"error": "empty body"})
                return
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                self.send_json(400, {"error": f"invalid json: {e}"})
                return

            saved = save_data(data)
            print_data_summary(saved)

            if forward_to_picoclaw:
                forward_data(saved)

            self.send_json(200, {"ok": True, "received": saved.get("timestampReadable")})
        else:
            self.send_json(404, {"error": "not found"})

    def send_json(self, code: int, data: dict):
        response = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def send_text(self, code: int, text: str):
        response = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

# === 启动 ===

def main():
    global forward_to_picoclaw

    parser = argparse.ArgumentParser(description="PicoClaw PhoneLink Server v2")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 端口 (default: 8765)")
    parser.add_argument("--ws-port", type=int, default=8766, help="WebSocket 端口 (default: 8766)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--forward", action="store_true", help="转发到 PicoClaw workspace")
    args = parser.parse_args()

    forward_to_picoclaw = args.forward
    ensure_data_dir()

    print("🦞 PicoClaw PhoneLink Server v2")
    print(f"   HTTP:     http://{args.host}:{args.port}")
    if HAS_WEBSOCKETS:
        print(f"   WebSocket: ws://{args.host}:{args.ws_port}")
    print(f"   数据目录:  {DATA_DIR}")
    print(f"   转发:      {'是' if forward_to_picoclaw else '否'}")
    print()

    # 启动 WebSocket 服务器（单独线程）
    if HAS_WEBSOCKETS:
        ws_thread = threading.Thread(
            target=start_ws_server,
            args=(args.host, args.ws_port),
            daemon=True
        )
        ws_thread.start()

    # 启动 HTTP 服务器（主线程）
    server = HTTPServer((args.host, args.port), PhoneDataHandler)
    print("等待手机数据... (Ctrl+C 停止)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        server.server_close()

if __name__ == "__main__":
    main()
