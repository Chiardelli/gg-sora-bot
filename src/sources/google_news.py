"""Checa notícias novas sobre o grupo via Google News RSS.

Não precisa de chave de API nem cadastro — é um feed RSS público. Cobre
matérias, participações em programas, prêmios etc. que não aparecem nas
fontes "oficiais" (YouTube/Spotify).
"""
import difflib
from urllib.parse import quote

import feedparser

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt"

# títulos com essa similaridade ou mais são tratados como a mesma notícia
# republicada por outro portal (evita notificar a mesma matéria várias vezes)
TITLE_SIMILARITY_THRESHOLD = 0.7


def _dedup_by_title(entries):
    kept = []
    kept_titles = []
    for entry in entries:
        title = (entry.get("title") or "").strip().lower()
        if any(
            difflib.SequenceMatcher(None, title, seen_title).ratio() >= TITLE_SIMILARITY_THRESHOLD
            for seen_title in kept_titles
        ):
            continue
        kept.append(entry)
        kept_titles.append(title)
    return kept


def check_google_news(group, state):
    messages = []
    query = group.get("google_news_query")
    if not query:
        return messages

    seen = state.setdefault("google_news", {})
    key = group["name"]
    is_first_run = key not in seen
    previously_seen = seen.get(key, [])
    previously_seen_set = set(previously_seen)

    url = GOOGLE_NEWS_RSS_URL.format(query=quote(query))
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        print(f"[google_news] erro ao buscar '{query}': {exc}")
        return messages

    entries = feed.entries[:10] if feed.entries else []
    current_links = [e.get("link") for e in entries if e.get("link")]

    if not is_first_run:
        new_entries = [e for e in entries if e.get("link") and e["link"] not in previously_seen_set]
        new_entries = _dedup_by_title(new_entries)
        # o feed vem do mais novo pro mais antigo; inverte pra notificar em ordem cronológica
        for entry in reversed(new_entries):
            title = entry.get("title", "Notícia nova")
            messages.append(f"*{group['name']}* na mídia:\n{title}\n{entry['link']}")

    merged = current_links + [l for l in previously_seen if l not in set(current_links)]
    seen[key] = merged[:50]  # limita o tamanho do state

    return messages
