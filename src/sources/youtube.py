"""Checa uploads novos nos canais do YouTube configurados pra cada grupo.

Usa a YouTube Data API v3 (gratuita, dentro da cota diária de 10.000 unidades).
Em vez de usar search.list (custa 100 unidades por chamada), resolve a
playlist de uploads do canal e lê playlistItems.list, que custa só 1 unidade
por chamada — assim dá pra checar dezenas de canais por hora sem estourar cota.
"""
import os
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_youtube_client: Any = None


def _get_client():
    global _youtube_client
    if _youtube_client is not None:
        return _youtube_client
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return None
    _youtube_client = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    return _youtube_client


def find_channel_id(name):
    """Busca o channelId do canal cujo nome mais se aproxima de `name`.
    Usada pelo comando /addgroup do Telegram — custa 100 unidades de cota
    (search.list) + 1 unidade por candidato (channels.list), mas só roda
    quando o comando é usado. O resultado nem sempre é o certo, por isso
    vale conferir depois."""
    youtube = _get_client()
    if youtube is None:
        return None
    try:
        resp = youtube.search().list(part="snippet", q=name, type="channel", maxResults=5).execute()
        items = resp.get("items", [])
        if not items:
            return None

        # canais "- Topic" são gerados automaticamente pelo YouTube pra
        # organizar faixas de música e não são o canal oficial de uploads
        candidates = [
            item["snippet"]["channelId"]
            for item in items
            if not item["snippet"]["channelTitle"].lower().endswith(" - topic")
        ] or [items[0]["snippet"]["channelId"]]

        if len(candidates) == 1:
            return candidates[0]

        # entre os candidatos restantes, o canal oficial costuma ser o
        # com mais inscritos (fan channels e canais de member costumam
        # ter bem menos)
        stats_resp = youtube.channels().list(part="statistics", id=",".join(candidates)).execute()
        by_subs = sorted(
            stats_resp.get("items", []),
            key=lambda c: int(c.get("statistics", {}).get("subscriberCount", 0)),
            reverse=True,
        )
        return by_subs[0]["id"] if by_subs else candidates[0]
    except Exception as exc:
        print(f"[youtube] erro ao buscar canal pra '{name}': {exc}")
        return None


def check_youtube(group, state):
    messages = []
    channel_ids = group.get("youtube_channel_ids") or []
    if not channel_ids:
        return messages

    youtube = _get_client()
    if youtube is None:
        return messages

    seen = state.setdefault("youtube", {})

    for channel_id in channel_ids:
        try:
            ch_resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
            items = ch_resp.get("items", [])
            if not items:
                print(f"[youtube] canal não encontrado: {channel_id}")
                continue
            uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

            pl_resp = (
                youtube.playlistItems()
                .list(part="snippet", playlistId=uploads_playlist_id, maxResults=5)
                .execute()
            )
            videos = pl_resp.get("items", [])
            if not videos:
                continue

            # a API retorna do mais novo pro mais antigo; inverte pra ordem cronológica
            videos = list(reversed(videos))
            ids = [v["snippet"]["resourceId"]["videoId"] for v in videos]

            last_seen_id = seen.get(channel_id)
            if last_seen_id is None:
                # primeira execução pra esse canal: só define a baseline,
                # sem notificar o histórico inteiro de uma vez
                seen[channel_id] = ids[-1]
                continue

            if last_seen_id in ids:
                idx = ids.index(last_seen_id)
                new_videos = videos[idx + 1 :]
            else:
                # último vídeo visto saiu da janela dos 5 mais recentes
                new_videos = videos

            for video in new_videos:
                title = video["snippet"]["title"]
                video_id = video["snippet"]["resourceId"]["videoId"]
                url = f"https://www.youtube.com/watch?v={video_id}"
                messages.append(f"*{group['name']}* postou no YouTube:\n{title}\n{url}")

            seen[channel_id] = ids[-1]

        except HttpError as exc:
            print(f"[youtube] erro de API pro canal {channel_id}: {exc}")
        except Exception as exc:
            print(f"[youtube] erro inesperado pro canal {channel_id}: {exc}")

    return messages
