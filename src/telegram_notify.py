"""Envia mensagens pro Telegram via Bot API (gratuita, sem limite prático
pro volume de uso desse projeto)."""
import os
import time

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"

# limite de caracteres por mensagem da própria API do Telegram
TELEGRAM_MESSAGE_LIMIT = 4096


def build_message_batches(messages, separator="\n\n"):
    """Agrupa uma lista de mensagens em lotes pra mandar o mínimo de
    mensagens possível (idealmente 1), em vez de uma mensagem por novidade,
    respeitando o limite de 4096 caracteres do Telegram."""
    batches = []
    current = ""
    for msg in messages:
        candidate = msg if not current else current + separator + msg
        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            if current:
                batches.append(current)
            # mensagem individual maior que o limite (raro): corta ela mesma
            current = msg[:TELEGRAM_MESSAGE_LIMIT]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


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
