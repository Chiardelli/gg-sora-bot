"""Carrega a lista de grupos monitorados a partir de config/groups.yaml e,
se existir, config/groups_bot.yaml (grupos adicionados via comando no
Telegram)."""
import os

import yaml

BOT_GROUPS_PATH = "config/groups_bot.yaml"


def load_config(path="config/groups.yaml", bot_path=BOT_GROUPS_PATH):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    groups = list(data.get("groups", []) or [])

    if os.path.exists(bot_path):
        with open(bot_path, "r", encoding="utf-8") as f:
            bot_data = yaml.safe_load(f) or {}
        groups.extend(bot_data.get("groups", []) or [])

    return groups
