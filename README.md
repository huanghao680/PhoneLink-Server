# 🦞 PicoClaw PhoneLink Server

手机数据接收服务器，接收来自 PhoneLink Android App 的实时数据。

## 🚀 功能

- **双通道接收**: WebSocket (8766) + HTTP (8765)
- **数据存储**: JSON 文件存储，支持历史查询
- **Docker 部署**: 一键容器化运行
- **PicoClaw 转发**: 可选转发到 PicoClaw workspace

## 📡 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/phone-data` | 接收手机数据 |
| `GET` | `/api/phone-data` | 查询最新数据 |
| `GET` | `/api/phone-data?format=text` | 文本格式查询 |
| `GET` | `/api/history?limit=20` | 历史记录 |
| `GET` | `/` | 服务状态 |

## 🏃 快速运行

### 直接运行
```bash
pip install -r requirements.txt
python3 server.py --port 8765 --forward
```

### Docker
```bash
docker compose up -d
```

## ⚙️ 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | 8765 | HTTP 端口 |
| `--ws-port` | 8766 | WebSocket 端口 |
| `--host` | 0.0.0.0 | 监听地址 |
| `--forward` | false | 转发到 PicoClaw |

## 📄 License

MIT
