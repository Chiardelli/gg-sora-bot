"""Checa lançamentos novos (álbuns/singles) na API pública do iTunes pra cada grupo.

Não precisa de credencial — é a Search/Lookup API gratuita da Apple. Usada
no lugar da fonte do Spotify (fora do ar desde jan/2026): a ideia é só
saber QUANDO saiu um álbum/single, já que no k-pop o lançamento costuma
sair no Spotify e no iTunes/Apple Music ao mesmo tempo.
"""
import requests

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def find_artist_id(name):
    """Busca o artistId numérico do artista cujo nome mais se aproxima de
    `name`. Usada pelo comando /addgroup do Telegram — pega o primeiro
    resultado que realmente tem álbum/single lançado (descarta homônimos
    sem catálogo), mas o resultado nem sempre é o certo, então vale
    conferir depois."""
    try:
        resp = requests.get(
            ITUNES_SEARCH_URL,
            params={"term": name, "entity": "musicArtist", "limit": 5},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None

        for artist in results:
            artist_id = str(artist["artistId"])
            if _has_releases(artist_id):
                return artist_id

        return str(results[0]["artistId"])
    except Exception as exc:
        print(f"[itunes] erro ao buscar artista pra '{name}': {exc}")
        return None


def _has_releases(artist_id):
    try:
        resp = requests.get(
            ITUNES_LOOKUP_URL,
            params={"id": artist_id, "entity": "album", "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return any(r.get("wrapperType") == "collection" for r in results)
    except Exception:
        return False


def _release_sort_key(album):
    return album.get("releaseDate") or "0000-00-00"


def check_itunes(group, state):
    messages = []
    artist_ids = group.get("itunes_artist_ids") or []
    if not artist_ids:
        return messages

    seen = state.setdefault("itunes", {})

    for artist_id in artist_ids:
        key = str(artist_id)
        try:
            resp = requests.get(
                ITUNES_LOOKUP_URL,
                params={"id": artist_id, "entity": "album", "limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            # o primeiro resultado do lookup é sempre o artista em si, não um álbum
            items = [r for r in data.get("results", []) if r.get("wrapperType") == "collection"]
            if not items:
                continue

            items.sort(key=_release_sort_key)  # mais antigo -> mais novo
            ids = [str(a["collectionId"]) for a in items]

            last_seen_id = seen.get(key)
            if last_seen_id is None:
                seen[key] = ids[-1]
                continue

            if last_seen_id in ids:
                idx = ids.index(last_seen_id)
                new_albums = items[idx + 1 :]
            else:
                new_albums = items

            for album in new_albums:
                name = album.get("collectionName", "")
                url = album.get("collectionViewUrl", "")
                track_count = album.get("trackCount") or 0
                label = "single" if track_count <= 3 else "álbum"
                messages.append(f"*{group['name']}* lançou um {label} (iTunes/Apple Music):\n{name}\n{url}")

            seen[key] = ids[-1]

        except Exception as exc:
            print(f"[itunes] erro pro artista {artist_id}: {exc}")

    return messages
