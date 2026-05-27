#!/bin/bash
# 生成自签名证书（运行一次即可）
cd "$(dirname "$0")"
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=frp-rib.com"
echo "✅ 证书已生成: cert.pem + key.pem"
