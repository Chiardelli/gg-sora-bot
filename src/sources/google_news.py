"""Checa notícias novas sobre o grupo via Google News RSS.

Não precisa de chave de API nem cadastro — é um feed RSS público. Cobre
matérias, participações em programas, prêmios etc. que não aparecem nas
fontes "oficiais" (YouTube/Spotify).

Consulta o feed em vários idiomas/regiões (não só pt-BR), já que a
imprensa coreana/japonesa/chinesa cobre kpop bem mais rápido e
detalhadamente que a brasileira. Notícia que não vem em pt-BR é traduzida
automaticamente (se GEMINI_API_KEY estiver configurada — veja src/ai.py);
sem IA, a notícia ainda é enviada, só que no idioma original.
"""
import calendar
import difflib
import time
from urllib.parse import quote

import feedparser

from ai import filter_relevant_titles, merge_duplicate_news, translate_to_ptbr

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

# locais consultados por grupo. pt-BR primeiro (não precisa tradução); os
# outros cobrem a imprensa "de origem" do kpop, que costuma noticiar tudo
# primeiro e com mais detalhe.
LOCALES = [
    {"code": "pt-BR", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt", "needs_translation": False},
    {"code": "ko", "hl": "ko", "gl": "KR", "ceid": "KR:ko", "needs_translation": True},
    {"code": "ja", "hl": "ja", "gl": "JP", "ceid": "JP:ja", "needs_translation": True},
    {"code": "zh-TW", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant", "needs_translation": True},
]

LOCALE_LANGUAGE_NAMES = {"ko": "coreano", "ja": "japonês", "zh-TW": "chinês"}

# quantas entradas manter por locale (mesmo corte de antes, só que agora
# por idioma em vez de só pt-BR)
ENTRIES_PER_LOCALE = 10

# títulos com essa similaridade ou mais são tratados como a mesma notícia
# republicada por outro portal (evita notificar a mesma matéria várias vezes)
TITLE_SIMILARITY_THRESHOLD = 0.7

# o Google News às vezes reindexa/republica uma matéria antiga com um link
# novo (ex: site atualizou a página), o que faz ela parecer "nova" pro diff
# por link. Entradas mais velhas que isso são ignoradas mesmo que o link
# nunca tenha sido visto antes.
MAX_NEWS_AGE_DAYS = 3


def _fetch_locale(query, locale):
    url = GOOGLE_NEWS_RSS_URL.format(
        query=quote(query), hl=locale["hl"], gl=locale["gl"], ceid=locale["ceid"]
    )
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        print(f"[google_news] erro ao buscar '{query}' ({locale['code']}): {exc}")
        return []

    raw_entries = feed.entries[:ENTRIES_PER_LOCALE] if feed.entries else []
    return [
        {
            "title": e.get("title", ""),
            "link": e.get("link"),
            "published_parsed": e.get("published_parsed"),
            "locale": locale["code"],
            "needs_translation": locale["needs_translation"],
        }
        for e in raw_entries
    ]


def _dedup_by_link(entries):
    kept = []
    seen_links = set()
    for entry in entries:
        link = entry.get("link")
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        kept.append(entry)
    return kept


def _is_recent(entry):
    published = entry.get("published_parsed")
    if not published:
        # sem data no feed: não dá pra saber a idade, então não filtra
        # (melhor arriscar notificar de novo do que perder notícia real)
        return True
    age_seconds = time.time() - calendar.timegm(published)
    return age_seconds <= MAX_NEWS_AGE_DAYS * 86400


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


def _merge_duplicate_entries(group_name, entries, cache=None):
    """Funde entradas que descrevem o mesmo fato/evento (comum quando várias
    entradas — de locales diferentes ou não — cobrem a mesma notícia). Se a
    IA estiver desligada ou falhar, devolve as entradas originais sem
    fundir (nunca perde notícia por causa disso)."""
    if len(entries) < 2:
        return entries

    clusters = merge_duplicate_news(group_name, [e.get("title", "") for e in entries], cache=cache)
    if clusters is None:
        return entries

    merged = []
    for cluster in clusters:
        if not cluster:
            continue
        representative = dict(entries[cluster[0]])
        if len(cluster) > 1:
            representative["merged_count"] = len(cluster)
        merged.append((cluster[0], representative))

    # preserva a ordem original (o índice mais baixo do cluster já reflete
    # a posição do representante na lista antes da fusão)
    merged.sort(key=lambda pair: pair[0])
    return [entry for _, entry in merged]


def _format_message(group_name, entry, cache=None):
    title = entry.get("title", "Notícia nova")
    note = ""

    if entry.get("needs_translation"):
        translated = translate_to_ptbr(title, LOCALE_LANGUAGE_NAMES.get(entry.get("locale")), cache=cache)
        if translated:
            title = translated
            note = " (tradução automática)"
        else:
            language = LOCALE_LANGUAGE_NAMES.get(entry.get("locale"), entry.get("locale"))
            note = f" (em {language}, tradução indisponível)"

    merged_count = entry.get("merged_count")
    if merged_count:
        note += f" (+ {merged_count - 1} outra{'s' if merged_count > 2 else ''} fonte{'s' if merged_count > 2 else ''} sobre o mesmo fato)"

    return f"*{group_name}* na mídia{note}:\n{title}\n{entry['link']}"


def check_google_news(group, state):
    messages = []
    query = group.get("google_news_query")
    if not query:
        return messages

    seen = state.setdefault("google_news", {})
    cache = state.setdefault("ai_cache", {})
    key = group["name"]
    is_first_run = key not in seen
    previously_seen = seen.get(key, [])
    previously_seen_set = set(previously_seen)

    raw_entries = []
    for locale in LOCALES:
        raw_entries.extend(_fetch_locale(query, locale))

    entries = _dedup_by_link(raw_entries)
    entries = [e for e in entries if _is_recent(e)]
    current_links = [e.get("link") for e in entries if e.get("link")]

    if not is_first_run:
        new_entries = [e for e in entries if e.get("link") and e["link"] not in previously_seen_set]
        new_entries = _dedup_by_title(new_entries)

        # filtro opcional por IA: descarta homônimo/ruído que a busca por
        # texto deixa passar (só roda se GEMINI_API_KEY estiver configurada;
        # se a IA falhar ou estiver desligada, mantém todas as notícias)
        if new_entries:
            relevant_idx = filter_relevant_titles(
                group["name"], [e.get("title", "") for e in new_entries], cache=cache
            )
            if relevant_idx is not None:
                new_entries = [e for i, e in enumerate(new_entries) if i in relevant_idx]

        # funde notícias que são o mesmo fato coberto por portais/idiomas
        # diferentes (comum com múltiplos locales) — mantém só a mais
        # completa/confiável de cada grupo, segundo a IA
        if new_entries:
            new_entries = _merge_duplicate_entries(group["name"], new_entries, cache=cache)

        # o feed vem do mais novo pro mais antigo; inverte pra notificar em ordem cronológica
        for entry in reversed(new_entries):
            messages.append(_format_message(group["name"], entry, cache=cache))

    merged = current_links + [l for l in previously_seen if l not in set(current_links)]
    seen[key] = merged[:50]  # limita o tamanho do state

    return messages
