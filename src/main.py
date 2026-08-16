"""Orquestrador principal: pra cada grupo configurado, roda todas as
checagens de fonte, envia notificações no Telegram pro que for novo, e
salva o estado atualizado.

Uso:
    python src/main.py

Variáveis de ambiente esperadas (veja README.md pra como obter cada uma):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (obrigatórias pra notificar)
    YOUTUBE_API_KEY                        (opcional, pra fonte YouTube)

Fonte iTunes (álbuns/singles) não precisa de credencial nenhuma.

Também processa comandos recebidos por mensagem no Telegram (ex: /addgroup)
antes de checar as fontes — veja telegram_commands.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from state import load_state, save_state
from telegram_notify import send_telegram_message, build_message_batches
from telegram_commands import process_telegram_commands
from sources.youtube import check_youtube
from sources.itunes import check_itunes
from sources.google_news import check_google_news
from sources.melon import check_melon

SOURCE_CHECKS = [check_youtube, check_itunes, check_google_news, check_melon]

# quantas execuções seguidas uma fonte precisa falhar pra um grupo antes de
# avisar no Telegram (em vez de só logar no Actions, que ninguém olha)
FAILURE_ALERT_THRESHOLD = 3


def main():
    state = load_state()
    process_telegram_commands(state)

    groups = load_config()
    if not groups:
        print("Nenhum grupo configurado em config/groups.yaml.")
        save_state(state)
        return

    all_messages = []
    alerts = []
    health = state.setdefault("source_health", {})

    for group in groups:
        name = group.get("name", "Grupo sem nome")
        if group.get("paused"):
            continue
        for check_fn in SOURCE_CHECKS:
            health_key = f"{check_fn.__name__}:{name}"
            entry = health.setdefault(health_key, {"fail_count": 0, "alerted": False})
            try:
                messages = check_fn(group, state)
                all_messages.extend(messages)
                if messages:
                    # contagem pro resumo semanal
                    weekly = state.setdefault("weekly_counts", {}).setdefault(name, {})
                    weekly[check_fn.__name__] = weekly.get(check_fn.__name__, 0) + len(messages)
                entry["fail_count"] = 0
                entry["alerted"] = False
            except Exception as exc:
                print(f"[main] erro checando {check_fn.__name__} pra '{name}': {exc}")
                entry["fail_count"] += 1
                if entry["fail_count"] >= FAILURE_ALERT_THRESHOLD and not entry["alerted"]:
                    fonte = check_fn.__name__.replace("check_", "").replace("_", " ")
                    alerts.append(
                        f'Fonte "{fonte}" falhando pra "{name}" há '
                        f'{entry["fail_count"]} execuções seguidas: {exc}'
                    )
                    entry["alerted"] = True

    print(f"{len(all_messages)} novidade(s) encontrada(s), {len(alerts)} alerta(s).")
    # agrupa tudo em 1 mensagem por lote (em vez de 1 mensagem por novidade)
    # pra não floodar o chat
    for batch in build_message_batches(all_messages):
        send_telegram_message(batch)
    for batch in build_message_batches(alerts):
        send_telegram_message(batch, parse_mode=None)

    save_state(state)


if __name__ == "__main__":
    main()
