---
name: email-sender
description: 邮件发送工具。通过 SMTP 发送邮件，支持 HTML 内容、附件、多收件人。适用于通知、报告推送场景。
version: "1.0"
enabled: true
category: office
author: system
---

# 邮件发送工具

通过 SMTP 协议发送邮件。

## 使用方式

```bash
python skills/email-sender/scripts/main.py \
  --to "user@example.com" \
  --subject "测试邮件" \
  --body "这是一封测试邮件" \
  --smtp-host smtp.gmail.com \
  --smtp-port 587 \
  --smtp-user your@gmail.com \
  --smtp-password your_app_password
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--to` | 收件人邮箱（必填，多个用逗号分隔） |
| `--subject` | 邮件主题（必填） |
| `--body` | 邮件正文（必填） |
| `--html` | HTML 内容（可选，覆盖 body） |
| `--smtp-host` | SMTP 服务器地址（必填） |
| `--smtp-port` | SMTP 端口（默认 587） |
| `--smtp-user` | 发件人邮箱（必填） |
| `--smtp-password` | 发件人密码/应用密码（必填） |
| `--attachment` | 附件文件路径（可选，多个用逗号分隔） |

## 依赖

- Python 3.11+（标准库 smtplib）
