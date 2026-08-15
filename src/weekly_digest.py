"""Manda um resumo semanal consolidado no Telegram, juntando a contagem de
novidades por grupo/fonte acumulada desde o último resumo.

O `src/main.py` incrementa `state["weekly_counts"]` a cada notificação
enviada em tempo real; esse script só lê essa contagem, monta um resumo e
zera pro próximo período — pensado pra rodar 1x/semana num workflow
separado do GitHub Actions (veja .github/workflows/weekly-digest.yml),
não no cron de hora em hora do main.py.

Uso:
    python src/weekly_digest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from state import load_state, save_state
from telegram_notify import send_telegram_message

FRIENDLY_SOURCE_NAMES = {
    "check_youtube": "YouTube",
    "check_itunes": "iTunes",
    "check_google_news": "Google News",
    "check_melon": "Melon",
}


def build_digest(counts):
    lines = []
    total = 0
    for group_name in sorted(counts):
        by_source = counts[group_name]
        group_total = sum(by_source.values())
        if not group_total:
            continue
        total += group_total
        parts = [
            f"{FRIENDLY_SOURCE_NAMES.get(source, source)}: {n}"
            for source, n in sorted(by_source.items())
            if n
        ]
        lines.append(f"- {group_name} ({group_total}): " + ", ".join(parts))

    if not lines:
        return None
    return f"Resumo da semana ({total} novidade(s) no total):\n" + "\n".join(lines)


def main():
    state = load_state()
    digest = build_digest(state.get("weekly_counts", {}))

    if digest:
        send_telegram_message(digest, parse_mode=None)
    else:
        print("Nenhuma novidade na semana — resumo não enviado.")

    state["weekly_counts"] = {}
    save_state(state)


if __name__ == "__main__":
    main()
