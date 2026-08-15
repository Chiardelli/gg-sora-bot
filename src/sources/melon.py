"""Checa se alguma música do grupo entrou no Top 100 do Melon (o chart mais
influente da indústria de kpop na Coreia).

O Melon não tem API pública — essa fonte faz scraping da página do chart, o
que é inerentemente mais frágil que as outras (todas API oficial ou RSS):
se a Melon mudar o HTML da página, essa fonte silenciosamente para de
funcionar (só loga erro no Actions). Depois de algumas execuções falhando
seguidas pro mesmo grupo, o alerta de fonte quebrada (veja main.py) avisa
no Telegram.
"""
import re

import requests

MELON_CHART_URL = "https://www.melon.com/chart/index.htm"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; gg-heartbeat/1.0)"}

# cada linha do chart tem um bloco de HTML iniciado por esse marcador
ROW_RE = re.compile(r'data-song-no="(\d+)"(.*?)(?=data-song-no="|\Z)', re.S)
RANK_RE = re.compile(r'<span class="rank ">(\d+)</span>')
ARTIST_ID_RE = re.compile(r'/artist/detail\.htm\?artistId=(\d+)')
TITLE_RE = re.compile(r'title="([^"]+) 재생"')


def _parse_chart(html):
    entries = []
    seen_song_ids = set()
    for song_id, block in ROW_RE.findall(html):
        if song_id in seen_song_ids:
            continue  # a página repete o mesmo data-song-no num bloco auxiliar vazio
        rank = RANK_RE.search(block)
        artist_id = ARTIST_ID_RE.search(block)
        title = TITLE_RE.search(block)
        if not (rank and artist_id and title):
            continue
        seen_song_ids.add(song_id)
        entries.append(
            {
                "song_id": song_id,
                "rank": int(rank.group(1)),
                "artist_id": artist_id.group(1),
                "title": title.group(1),
            }
        )
    return entries


def check_melon(group, state):
    messages = []
    artist_id = group.get("melon_artist_id")
    if not artist_id:
        return messages

    key = str(artist_id)
    seen = state.setdefault("melon", {})

    try:
        resp = requests.get(MELON_CHART_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        entries = _parse_chart(resp.text)
    except Exception as exc:
        print(f"[melon] erro pro artista {artist_id}: {exc}")
        return messages

    artist_entries = [e for e in entries if e["artist_id"] == key]
    current_song_ids = {e["song_id"] for e in artist_entries}

    is_first_run = key not in seen
    if not is_first_run:
        previous_song_ids = set(seen.get(key, []))
        new_song_ids = current_song_ids - previous_song_ids
        for entry in artist_entries:
            if entry["song_id"] in new_song_ids:
                messages.append(
                    f"*{group['name']}* entrou no Top 100 do Melon:\n"
                    f"{entry['title']} (posição {entry['rank']})"
                )

    seen[key] = sorted(current_song_ids)
    return messages
