#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邮件发送工具 — 通过 SMTP 发送邮件。"""
import argparse
import json
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="邮件发送工具")
    parser.add_argument("--to", required=True, help="收件人（逗号分隔）")
    parser.add_argument("--subject", required=True, help="邮件主题")
    parser.add_argument("--body", required=True, help="邮件正文")
    parser.add_argument("--html", default="", help="HTML 内容")
    parser.add_argument("--smtp-host", required=True, help="SMTP 服务器")
    parser.add_argument("--smtp-port", type=int, default=587, help="SMTP 端口")
    parser.add_argument("--smtp-user", required=True, help="发件人邮箱")
    parser.add_argument("--smtp-password", required=True, help="发件人密码")
    parser.add_argument("--attachment", default="", help="附件路径（逗号分隔）")
    args = parser.parse_args()

    msg = MIMEMultipart()
    msg["From"] = args.smtp_user
    msg["To"] = args.to
    msg["Subject"] = args.subject

    if args.html:
        msg.attach(MIMEText(args.html, "html", "utf-8"))
    else:
        msg.attach(MIMEText(args.body, "plain", "utf-8"))

    # 附件
    if args.attachment:
        for fpath in args.attachment.split(","):
            fpath = fpath.strip()
            if not fpath or not Path(fpath).exists():
                continue
            part = MIMEBase("application", "octet-stream")
            part.set_payload(Path(fpath).read_bytes())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{Path(fpath).name}"')
            msg.attach(part)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(args.smtp_host, args.smtp_port) as server:
            server.starttls(context=context)
            server.login(args.smtp_user, args.smtp_password)
            recipients = [r.strip() for r in args.to.split(",")]
            server.sendmail(args.smtp_user, recipients, msg.as_string())
        print(json.dumps({"success": True, "recipients": len(recipients), "subject": args.subject}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
