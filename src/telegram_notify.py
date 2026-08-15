"""Envia mensagens pro Telegram via Bot API (gratuita, sem limite prático
pro volume de uso desse projeto)."""
import os
import time

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_message(text, parse_mode="Markdown"):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não configurados. Mensagem que seria enviada:")
        print(text)
        return

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"[telegram] erro ao enviar mensagem ({resp.status_code}): {resp.text}")
    except Exception as exc:
        print(f"[telegram] exceção ao enviar mensagem: {exc}")

    # pequena pausa pra não estourar rate limit do Telegram quando várias
    # notificações são enviadas em sequência na mesma execução
    time.sleep(0.5)
