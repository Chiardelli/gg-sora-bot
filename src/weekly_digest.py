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
from ai import generate_text, is_enabled

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


def _ai_commentary(counts):
    """Comentário curto gerado por IA sobre a semana, baseado só nas
    contagens (nunca em fatos inventados). Devolve None se a IA estiver
    desligada ou falhar, o resumo numérico continua funcionando sozinho."""
    if not is_enabled():
        return None

    totals = {name: sum(by_source.values()) for name, by_source in counts.items()}
    totals = {name: n for name, n in totals.items() if n}
    if not totals:
        return None

    lines = "\n".join(f"{name}: {n} novidade(s)" for name, n in sorted(totals.items(), key=lambda kv: -kv[1]))
    prompt = (
        "Você é a Sora, bot de alertas de kpop no Telegram. Com base SOMENTE "
        "nesses números de novidades da semana por grupo (não invente "
        "nenhum fato, música, evento ou notícia específica que não esteja "
        "aqui), escreva um comentário curto (2 a 3 frases), animado e casual "
        "em português do Brasil, destacando o(s) grupo(s) mais ativo(s) da "
        f"semana.\n\n{lines}"
    )
    return generate_text(prompt, temperature=0.6)


def main():
    state = load_state()
    counts = state.get("weekly_counts", {})
    digest = build_digest(counts)

    if digest:
        commentary = _ai_commentary(counts)
        if commentary:
            digest = f"{digest}\n\n{commentary}"
        send_telegram_message(digest, parse_mode=None)
    else:
        print("Nenhuma novidade na semana — resumo não enviado.")

    state["weekly_counts"] = {}
    save_state(state)


if __name__ == "__main__":
    main()
