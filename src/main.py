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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from state import load_state, save_state
from telegram_notify import send_telegram_message, build_message_batches
from ai import summarize_updates, rank_updates
from telegram_commands import process_telegram_commands
from sources.youtube import check_youtube
from sources.itunes import check_itunes
from sources.google_news import check_google_news
from sources.melon import check_melon

SOURCE_CHECKS = [check_youtube, check_itunes, check_google_news, check_melon]

# quantas execuções seguidas uma fonte precisa falhar pra um grupo antes de
# avisar no Telegram (em vez de só logar no Actions, que ninguém olha)
FAILURE_ALERT_THRESHOLD = 3

# histórico de novidades notificadas, guardado em state["activity_log"] pra
# alimentar o /ask (pergunta livre sobre os grupos). Podado a cada execução
# pelos dois limites abaixo, pra não deixar state/seen.json crescer sem
# controle.
ACTIVITY_LOG_MAX_AGE_DAYS = 14
ACTIVITY_LOG_MAX_ENTRIES = 500

# cache de respostas de IA (state["ai_cache"]) evita rechamar a IA pro
# mesmo lote/título duas vezes; principalmente uma proteção contra
# reprocessar tudo de novo se uma execução falhar depois de notificar mas
# antes de salvar o state. Janela curta porque, em uso normal, um link já
# processado nunca reaparece como "novo" de novo (dedup por link no
# state), então cache antigo não tem valor, só atrapalha o tamanho do
# state/seen.json.
AI_CACHE_MAX_AGE_DAYS = 3
AI_CACHE_MAX_ENTRIES = 300


def _log_activity(state, group_name, messages):
    if not messages:
        return
    log = state.setdefault("activity_log", [])
    now = time.time()
    for message in messages:
        log.append({"ts": now, "group": group_name, "text": message})


def _prune_activity_log(state):
    log = state.get("activity_log")
    if not log:
        return
    cutoff = time.time() - ACTIVITY_LOG_MAX_AGE_DAYS * 86400
    log = [entry for entry in log if entry.get("ts", 0) >= cutoff]
    state["activity_log"] = log[-ACTIVITY_LOG_MAX_ENTRIES:]


def _prune_ai_cache(state):
    cache = state.get("ai_cache")
    if not cache:
        return
    cutoff = time.time() - AI_CACHE_MAX_AGE_DAYS * 86400
    fresh = {k: v for k, v in cache.items() if v.get("ts", 0) >= cutoff}
    if len(fresh) > AI_CACHE_MAX_ENTRIES:
        newest_first = sorted(fresh.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)
        fresh = dict(newest_first[:AI_CACHE_MAX_ENTRIES])
    state["ai_cache"] = fresh


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
                    # histórico pro /ask
                    _log_activity(state, name, messages)
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
    # pra não floodar o chat; se a IA estiver configurada, ordena do mais
    # pro menos importante e tenta reescrever como um boletim único mais
    # natural (com fallback pro texto bruto/ordem original se a IA falhar,
    # devolver ordem incompleta, ou derrubar algum link)
    if all_messages:
        order = rank_updates(all_messages)
        if order:
            all_messages = [all_messages[i] for i in order]

    outgoing = all_messages
    if all_messages:
        summary = summarize_updates(all_messages)
        if summary:
            outgoing = [summary]
    for batch in build_message_batches(outgoing):
        send_telegram_message(batch)
    for batch in build_message_batches(alerts):
        send_telegram_message(batch, parse_mode=None)

    _prune_activity_log(state)
    _prune_ai_cache(state)
    save_state(state)


if __name__ == "__main__":
    main()
