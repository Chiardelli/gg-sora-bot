"""Processa comandos recebidos por mensagem no Telegram (/addgroup,
/removegroup, /pausegroup, /resumegroup, /listgroups, /help) pra gerenciar
grupos na configuração sem precisar editar o repositório.

Usa long polling manual (getUpdates): como o bot já roda de hora em hora via
GitHub Actions, não precisa de um processo dedicado ouvindo mensagens — cada
execução só verifica se chegou algum comando novo desde a última vez.
"""
import os
import re

import requests
import yaml

from config import load_config
from sources.itunes import find_artist_id
from sources.youtube import find_channel_id
from telegram_notify import send_telegram_message

TELEGRAM_API_BASE = "https://api.telegram.org"
GROUPS_BOT_PATH = "config/groups_bot.yaml"
CURATED_GROUPS_PATH = "config/groups.yaml"

ADD_GROUP_RE = re.compile(r"^/addgroup(?:@\w+)?\s+(.+)$", re.IGNORECASE)
REMOVE_GROUP_RE = re.compile(r"^/removegroup(?:@\w+)?\s+(.+)$", re.IGNORECASE)
PAUSE_GROUP_RE = re.compile(r"^/pausegroup(?:@\w+)?\s+(.+)$", re.IGNORECASE)
RESUME_GROUP_RE = re.compile(r"^/resumegroup(?:@\w+)?\s+(.+)$", re.IGNORECASE)
LIST_GROUPS_RE = re.compile(r"^/listgroups(?:@\w+)?\s*$", re.IGNORECASE)
HELP_RE = re.compile(r"^/(help|start)(?:@\w+)?\s*$", re.IGNORECASE)

HELP_TEXT = (
    "Comandos disponíveis:\n"
    "/addgroup Nome Do Grupo - adiciona um grupo (busca YouTube/iTunes automaticamente)\n"
    "/removegroup Nome Do Grupo - remove um grupo adicionado via /addgroup\n"
    "/pausegroup Nome Do Grupo - pausa as notificações de um grupo sem removê-lo\n"
    "/resumegroup Nome Do Grupo - reativa as notificações de um grupo pausado\n"
    "/listgroups - lista os grupos configurados\n"
    "/help - mostra essa mensagem"
)


def _get_updates(offset):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return []
    url = f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as exc:
        print(f"[telegram_commands] erro ao buscar updates: {exc}")
        return []


def _load_bot_groups():
    if not os.path.exists(GROUPS_BOT_PATH):
        return []
    with open(GROUPS_BOT_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("groups", []) or []


def _save_bot_groups(groups):
    with open(GROUPS_BOT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump({"groups": groups}, f, allow_unicode=True, sort_keys=False)


def _add_group(name):
    if any(g.get("name", "").lower() == name.lower() for g in load_config()):
        return f'"{name}" já está configurado.'

    youtube_channel_id = find_channel_id(name)
    itunes_artist_id = find_artist_id(name)

    groups = _load_bot_groups()
    groups.append(
        {
            "name": name,
            "youtube_channel_ids": [youtube_channel_id] if youtube_channel_id else [],
            "itunes_artist_ids": [itunes_artist_id] if itunes_artist_id else [],
            "google_news_query": f"{name} kpop",
        }
    )
    _save_bot_groups(groups)

    return (
        f'"{name}" adicionado.\n'
        f"YouTube: {'encontrado' if youtube_channel_id else 'não encontrado, confira manualmente'}\n"
        f"iTunes: {'encontrado' if itunes_artist_id else 'não encontrado, confira manualmente'}\n"
        f"Revise em {GROUPS_BOT_PATH} se algo ficou errado (ex: nome comum "
        f"pode ter encontrado o canal/artista errado)."
    )


def _remove_group(name):
    groups = _load_bot_groups()
    matched = [g for g in groups if g.get("name", "").lower() == name.lower()]
    if not matched:
        if any(g.get("name", "").lower() == name.lower() for g in load_config()):
            return (
                f'"{name}" está em {CURATED_GROUPS_PATH} (adicionado manualmente), '
                f"não em {GROUPS_BOT_PATH} — remova editando o arquivo direto."
            )
        return f'"{name}" não está configurado.'

    remaining = [g for g in groups if g.get("name", "").lower() != name.lower()]
    _save_bot_groups(remaining)
    return f'"{name}" removido.'


def _set_paused(name, paused):
    groups = _load_bot_groups()
    matched = next((g for g in groups if g.get("name", "").lower() == name.lower()), None)

    if matched is None:
        if any(g.get("name", "").lower() == name.lower() for g in load_config()):
            return (
                f'"{name}" está em {CURATED_GROUPS_PATH} (adicionado manualmente) — '
                f'edite o campo "paused" direto no arquivo pra pausar/reativar.'
            )
        return f'"{name}" não está configurado.'

    if matched.get("paused", False) == paused:
        estado = "já estava pausado" if paused else "já estava ativo"
        return f'"{name}" {estado}.'

    matched["paused"] = paused
    _save_bot_groups(groups)
    return f'"{name}" {"pausado" if paused else "reativado"}.'


def _list_groups():
    groups = load_config()
    if not groups:
        return "Nenhum grupo configurado ainda."

    bot_names = {g.get("name", "").lower() for g in _load_bot_groups()}
    lines = []
    for group in groups:
        name = group.get("name", "sem nome")
        origem = "via /addgroup" if name.lower() in bot_names else "manual"
        status = ", pausado" if group.get("paused") else ""
        lines.append(f"- {name} ({origem}{status})")

    return f"{len(groups)} grupo(s) configurado(s):\n" + "\n".join(lines)


COMMANDS = [
    (HELP_RE, lambda m: HELP_TEXT),
    (LIST_GROUPS_RE, lambda m: _list_groups()),
    (ADD_GROUP_RE, lambda m: _add_group(m.group(1).strip())),
    (REMOVE_GROUP_RE, lambda m: _remove_group(m.group(1).strip())),
    (PAUSE_GROUP_RE, lambda m: _set_paused(m.group(1).strip(), True)),
    (RESUME_GROUP_RE, lambda m: _set_paused(m.group(1).strip(), False)),
]


def process_telegram_commands(state):
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        return

    telegram_state = state.setdefault("telegram", {})
    last_update_id = telegram_state.get("last_update_id")
    offset = last_update_id + 1 if last_update_id is not None else None

    for update in _get_updates(offset):
        telegram_state["last_update_id"] = update["update_id"]
        message = update.get("message") or {}
        if str(message.get("chat", {}).get("id")) != str(chat_id):
            continue  # ignora mensagens de qualquer chat que não seja o dono

        text = (message.get("text") or "").strip()

        for pattern, handler in COMMANDS:
            match = pattern.match(text)
            if not match:
                continue
            try:
                reply = handler(match)
            except Exception as exc:
                reply = f"Erro ao processar o comando: {exc}"
                print(f"[telegram_commands] {reply}")
            send_telegram_message(reply, parse_mode=None)
            break
