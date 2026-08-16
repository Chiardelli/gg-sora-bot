"""Processa um único update do Telegram recebido via repository_dispatch,
disparado pelo Cloudflare Worker (veja cloudflare-worker/) assim que o
Telegram entrega a mensagem — dá resposta em segundos, sem esperar o
próximo cron (que só processa comandos como fallback).

Reaproveita _dispatch_command de telegram_commands.py: mesma lógica de
sempre, só que acionada por push em vez de polling.

Uso (rodado pelo workflow .github/workflows/telegram-webhook.yml):
    TELEGRAM_UPDATE_JSON='{...}' python src/process_webhook_update.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram_commands import _dispatch_command  # noqa: E402
from telegram_notify import send_telegram_message  # noqa: E402


def main():
    raw = os.environ.get("TELEGRAM_UPDATE_JSON", "").strip()
    if not raw:
        print("[process_webhook_update] TELEGRAM_UPDATE_JSON vazio, nada a fazer.")
        return

    update = json.loads(raw)
    message = update.get("message") or {}

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id or str(message.get("chat", {}).get("id")) != str(chat_id):
        print("[process_webhook_update] update de outro chat, ignorado.")
        return

    text = (message.get("text") or "").strip()
    reply = _dispatch_command(text)
    if reply is not None:
        send_telegram_message(reply, parse_mode=None)
    else:
        print(f"[process_webhook_update] texto não reconhecido como comando: {text!r}")


if __name__ == "__main__":
    main()
