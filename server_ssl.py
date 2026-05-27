#!/usr/bin/env python3
"""
PicoClaw PhoneLink 接收服务器 (HTTPS版)
接收来自 Android App 的手机数据，存储并可转发给 PicoClaw

使用方法：
    python3 server.py [--port 8765] [--forward] [--no-ssl]

功能：
    1. 接收 POST /api/phone-data → 存储 JSON
    2. GET  /api/phone-data      → 查询最新数据
    3. GET  /api/history         → 查询历史数据
    4. GET  /                    → 简单状态页面
"""

import json
import os
import ssl
import sys
import time
import argparse
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# === 配置 ===

DATA_DIR = Path(__file__).parent / "data"
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.json"
MAX_HISTORY = 100  # 保留最近100条记录

# === 数据存储 ===

def ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)

def save_data(data: dict):
    """保存最新数据和历史记录"""
    ensure_data_dir()

    # 添加接收时间
    data["_received_at"] = datetime.now().isoformat()

    # 保存最新
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 追加历史
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            history = []

    history.append(data)
    # 只保留最近 MAX_HISTORY 条
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    return data

def get_latest() -> dict:
    """获取最新数据"""
    if LATEST_FILE.exists():
        with open(LATEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_history(limit: int = 20) -> list:
    """获取历史数据"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data[-limit:]
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return []

def format_phone_data(data: dict) -> str:
    """格式化手机数据为可读文本"""
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
        f"   页面: {data.get('foregroundActivity', 'unknown')}",
        f"",
        f"🔋 电量: {data.get('batteryLevel', '?')}% ({data.get('batteryStatus', '?')})",
        f"   充电: {'是 (' + data.get('chargeSource', '?') + ')' if data.get('isCharging') else '否'}",
        f"   温度: {data.get('batteryTemperature', 0)}°C",
        f"",
        f"📲 设备: {data.get('deviceBrand', '?')} {data.get('deviceModel', '?')}",
        f"   系统: Android {data.get('androidVersion', '?')} (API {data.get('sdkInt', '?')})",
        f"   分辨率: {data.get('screenResolution', '?')}",
        f"",
        f"📶 WiFi: {'已连接' if data.get('isWifiConnected') else '未连接'}",
        f"   网络: {data.get('mobileNetworkType', 'unknown')}",
    ]
    return "\n".join(lines)

# === HTTP 服务器 ===

class PhoneDataHandler(BaseHTTPRequestHandler):
    """处理来自 PhoneLink App 的 HTTP 请求"""

    def do_GET(self):
        if self.path == "/" or self.path == "/status":
            self.send_json(200, {
                "service": "PicoClaw PhoneLink Server",
                "status": "running",
                "ssl": True,
                "has_data": LATEST_FILE.exists(),
                "history_count": len(get_history(999)),
                "usage": {
                    "POST /api/phone-data": "接收手机数据",
                    "GET /api/phone-data": "查询最新数据",
                    "GET /api/phone-data?format=text": "查询最新数据（文本格式）",
                    "GET /api/history": "查询历史数据",
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

            # 打印摘要到终端
            print("\n" + "=" * 50)
            print(f"📥 收到数据 [{saved.get('timestampReadable', '?')}]")
            print(f"   设备: {saved.get('deviceBrand', '?')} {saved.get('deviceModel', '?')}")
            print(f"   应用: {saved.get('foregroundLabel', 'unknown')}")
            print(f"   电量: {saved.get('batteryLevel', '?')}%")
            print(f"   位置: {saved.get('latitude', 0):.6f}, {saved.get('longitude', 0):.6f}")
            if saved.get("locationAddress"):
                print(f"   地址: {saved['locationAddress']}")
            print("=" * 50)

            # 可选：转发给 PicoClaw
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
        # 简化日志输出
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

# === PicoClaw 转发（可选） ===

forward_to_picoclaw = False

def forward_data(data: dict):
    """将数据转发给 PicoClaw（通过写入共享文件）"""
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

# === 启动 ===

def main():
    global forward_to_picoclaw

    parser = argparse.ArgumentParser(description="PicoClaw PhoneLink Server")
    parser.add_argument("--port", type=int, default=8765, help="监听端口 (default: 8765)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址 (default: 0.0.0.0)")
    parser.add_argument("--forward", action="store_true", help="转发数据到 PicoClaw workspace")
    parser.add_argument("--no-ssl", action="store_true", help="禁用SSL（仅本地调试用）")
    args = parser.parse_args()

    forward_to_picoclaw = args.forward
    ensure_data_dir()

    server = HTTPServer((args.host, args.port), PhoneDataHandler)

    # === SSL 配置 ===
    use_ssl = not args.no_ssl
    cert_file = Path(__file__).parent / "cert.pem"
    key_file = Path(__file__).parent / "key.pem"

    if use_ssl:
        if not cert_file.exists() or not key_file.exists():
            print("❌ SSL 证书不存在！")
            print(f"   需要: {cert_file}")
            print(f"   需要: {key_file}")
            print()
            print("   生成自签名证书：")
            print("   bash gen_cert.sh")
            print()
            print("   或用 --no-ssl 跳过SSL（仅限本地调试）")
            sys.exit(1)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        proto = "HTTPS"
    else:
        proto = "HTTP"

    print("🦞 PicoClaw PhoneLink Server")
    print(f"   协议: {proto}")
    print(f"   监听: {proto.lower()}://{args.host}:{args.port}")
    print(f"   数据目录: {DATA_DIR}")
    print(f"   转发到 PicoClaw: {'是' if forward_to_picoclaw else '否'}")
    print()
    print("等待手机数据...")
    print("按 Ctrl+C 停止")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        server.server_close()

if __name__ == "__main__":
    main()
