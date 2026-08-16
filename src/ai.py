"""Cliente fininho pra Gemini API (tier gratuito do Google AI Studio, sem
cartão de crédito) usado pra deixar a mensagem consolidada mais legível,
filtrar notícia irrelevante, fundir notícia duplicada sobre o mesmo fato,
enriquecer o resumo semanal e gerar recomendações.

Tudo aqui é opcional: se GEMINI_API_KEY não estiver configurada, ou a
chamada falhar por qualquer motivo (rate limit, timeout, resposta
inesperada), as funções devolvem None e quem chamou deve cair de volta pro
comportamento sem IA. O bot nunca deve parar de funcionar por causa da IA.
"""
import hashlib
import json
import os
import re
import time

import requests

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# alias "-latest" da própria Google: sempre aponta pro modelo recomendado do
# momento, sem precisar fixar (e depois atualizar) uma versão datada.
# "lite" porque as tarefas daqui (filtrar, traduzir título, resumir) são
# simples, e na prática se mostrou bem mais estável e rápido 
DEFAULT_MODEL = "gemini-flash-lite-latest"
TIMEOUT = 30

# tarefas daqui costumam rodar várias vezes por execução (1x por grupo, 1x
# por notícia estrangeira etc.), um retry curto evita descartar a resposta
# por causa de instabilidade pontual da API (erro 5xx/timeout)
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.5

URL_RE = re.compile(r"https?://\S+")

# sentinela pra distinguir "não tá no cache" de "tá no cache com valor
# vazio" (ex: filter_relevant_titles devolvendo [] é uma resposta válida)
_CACHE_MISS = object()


def is_enabled():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _cache_key(*parts):
    raw = "||".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _cache_get(cache, key):
    """`cache` é um dict opcional (normalmente `state["ai_cache"]`) passado
    por quem chama, mantém ai.py sem depender de state pra funcionar
    isolado/testável. Sem cache (None), sempre dá miss."""
    if cache is None:
        return _CACHE_MISS
    entry = cache.get(key)
    return entry["value"] if entry else _CACHE_MISS


def _cache_set(cache, key, value):
    if cache is not None and value is not None:
        cache[key] = {"ts": time.time(), "value": value}


def generate_text(prompt, temperature=0.4):
    """Manda um prompt de texto simples pro Gemini e devolve a resposta em
    texto, ou None se a IA não estiver configurada ou a chamada falhar."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }

    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(url, params={"key": api_key}, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", []) or []
            text = "".join(p.get("text", "") for p in parts).strip()
            return text or None
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else None
            if status and status < 500:
                break  # erro do cliente (chave inválida, modelo inexistente...): repetir não resolve
        except Exception as exc:
            last_exc = exc

        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)

    print(f"[ai] erro ao chamar Gemini após {min(attempt, MAX_ATTEMPTS)} tentativa(s): {last_exc}")
    return None


def filter_relevant_titles(group_name, titles, cache=None):
    """Recebe uma lista de títulos de notícia e devolve os índices dos que
    realmente são sobre `group_name` (kpop), filtra homônimo/ruído que a
    busca por texto do Google News deixa passar. Devolve None se a IA
    estiver desligada ou a resposta vier num formato inesperado; nesse caso
    quem chamou deve manter todos os títulos (nunca perder notícia real por
    falha da IA).

    `cache` (opcional, dict) evita rechamar a IA pro mesmo lote de títulos
    duas vezes e protege sobretudo contra reprocessar tudo de novo se uma
    execução falhar depois de notificar mas antes de salvar o state."""
    if not titles or not is_enabled():
        return None

    key = _cache_key("filter_relevant", group_name, tuple(titles))
    cached = _cache_get(cache, key)
    if cached is not _CACHE_MISS:
        return cached

    numbered = "\n".join(f"{i}: {title}" for i, title in enumerate(titles))
    prompt = (
        f'Você filtra notícias pra um bot de alertas sobre o grupo de kpop "{group_name}". '
        "Abaixo tem uma lista de títulos de notícia, numerados a partir de 0. "
        "Devolva APENAS um array JSON com os índices dos títulos que são "
        f'realmente sobre o grupo/idol de kpop "{group_name}" (ignore homônimos '
        "de outras áreas, notícias sobre outro assunto, ou ruído). Se todos "
        "forem relevantes, devolva todos os índices. Responda só com o JSON, "
        f"sem texto extra, sem markdown.\n\n{numbered}"
    )
    text = generate_text(prompt, temperature=0)
    if text is None:
        return None
    try:
        cleaned = text.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        indices = json.loads(cleaned)
        result = [i for i in indices if isinstance(i, int) and 0 <= i < len(titles)]
        _cache_set(cache, key, result)
        return result
    except Exception as exc:
        print(f"[ai] resposta inesperada ao filtrar notícias: {text!r} ({exc})")
        return None


def merge_duplicate_news(group_name, titles, cache=None):
    """Agrupa índices de notícia (títulos numerados a partir de 0) que
    descrevem o MESMO fato/evento, comum quando o mesmo acontecimento é
    coberto por portais diferentes (às vezes em idiomas diferentes). Devolve
    uma lista de clusters (listas de índices); o primeiro índice de cada
    cluster é a notícia escolhida pela IA como mais completa e confiável
    pra representar o grupo. Devolve None se a IA estiver desligada ou a
    resposta vier num formato inesperado; nesse caso quem chamou deve
    manter todas as notícias sem fundir (nunca perder notícia real por
    falha da IA).

    `cache` (opcional, dict) evita rechamar a IA pro mesmo lote duas vezes —
    veja `filter_relevant_titles` pro motivo (proteção contra reprocessar
    tudo se uma execução falhar antes de salvar o state)."""
    if not titles or not is_enabled():
        return None
    if len(titles) == 1:
        return [[0]]

    key = _cache_key("merge_duplicate", group_name, tuple(titles))
    cached = _cache_get(cache, key)
    if cached is not _CACHE_MISS:
        return cached

    numbered = "\n".join(f"{i}: {title}" for i, title in enumerate(titles))
    prompt = (
        f'Você recebe manchetes de notícia, todas já confirmadas como sobre o grupo de kpop "{group_name}", '
        "numeradas a partir de 0. Algumas podem descrever o MESMO fato/evento, só que cobertas por "
        "portais diferentes (às vezes em idiomas diferentes, ou uma sendo tradução de outra). Agrupe os "
        "índices que descrevem o mesmo fato/evento; manchetes sobre fatos diferentes ficam em grupos "
        "separados (com 1 índice só). Dentro de cada grupo com mais de 1 índice, coloque PRIMEIRO o "
        "índice da manchete mais completa e confiável (prefira a que tem mais detalhe e pareça vir de "
        "portal jornalístico mais confiável), esse é o representante do grupo. Devolva APENAS um array "
        "JSON de arrays de índices (todo índice de 0 a "
        f"{len(titles) - 1} deve aparecer exatamente uma vez, em algum grupo). Responda só com o JSON, "
        f"sem texto extra, sem markdown.\n\n{numbered}"
    )
    text = generate_text(prompt, temperature=0)
    if text is None:
        return None
    try:
        cleaned = text.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        clusters = json.loads(cleaned)
        seen_indices = set()
        valid_clusters = []
        for cluster in clusters:
            valid = [i for i in cluster if isinstance(i, int) and 0 <= i < len(titles) and i not in seen_indices]
            if not valid:
                continue
            seen_indices.update(valid)
            valid_clusters.append(valid)
        # alguma manchete ficou de fora da resposta da IA: devolve ela sozinha,
        # pra nunca perder notícia por causa de resposta incompleta
        for i in range(len(titles)):
            if i not in seen_indices:
                valid_clusters.append([i])
        result = valid_clusters or None
        _cache_set(cache, key, result)
        return result
    except Exception as exc:
        print(f"[ai] resposta inesperada ao fundir notícias duplicadas: {text!r} ({exc})")
        return None


def translate_to_ptbr(text, source_language_hint=None, cache=None):
    """Traduz um texto curto (ex: título de notícia) pra português do
    Brasil. Devolve None se a IA estiver desligada ou a chamada falhar —
    quem chamou deve usar o texto original nesse caso, nunca descartar a
    notícia por falha de tradução.

    `cache` (opcional, dict) evita retraduzir o mesmo título duas vezes —
    veja `filter_relevant_titles` pro motivo."""
    if not text or not is_enabled():
        return None

    key = _cache_key("translate", source_language_hint or "", text)
    cached = _cache_get(cache, key)
    if cached is not _CACHE_MISS:
        return cached

    hint = f" O texto original está em {source_language_hint}." if source_language_hint else ""
    prompt = (
        "Traduza o texto abaixo pra português do Brasil, mantendo o "
        f"sentido e o tom de manchete de notícia.{hint} Responda só com a "
        f"tradução, sem aspas, sem explicação, sem texto extra.\n\n{text}"
    )
    result = generate_text(prompt, temperature=0.2)
    _cache_set(cache, key, result)
    return result


def rank_updates(messages):
    """Devolve uma permutação dos índices de `messages` (mensagens de
    novidade já formatadas), da mais pra menos importante, lançamento de
    álbum/MV pesa mais que participação menor em programa, por exemplo.
    Devolve None se a IA estiver desligada, a resposta vier incompleta ou
    num formato inesperado; quem chamou deve manter a ordem original nesse
    caso (nunca vale a pena arriscar perder ou duplicar um item por causa
    de ordenação da IA)."""
    if not messages or len(messages) < 2 or not is_enabled():
        return None

    numbered = "\n---\n".join(f"{i}:\n{m}" for i, m in enumerate(messages))
    prompt = (
        "Você é a Sora, bot de alertas de kpop. Abaixo tem as novidades do "
        "lote atual, numeradas a partir de 0, separadas por '---'. Ordene "
        "os índices do mais importante pro menos importante pra quem "
        "acompanha kpop de perto: lançamento de álbum/single novo e MV "
        "oficial pesam mais que participação menor em programa de TV, "
        "notícia de bastidor, boato não confirmado, ou matéria genérica. "
        "Devolva APENAS um array JSON com TODOS os índices de 0 a "
        f"{len(messages) - 1}, cada um aparecendo exatamente uma vez, na "
        f"ordem de importância. Responda só o JSON, sem texto extra.\n\n{numbered}"
    )
    text = generate_text(prompt, temperature=0)
    if text is None:
        return None
    try:
        cleaned = text.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        order = json.loads(cleaned)
        seen = set()
        result = []
        for i in order:
            if isinstance(i, int) and 0 <= i < len(messages) and i not in seen:
                seen.add(i)
                result.append(i)
        if len(result) != len(messages):
            # resposta incompleta/com índice repetido: não dá pra confiar,
            # melhor manter a ordem original
            return None
        return result
    except Exception as exc:
        print(f"[ai] resposta inesperada ao ordenar novidades: {text!r} ({exc})")
        return None


def summarize_updates(raw_messages):
    """Reescreve a lista de novidades brutas como um boletim único e mais
    natural. Devolve None (e quem chamou deve usar o texto bruto) se a IA
    estiver desligada, falhar, ou se a resposta tiver derrubado algum link —
    nunca vale a pena arriscar perder uma URL de novidade por causa de
    reescrita da IA."""
    if not raw_messages or not is_enabled():
        return None

    joined = "\n\n".join(raw_messages)
    prompt = (
        "Você é a Sora, um bot de alertas de kpop no Telegram. Reescreva as "
        "novidades abaixo como um boletim único, curto e natural em "
        "português do Brasil. Regras importantes: mantenha TODOS os links "
        "exatamente como estão (não altere, não invente, não remova nenhuma "
        "URL); não invente nenhuma informação que não esteja no texto "
        "original; pode usar *negrito* (Markdown do Telegram) pros nomes dos "
        "grupos; respeite a ordem em que as novidades aparecem abaixo (já "
        "vêm da mais pra menos importante, não reordene); não escreva "
        f"título nem introdução genérica, vá direto pras novidades.\n\n{joined}"
    )
    text = generate_text(prompt, temperature=0.4)
    if not text:
        return None

    original_urls = set(URL_RE.findall(joined))
    summarized_urls = set(URL_RE.findall(text))
    if original_urls - summarized_urls:
        print("[ai] resumo descartado: a reescrita perdeu algum link, mantendo texto original")
        return None
    return text
