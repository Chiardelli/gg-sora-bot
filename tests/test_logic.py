"""Teste manual (não faz parte do projeto entregue) só pra validar a lógica
de diff das fontes com dados falsos, sem depender de rede/credenciais reais.
"""
import sys
import os
import json
import types
from unittest.mock import patch

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from state import load_state, save_state 


def test_state_roundtrip(tmp_path):
    path = str(tmp_path / "seen.json")
    save_state({"a": {"b": "c"}}, path=path)
    loaded = load_state(path=path)
    assert loaded == {"a": {"b": "c"}}
    print("state roundtrip OK")


def test_youtube_no_credentials_returns_empty():
    from sources.youtube import check_youtube
    os.environ.pop("YOUTUBE_API_KEY", None)
    result = check_youtube({"name": "X", "youtube_channel_ids": ["UC123"]}, {})
    assert result == []
    print("youtube sem credencial: retorna [] OK")


def test_itunes_first_run_no_notification_then_detects_new():
    from sources import itunes

    group = {"name": "Grupo Teste", "itunes_artist_ids": ["123"]}
    state = {}

    def make_response(albums):
        class FakeResp:
            def raise_for_status(self):
                pass
            def json(self):
                return {"results": [{"wrapperType": "artist"}] + albums}
        return FakeResp()

    albums_v1 = [
        {"wrapperType": "collection", "collectionId": 1, "collectionName": "Album 1",
         "collectionViewUrl": "http://example.com/1", "releaseDate": "2025-01-01T00:00:00Z", "trackCount": 8},
    ]
    albums_v2 = albums_v1 + [
        {"wrapperType": "collection", "collectionId": 2, "collectionName": "Single 2",
         "collectionViewUrl": "http://example.com/2", "releaseDate": "2025-02-01T00:00:00Z", "trackCount": 2},
    ]

    with patch.object(itunes.requests, "get", return_value=make_response(albums_v1)):
        msgs_first = itunes.check_itunes(group, state)
    assert msgs_first == [], f"esperado nenhuma notificação no primeiro run, veio {msgs_first}"

    with patch.object(itunes.requests, "get", return_value=make_response(albums_v2)):
        msgs_second = itunes.check_itunes(group, state)
    assert len(msgs_second) == 1 and "Single 2" in msgs_second[0], f"esperado 1 notificação sobre Single 2, veio {msgs_second}"
    print("itunes diff logic OK:", msgs_second)


def _fake_feed(links):
    entries = [types.SimpleNamespace(get=(lambda d: (lambda k, default=None: d.get(k, default)))({"link": l, "title": f"Notícia {l}"})) for l in links]
    # feedparser entries behave like dicts; simulate with plain dicts instead
    return types.SimpleNamespace(entries=[{"link": l, "title": f"Notícia {l}"} for l in links])


def test_google_news_first_run_no_notification_then_detects_new():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {}

    with patch.object(google_news.feedparser, "parse", return_value=_fake_feed(["u1", "u2", "u3"])):
        msgs_first = google_news.check_google_news(group, state)
    assert msgs_first == [], f"esperado nenhuma notificação no primeiro run, veio {msgs_first}"

    # segunda execução: 1 link novo (u4) além dos 3 antigos
    with patch.object(google_news.feedparser, "parse", return_value=_fake_feed(["u4", "u1", "u2", "u3"])):
        msgs_second = google_news.check_google_news(group, state)
    assert len(msgs_second) == 1 and "u4" in msgs_second[0], f"esperado 1 notificação sobre u4, veio {msgs_second}"
    print("google_news diff logic OK:", msgs_second)


def test_google_news_ignores_old_reindexed_entry():
    from sources import google_news
    import time

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": ["u1"]}}

    now = time.gmtime()
    old = time.gmtime(time.time() - (google_news.MAX_NEWS_AGE_DAYS + 5) * 86400)

    entries = [
        {"link": "u_novo", "title": "Notícia de verdade recém-saída", "published_parsed": now},
        {"link": "u_velho", "title": "Matéria antiga reindexada com link novo", "published_parsed": old},
    ]
    feed = types.SimpleNamespace(entries=entries)

    with patch.object(google_news.feedparser, "parse", return_value=feed):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 1 and "u_novo" in msgs[0], f"esperada só a notícia recente, veio {msgs}"
    assert "u_velho" not in state["google_news"]["Grupo Teste"], "notícia velha não deveria nem entrar no state"
    print("google_news ignora reindexação de notícia velha OK:", msgs)


def test_google_news_queries_multiple_locales_and_translates_foreign_entries():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": []}}

    def fake_parse(url):
        if "hl=ko" in url:
            return types.SimpleNamespace(entries=[{"link": "u_kr", "title": "코리안 뉴스 제목"}])
        if "hl=ja" in url or "hl=zh-TW" in url:
            return types.SimpleNamespace(entries=[])
        return types.SimpleNamespace(entries=[{"link": "u_br", "title": "Notícia em português"}])

    with patch.object(google_news.feedparser, "parse", side_effect=fake_parse), \
         patch.object(google_news, "translate_to_ptbr", return_value="Título traduzido pro português"):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 2, f"esperada 1 notícia de cada locale (pt-BR + ko), veio {msgs}"
    br_msg = next(m for m in msgs if "u_br" in m)
    kr_msg = next(m for m in msgs if "u_kr" in m)
    assert "Notícia em português" in br_msg and "tradução" not in br_msg
    assert "Título traduzido pro português" in kr_msg and "tradução automática" in kr_msg
    print("google_news consulta múltiplos locales e traduz notícia estrangeira OK:", msgs)


def test_google_news_falls_back_to_original_title_when_translation_unavailable():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": []}}

    def fake_parse(url):
        if "hl=ko" in url:
            return types.SimpleNamespace(entries=[{"link": "u_kr", "title": "코리안 뉴스 제목"}])
        return types.SimpleNamespace(entries=[])

    with patch.object(google_news.feedparser, "parse", side_effect=fake_parse), \
         patch.object(google_news, "translate_to_ptbr", return_value=None):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 1 and "코리안 뉴스 제목" in msgs[0] and "tradução indisponível" in msgs[0], (
        f"esperado título original com aviso de tradução indisponível, veio {msgs}"
    )
    print("google_news volta pro título original quando tradução falha OK:", msgs)


def test_google_news_dedups_same_link_returned_by_multiple_locales():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": []}}

    same_entry = types.SimpleNamespace(entries=[{"link": "u_dup", "title": "Mesma notícia"}])

    with patch.object(google_news.feedparser, "parse", return_value=same_entry):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 1, f"esperada 1 notificação só (mesmo link vindo de 4 locales), veio {msgs}"
    assert state["google_news"]["Grupo Teste"] == ["u_dup"], "state não deveria guardar o link duplicado 4x"
    print("google_news dedup de link repetido entre locales OK:", msgs)


def test_ai_translate_to_ptbr_uses_cache_on_second_call():
    import ai

    cache = {}
    with patch.object(ai, "is_enabled", return_value=True), \
         patch.object(ai, "generate_text", return_value="Título traduzido") as mock_gen:
        first = ai.translate_to_ptbr("제목", "coreano", cache=cache)
        second = ai.translate_to_ptbr("제목", "coreano", cache=cache)

    assert first == second == "Título traduzido"
    assert mock_gen.call_count == 1, f"esperada só 1 chamada à IA (2ª deveria vir do cache), veio {mock_gen.call_count}"
    print("ai.translate_to_ptbr usa cache na 2ª chamada OK")


def test_ai_translate_to_ptbr_cache_miss_on_different_text():
    import ai

    cache = {}
    with patch.object(ai, "is_enabled", return_value=True), \
         patch.object(ai, "generate_text", return_value="traduzido") as mock_gen:
        ai.translate_to_ptbr("texto 1", "coreano", cache=cache)
        ai.translate_to_ptbr("texto 2", "coreano", cache=cache)

    assert mock_gen.call_count == 2, f"textos diferentes não deveriam compartilhar cache, veio {mock_gen.call_count}"
    print("ai.translate_to_ptbr cache não confunde textos diferentes OK")


def test_ai_filter_relevant_titles_uses_cache_on_second_call():
    import ai

    cache = {}
    titles = ["notícia A", "notícia B"]
    with patch.object(ai, "is_enabled", return_value=True), \
         patch.object(ai, "generate_text", return_value="[0]") as mock_gen:
        first = ai.filter_relevant_titles("Grupo Teste", titles, cache=cache)
        second = ai.filter_relevant_titles("Grupo Teste", titles, cache=cache)

    assert first == second == [0]
    assert mock_gen.call_count == 1
    print("ai.filter_relevant_titles usa cache na 2ª chamada OK")


def test_google_news_rerun_after_failed_save_uses_cache_instead_of_recalling_ai():
    """Simula uma execução que notifica mas falha antes de salvar o state
    (ex: git push falhou no Actions) a próxima execução vê os MESMOS
    links como 'novos' de novo. O cache evita rechamar a IA pra
    tradução/filtro/fusão do mesmo lote duas vezes."""
    from sources import google_news

    group = {"name": "TWICE", "google_news_query": "TWICE kpop"}
    state = {"google_news": {"TWICE": []}}  # já rodou antes, mas sem essas notícias no baseline

    entries = [
        {"link": "u_kr", "title": "코리안 뉴스 제목"},
        {"link": "u_kr2", "title": "다른 코리안 뉴스"},
    ]

    def fake_parse(url):
        if "hl=ko" in url:
            return types.SimpleNamespace(entries=entries)
        return types.SimpleNamespace(entries=[])

    ai_generate_calls = []

    def fake_translate(text, hint, cache=None):
        key = ("translate", hint, text)
        if cache is not None and key in cache:
            return cache[key]
        ai_generate_calls.append(text)
        result = f"traduzido: {text}"
        if cache is not None:
            cache[key] = result
        return result

    # dict de cache compartilhado entre as duas "execuções", como se fosse o
    # ai_cache persistido em state/seen.json e recarregado do disco
    cache = {}
    with patch.object(google_news.feedparser, "parse", side_effect=fake_parse), \
         patch.object(google_news, "translate_to_ptbr", side_effect=fake_translate):
        # 1ª execução: não salva state["google_news"] de volta (simula falha antes do git push)
        google_news.check_google_news(group, {"google_news": {"TWICE": []}, "ai_cache": cache})
        # 2ª execução (rerun): mesmo baseline de antes, já que a 1ª não foi salva
        google_news.check_google_news(group, {"google_news": {"TWICE": []}, "ai_cache": cache})

    assert len(ai_generate_calls) == 2, f"esperadas só 2 chamadas de tradução no total (1 por notícia, cacheadas na repetição), veio {len(ai_generate_calls)}"
    print("google_news reaproveita cache entre execuções (rerun após falha) OK")


def test_prune_ai_cache_removes_old_entries_and_caps_size():
    import main as main_module
    import time

    old_ts = time.time() - (main_module.AI_CACHE_MAX_AGE_DAYS + 1) * 86400
    recent_ts = time.time()
    state = {
        "ai_cache": {
            "k_old": {"ts": old_ts, "value": "velho"},
            "k_new": {"ts": recent_ts, "value": "novo"},
        }
    }

    main_module._prune_ai_cache(state)

    assert list(state["ai_cache"].keys()) == ["k_new"]
    print("main._prune_ai_cache remove entradas velhas OK")


def test_google_news_ai_merges_duplicate_coverage_of_same_event():
    from sources import google_news

    group = {"name": "TWICE", "google_news_query": "TWICE kpop"}
    state = {"google_news": {"TWICE": []}}

    entries = [
        {"link": "u_kr", "title": "Chaeyoung deixa a JYP (fonte coreana)"},
        {"link": "u_br", "title": "Chaeyoung, do TWICE, anuncia saída da JYP Entertainment após 14 anos - matéria completa com entrevista"},
        {"link": "u_outro", "title": "TWICE confirma novo single pra setembro"},
    ]
    feed = types.SimpleNamespace(entries=entries)

    # a IA escolhe u_br (índice 1) como representante por ser mais completa
    with patch.object(google_news.feedparser, "parse", return_value=feed), \
         patch.object(google_news, "merge_duplicate_news", return_value=[[1, 0], [2]]):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 2, f"esperadas 2 mensagens (1 fundida + 1 separada), veio {msgs}"
    fundida = next(m for m in msgs if "u_br" in m)
    separada = next(m for m in msgs if "u_outro" in m)
    assert "u_kr" not in "".join(msgs), "link descartado pela fusão não deveria aparecer em nenhuma mensagem"
    assert "outra fonte" in fundida, f"esperada nota de fusão na mensagem escolhida, veio {fundida}"
    assert "outra fonte" not in separada
    print("google_news funde notícias duplicadas via IA OK:", msgs)


def test_google_news_merge_disabled_keeps_all_entries_separate():
    from sources import google_news

    group = {"name": "TWICE", "google_news_query": "TWICE kpop"}
    state = {"google_news": {"TWICE": []}}

    entries = [
        {"link": "u1", "title": "TWICE lança álbum novo"},
        {"link": "u2", "title": "TWICE se apresenta em festival de verão"},
    ]
    feed = types.SimpleNamespace(entries=entries)

    # merge_duplicate_news real devolve None sem GEMINI_API_KEY configurada
    with patch.object(google_news.feedparser, "parse", return_value=feed):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 2, f"sem IA configurada, nada deveria ser fundido, veio {msgs}"
    print("google_news sem IA configurada não funde notícias OK")


def test_google_news_ai_filter_removes_irrelevant_entry():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": ["u1"]}}

    entries = [
        {"link": "u2", "title": "Grupo Teste kpop lança clipe novo"},
        {"link": "u3", "title": "Homônimo Grupo Teste vence campeonato de xadrez"},
    ]
    feed = types.SimpleNamespace(entries=entries)

    with patch.object(google_news.feedparser, "parse", return_value=feed), \
         patch.object(google_news, "filter_relevant_titles", return_value=[0]):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 1 and "u2" in msgs[0], f"esperada só a notícia relevante segundo a IA, veio {msgs}"
    print("google_news filtro de relevância por IA OK:", msgs)


def test_google_news_ai_filter_disabled_keeps_all_entries():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": ["u1"]}}

    entries = [{"link": "u2", "title": "Notícia qualquer"}]
    feed = types.SimpleNamespace(entries=entries)

    # filter_relevant_titles real devolve None quando GEMINI_API_KEY não
    # está configurada (sem IA no ambiente de teste), não deve filtrar nada
    with patch.object(google_news.feedparser, "parse", return_value=feed):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 1 and "u2" in msgs[0], f"sem IA configurada, nada deveria ser filtrado, veio {msgs}"
    print("google_news sem IA configurada mantém todas as notícias OK")


def test_main_uses_ai_summary_when_valid():
    import main as main_module

    def ok_check(group, state):
        return ["*Grupo Teste* postou no YouTube:\nTítulo\nhttp://x.com/1"]

    group = {"name": "Grupo Teste"}
    state = {}
    sent = []

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [ok_check]), \
         patch.object(main_module, "summarize_updates", return_value="Boletim: Grupo Teste postou vídeo novo! http://x.com/1"), \
         patch.object(main_module, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        main_module.main()

    assert len(sent) == 1 and sent[0].startswith("Boletim:"), f"esperado o resumo da IA, veio {sent}"
    print("main usa resumo da IA quando válido OK:", sent[0])


def test_main_falls_back_to_raw_when_ai_returns_none():
    import main as main_module

    def ok_check(group, state):
        return ["novidade 1", "novidade 2"]

    group = {"name": "Grupo Teste"}
    state = {}
    sent = []

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [ok_check]), \
         patch.object(main_module, "summarize_updates", return_value=None), \
         patch.object(main_module, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        main_module.main()

    assert len(sent) == 1 and "novidade 1" in sent[0] and "novidade 2" in sent[0], f"esperado texto bruto, veio {sent}"
    print("main volta pro texto bruto quando IA não devolve resumo válido OK")


def test_main_reorders_updates_by_ai_rank():
    import main as main_module

    def ok_check(group, state):
        return ["*Grupo Teste* na mídia:\nnotícia menor\nhttp://x.com/1", "*Grupo Teste* lançou um álbum novo\nhttp://x.com/2"]

    group = {"name": "Grupo Teste"}
    state = {}
    sent = []

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [ok_check]), \
         patch.object(main_module, "rank_updates", return_value=[1, 0]), \
         patch.object(main_module, "summarize_updates", return_value=None), \
         patch.object(main_module, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        main_module.main()

    assert len(sent) == 1
    assert sent[0].index("álbum novo") < sent[0].index("notícia menor"), f"esperado álbum primeiro, veio {sent[0]}"
    print("main reordena novidades pela IA OK")


def test_main_keeps_original_order_when_rank_unavailable():
    import main as main_module

    def ok_check(group, state):
        return ["primeira novidade", "segunda novidade"]

    group = {"name": "Grupo Teste"}
    state = {}
    sent = []

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [ok_check]), \
         patch.object(main_module, "summarize_updates", return_value=None), \
         patch.object(main_module, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        main_module.main()

    assert len(sent) == 1
    assert sent[0].index("primeira novidade") < sent[0].index("segunda novidade"), f"esperada ordem original, veio {sent[0]}"
    print("main mantém ordem original quando rank indisponível OK")


def test_ai_rank_updates_returns_valid_permutation():
    import ai

    with patch.object(ai, "is_enabled", return_value=True), \
         patch.object(ai, "generate_text", return_value="[2, 0, 1]"):
        order = ai.rank_updates(["a", "b", "c"])

    assert order == [2, 0, 1]
    print("ai.rank_updates devolve permutação válida OK")


def test_ai_rank_updates_returns_none_on_incomplete_response():
    import ai

    with patch.object(ai, "is_enabled", return_value=True), \
         patch.object(ai, "generate_text", return_value="[0, 0]"):  # índice repetido, incompleto
        order = ai.rank_updates(["a", "b", "c"])

    assert order is None, "resposta incompleta/com repetição não deveria ser confiada"
    print("ai.rank_updates devolve None quando resposta vem incompleta OK")


def test_weekly_digest_appends_ai_commentary_when_enabled():
    import weekly_digest

    state = {"weekly_counts": {"Grupo Teste": {"check_youtube": 2}}}
    sent = []

    with patch.object(weekly_digest, "load_state", return_value=state), \
         patch.object(weekly_digest, "save_state", lambda s: None), \
         patch.object(weekly_digest, "is_enabled", return_value=True), \
         patch.object(weekly_digest, "generate_text", return_value="Grupo Teste bombou essa semana!"), \
         patch.object(weekly_digest, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        weekly_digest.main()

    assert len(sent) == 1 and "Grupo Teste bombou essa semana!" in sent[0], f"esperado comentário da IA anexado, veio {sent}"
    print("weekly digest com comentário da IA OK:", sent[0])


def test_telegram_recommend_command_without_ai_configured():
    import telegram_commands

    state = {}
    update = {"update_id": 20, "message": {"chat": {"id": 999}, "text": "/recommend"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert len(sent) == 1 and "GEMINI_API_KEY" in sent[0], f"esperado aviso de IA não configurada, veio {sent}"
        print("telegram /recommend sem IA configurada OK:", sent[0])
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_recommend_command_with_ai_configured():
    import telegram_commands

    state = {}
    update = {"update_id": 21, "message": {"chat": {"id": 999}, "text": "/recommend"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands, "load_config", return_value=[{"name": "IVE"}]), \
             patch.object(telegram_commands, "is_enabled", return_value=True), \
             patch.object(telegram_commands, "generate_text", return_value="- NewJeans: comece com Super Shy"), \
             patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert len(sent) == 1 and "NewJeans" in sent[0], f"esperada recomendação da IA, veio {sent}"
        print("telegram /recommend com IA configurada OK:", sent[0])
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_addgroup_command_creates_group():
    import telegram_commands

    tmp_bot_path = os.path.join(os.path.dirname(__file__), "_tmp_groups_bot.yaml")
    if os.path.exists(tmp_bot_path):
        os.remove(tmp_bot_path)

    state = {}
    update = {"update_id": 42, "message": {"chat": {"id": 999}, "text": "/addgroup Grupo Teste"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands, "GROUPS_BOT_PATH", tmp_bot_path), \
             patch.object(telegram_commands, "load_config", return_value=[]), \
             patch.object(telegram_commands, "find_channel_id", return_value="UCabc"), \
             patch.object(telegram_commands, "find_artist_id", return_value="123"), \
             patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert state["telegram"]["last_update_id"] == 42
        assert len(sent) == 1 and "Grupo Teste" in sent[0], f"esperada 1 confirmação, veio {sent}"

        with open(tmp_bot_path, "r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        group = saved["groups"][0]
        assert group["name"] == "Grupo Teste"
        assert group["youtube_channel_ids"] == ["UCabc"]
        assert group["itunes_artist_ids"] == ["123"]
        print("telegram /addgroup command OK:", sent[0].splitlines()[0])
    finally:
        if os.path.exists(tmp_bot_path):
            os.remove(tmp_bot_path)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_removegroup_command_deletes_group():
    import telegram_commands

    tmp_bot_path = os.path.join(os.path.dirname(__file__), "_tmp_groups_bot_remove.yaml")
    with open(tmp_bot_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"groups": [{"name": "Grupo Teste", "youtube_channel_ids": ["UCabc"]}]}, f)

    state = {}
    update = {"update_id": 7, "message": {"chat": {"id": 999}, "text": "/removegroup Grupo Teste"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands, "GROUPS_BOT_PATH", tmp_bot_path), \
             patch.object(telegram_commands, "load_config", return_value=[]), \
             patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert state["telegram"]["last_update_id"] == 7
        assert len(sent) == 1 and "removido" in sent[0], f"esperada 1 confirmação de remoção, veio {sent}"

        with open(tmp_bot_path, "r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["groups"] == []
        print("telegram /removegroup command OK:", sent[0])
    finally:
        if os.path.exists(tmp_bot_path):
            os.remove(tmp_bot_path)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_listgroups_command_replies_with_groups():
    import telegram_commands

    tmp_bot_path = os.path.join(os.path.dirname(__file__), "_tmp_groups_bot_list.yaml")
    with open(tmp_bot_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"groups": [{"name": "Grupo Bot"}]}, f)

    state = {}
    update = {"update_id": 9, "message": {"chat": {"id": 999}, "text": "/listgroups"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    merged_groups = [{"name": "Grupo Manual"}, {"name": "Grupo Bot"}]

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands, "GROUPS_BOT_PATH", tmp_bot_path), \
             patch.object(telegram_commands, "load_config", return_value=merged_groups), \
             patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert state["telegram"]["last_update_id"] == 9
        assert len(sent) == 1, f"esperada 1 resposta, veio {sent}"
        assert "Grupo Manual" in sent[0] and "manual" in sent[0]
        assert "Grupo Bot" in sent[0] and "/addgroup" in sent[0]
        print("telegram /listgroups command OK:", sent[0].splitlines()[0])
    finally:
        if os.path.exists(tmp_bot_path):
            os.remove(tmp_bot_path)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_help_command_replies_with_help_text():
    import telegram_commands

    state = {}
    update = {"update_id": 11, "message": {"chat": {"id": 999}, "text": "/help"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert state["telegram"]["last_update_id"] == 11
        assert len(sent) == 1 and "/addgroup" in sent[0] and "/pausegroup" in sent[0]
        print("telegram /help command OK")
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_process_webhook_update_dispatches_command():
    import process_webhook_update

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_UPDATE_JSON"] = json.dumps(
        {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/help"}}
    )
    sent = []

    try:
        with patch.object(process_webhook_update, "send_telegram_message", side_effect=lambda t, **kw: sent.append(t)):
            process_webhook_update.main()
        assert len(sent) == 1 and "/addgroup" in sent[0], f"esperada 1 resposta com /addgroup, veio {sent}"
        print("process_webhook_update /help OK")
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_UPDATE_JSON", None)


def test_process_webhook_update_ignores_other_chat():
    import process_webhook_update

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_UPDATE_JSON"] = json.dumps(
        {"update_id": 1, "message": {"chat": {"id": 111}, "text": "/help"}}
    )
    sent = []

    try:
        with patch.object(process_webhook_update, "send_telegram_message", side_effect=lambda t, **kw: sent.append(t)):
            process_webhook_update.main()
        assert sent == [], f"esperado nenhuma resposta pra chat diferente, veio {sent}"
        print("process_webhook_update ignora outro chat OK")
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_UPDATE_JSON", None)


def test_telegram_pausegroup_and_resumegroup_commands():
    import telegram_commands

    tmp_bot_path = os.path.join(os.path.dirname(__file__), "_tmp_groups_bot_pause.yaml")
    with open(tmp_bot_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"groups": [{"name": "Grupo Teste"}]}, f)

    def make_resp(update_id, text):
        update = {"update_id": update_id, "message": {"chat": {"id": 999}, "text": text}}

        class FakeResp:
            def raise_for_status(self):
                pass
            def json(self):
                return {"result": [update]}
        return FakeResp()

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []
    state = {}

    try:
        with patch.object(telegram_commands, "GROUPS_BOT_PATH", tmp_bot_path), \
             patch.object(telegram_commands, "load_config", return_value=[{"name": "Grupo Teste"}]), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):

            with patch.object(telegram_commands.requests, "get", return_value=make_resp(1, "/pausegroup Grupo Teste")):
                telegram_commands.process_telegram_commands(state)
            assert len(sent) == 1 and "pausado" in sent[0], f"esperado 'pausado', veio {sent}"

            with open(tmp_bot_path, "r", encoding="utf-8") as f:
                saved = yaml.safe_load(f)
            assert saved["groups"][0]["paused"] is True

            with patch.object(telegram_commands.requests, "get", return_value=make_resp(2, "/resumegroup Grupo Teste")):
                telegram_commands.process_telegram_commands(state)
            assert len(sent) == 2 and "reativado" in sent[1], f"esperado 'reativado', veio {sent}"

            with open(tmp_bot_path, "r", encoding="utf-8") as f:
                saved = yaml.safe_load(f)
            assert saved["groups"][0]["paused"] is False

        print("telegram /pausegroup + /resumegroup OK:", sent)
    finally:
        if os.path.exists(tmp_bot_path):
            os.remove(tmp_bot_path)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_google_news_dedup_similar_titles():
    from sources import google_news

    group = {"name": "Grupo Teste", "google_news_query": "grupo teste kpop"}
    state = {"google_news": {"Grupo Teste": ["u1"]}}

    entries = [
        {"link": "u3", "title": "Grupo Teste anuncia nova turnê mundial para 2026"},
        {"link": "u2", "title": "Grupo Teste confirma nova turnê mundial para 2026"},
    ]
    feed = types.SimpleNamespace(entries=entries)

    with patch.object(google_news.feedparser, "parse", return_value=feed):
        msgs = google_news.check_google_news(group, state)

    assert len(msgs) == 1, f"esperada 1 notificação (títulos quase iguais deduplicados), veio {msgs}"
    print("google_news title dedup OK:", msgs)


def _fake_melon_html(rows):
    parts = []
    for song_id, rank, artist_id, title in rows:
        parts.append(
            f'<tr data-song-no="{song_id}">'
            f'<td><span class="rank ">{rank}</span></td>'
            f'<td><a title="{title} 재생">{title}</a></td>'
            f'<td><a href="/artist/detail.htm?artistId={artist_id}" title="Artist - 페이지 이동">Artist</a></td>'
            f"</tr>"
        )
    return "".join(parts)


def test_melon_first_run_then_new_chart_entry():
    from sources import melon

    group = {"name": "Grupo Teste", "melon_artist_id": "123"}
    state = {}

    rows_v1 = [("1001", 5, "123", "Song A")]
    rows_v2 = rows_v1 + [("1002", 10, "123", "Song B")]

    class FakeResp:
        def __init__(self, html):
            self.text = html
        def raise_for_status(self):
            pass

    with patch.object(melon.requests, "get", return_value=FakeResp(_fake_melon_html(rows_v1))):
        msgs_first = melon.check_melon(group, state)
    assert msgs_first == [], f"esperado nenhuma notificação no primeiro run, veio {msgs_first}"

    with patch.object(melon.requests, "get", return_value=FakeResp(_fake_melon_html(rows_v2))):
        msgs_second = melon.check_melon(group, state)
    assert len(msgs_second) == 1 and "Song B" in msgs_second[0], f"esperado 1 notificação sobre Song B, veio {msgs_second}"
    print("melon diff logic OK:", msgs_second)


def test_main_alerts_after_repeated_source_failures():
    import main as main_module

    def failing_check(group, state):
        raise RuntimeError("boom")

    group = {"name": "Grupo Teste"}
    state = {}
    sent = []

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [failing_check]), \
         patch.object(main_module, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        for _ in range(main_module.FAILURE_ALERT_THRESHOLD):
            main_module.main()

    assert len(sent) == 1, f"esperado 1 alerta após {main_module.FAILURE_ALERT_THRESHOLD} falhas seguidas, veio {sent}"
    assert "falhando" in sent[0]
    print("main failure alert OK:", sent[0])


def test_main_logs_activity_for_ask():
    import main as main_module

    def ok_check(group, state):
        return ["*Grupo Teste* postou no YouTube:\nVídeo novo\nhttp://x.com/1"]

    group = {"name": "Grupo Teste"}
    state = {}

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [ok_check]), \
         patch.object(main_module, "send_telegram_message", lambda *a, **kw: None):
        main_module.main()

    log = state["activity_log"]
    assert len(log) == 1 and log[0]["group"] == "Grupo Teste" and "Vídeo novo" in log[0]["text"]
    assert "ts" in log[0]
    print("main registra atividade pro /ask OK:", log)


def test_prune_activity_log_removes_old_entries_and_caps_size():
    import main as main_module
    import time

    old_ts = time.time() - (main_module.ACTIVITY_LOG_MAX_AGE_DAYS + 1) * 86400
    recent_ts = time.time()
    state = {
        "activity_log": [
            {"ts": old_ts, "group": "A", "text": "velho demais"},
            {"ts": recent_ts, "group": "B", "text": "recente"},
        ]
    }

    main_module._prune_activity_log(state)

    assert len(state["activity_log"]) == 1 and state["activity_log"][0]["text"] == "recente"
    print("main._prune_activity_log remove entradas velhas OK")


def test_telegram_ask_command_without_ai_configured():
    import telegram_commands

    state = {}
    update = {"update_id": 30, "message": {"chat": {"id": 999}, "text": "/ask o que rolou com a IVE?"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert len(sent) == 1 and "GEMINI_API_KEY" in sent[0], f"esperado aviso de IA não configurada, veio {sent}"
        print("telegram /ask sem IA configurada OK:", sent[0])
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_ask_command_with_no_history():
    import telegram_commands

    state = {}
    update = {"update_id": 31, "message": {"chat": {"id": 999}, "text": "/ask o que rolou com a IVE?"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands, "is_enabled", return_value=True), \
             patch.object(telegram_commands, "load_full_state", return_value={}), \
             patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert len(sent) == 1 and "não tenho novidades" in sent[0], f"esperado aviso de histórico vazio, veio {sent}"
        print("telegram /ask sem histórico OK:", sent[0])
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_telegram_ask_command_answers_from_history():
    import telegram_commands

    state = {}
    update = {"update_id": 32, "message": {"chat": {"id": 999}, "text": "/ask o que rolou com a IVE essa semana?"}}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"result": [update]}

    fake_state = {"activity_log": [{"ts": 1755000000, "group": "IVE", "text": "*IVE* lançou um álbum novo"}]}

    os.environ["TELEGRAM_CHAT_ID"] = "999"
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
    sent = []

    try:
        with patch.object(telegram_commands, "is_enabled", return_value=True), \
             patch.object(telegram_commands, "load_full_state", return_value=fake_state), \
             patch.object(telegram_commands, "generate_text", return_value="A IVE lançou um álbum novo essa semana!") as mock_gen, \
             patch.object(telegram_commands.requests, "get", return_value=FakeResp()), \
             patch.object(telegram_commands, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
            telegram_commands.process_telegram_commands(state)

        assert len(sent) == 1 and "álbum novo" in sent[0]
        prompt_used = mock_gen.call_args[0][0]
        assert "IVE" in prompt_used and "o que rolou com a IVE essa semana?" in prompt_used
        print("telegram /ask responde com base no histórico OK:", sent[0])
    finally:
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_main_tracks_weekly_counts():
    import main as main_module

    def ok_check(group, state):
        return ["novidade 1", "novidade 2"]

    group = {"name": "Grupo Teste"}
    state = {}

    with patch.object(main_module, "load_config", return_value=[group]), \
         patch.object(main_module, "load_state", return_value=state), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [ok_check]), \
         patch.object(main_module, "send_telegram_message", lambda *a, **kw: None):
        main_module.main()

    assert state["weekly_counts"]["Grupo Teste"]["ok_check"] == 2
    print("main weekly_counts tracking OK:", state["weekly_counts"])


def test_main_skips_paused_group():
    import main as main_module

    calls = []

    def tracking_check(group, state):
        calls.append(group["name"])
        return []

    groups = [{"name": "Grupo Pausado", "paused": True}, {"name": "Grupo Ativo"}]

    with patch.object(main_module, "load_config", return_value=groups), \
         patch.object(main_module, "load_state", return_value={}), \
         patch.object(main_module, "save_state", lambda s: None), \
         patch.object(main_module, "process_telegram_commands", lambda s: None), \
         patch.object(main_module, "SOURCE_CHECKS", [tracking_check]), \
         patch.object(main_module, "send_telegram_message", lambda *a, **kw: None):
        main_module.main()

    assert calls == ["Grupo Ativo"], f"esperado só o grupo ativo, veio {calls}"
    print("main paused-group skip OK")


def test_weekly_digest_builds_summary_and_resets():
    import weekly_digest

    state = {"weekly_counts": {"Grupo Teste": {"check_youtube": 2, "check_itunes": 1}}}
    sent = []

    with patch.object(weekly_digest, "load_state", return_value=state), \
         patch.object(weekly_digest, "save_state", lambda s: None), \
         patch.object(weekly_digest, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        weekly_digest.main()

    assert len(sent) == 1 and "Grupo Teste" in sent[0] and "YouTube" in sent[0], f"resumo inesperado: {sent}"
    assert state["weekly_counts"] == {}
    print("weekly digest OK:", sent[0])


def test_weekly_digest_skips_send_when_no_counts():
    import weekly_digest

    state = {"weekly_counts": {}}
    sent = []

    with patch.object(weekly_digest, "load_state", return_value=state), \
         patch.object(weekly_digest, "save_state", lambda s: None), \
         patch.object(weekly_digest, "send_telegram_message", side_effect=lambda text, **kw: sent.append(text)):
        weekly_digest.main()

    assert sent == [], f"esperado nenhum envio sem novidades na semana, veio {sent}"
    print("weekly digest sem novidades: não envia OK")


def test_build_message_batches_groups_small_messages_into_one():
    from telegram_notify import build_message_batches

    batches = build_message_batches(["novidade 1", "novidade 2", "novidade 3"])
    assert len(batches) == 1
    assert "novidade 1" in batches[0] and "novidade 3" in batches[0]
    print("build_message_batches agrupa mensagens pequenas em 1 lote OK")


def test_build_message_batches_splits_when_over_telegram_limit():
    from telegram_notify import build_message_batches, TELEGRAM_MESSAGE_LIMIT

    big_msg = "x" * (TELEGRAM_MESSAGE_LIMIT - 10)
    batches = build_message_batches([big_msg, big_msg])
    assert len(batches) == 2, f"esperado 2 lotes (não cabe tudo em 1 msg), veio {len(batches)}"
    assert all(len(b) <= TELEGRAM_MESSAGE_LIMIT for b in batches)
    print("build_message_batches respeita o limite de 4096 caracteres OK")


def test_build_message_batches_empty_list_returns_no_batches():
    from telegram_notify import build_message_batches

    assert build_message_batches([]) == []
    print("build_message_batches com lista vazia retorna [] OK")


def test_youtube_diff_logic_with_mock_client():
    from sources import youtube

    group = {"name": "Grupo Teste", "youtube_channel_ids": ["UC1"]}
    state = {}

    def make_client(video_ids):
        client = types.SimpleNamespace()

        class Channels:
            def list(self, part, id):
                class Req:
                    def execute(self_inner):
                        return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "PL1"}}}]}
                return Req()

        class PlaylistItems:
            def list(self, part, playlistId, maxResults):
                class Req:
                    def execute(self_inner):
                        # API retorna do mais novo pro mais antigo
                        items = [
                            {"snippet": {"title": f"Video {vid}", "resourceId": {"videoId": vid}}}
                            for vid in reversed(video_ids)
                        ]
                        return {"items": items}
                return Req()

        client.channels = lambda: Channels()
        client.playlistItems = lambda: PlaylistItems()
        return client

    os.environ["YOUTUBE_API_KEY"] = "fake-key-for-test"
    youtube._youtube_client = make_client(["v1", "v2", "v3"])
    msgs_first = youtube.check_youtube(group, state)
    assert msgs_first == [], f"esperado nenhuma notificação no primeiro run, veio {msgs_first}"

    youtube._youtube_client = make_client(["v1", "v2", "v3", "v4"])
    msgs_second = youtube.check_youtube(group, state)
    assert len(msgs_second) == 1 and "v4" in msgs_second[0], f"esperado 1 notificação sobre v4, veio {msgs_second}"
    print("youtube diff logic OK:", msgs_second)

    youtube._youtube_client = None
    os.environ.pop("YOUTUBE_API_KEY", None)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        class P:
            def __init__(self, base):
                self.base = base
            def __truediv__(self, other):
                return os.path.join(self.base, other)
        test_state_roundtrip(P(d))
    test_youtube_no_credentials_returns_empty()
    test_itunes_first_run_no_notification_then_detects_new()
    test_google_news_first_run_no_notification_then_detects_new()
    test_google_news_ignores_old_reindexed_entry()
    test_google_news_queries_multiple_locales_and_translates_foreign_entries()
    test_google_news_falls_back_to_original_title_when_translation_unavailable()
    test_google_news_dedups_same_link_returned_by_multiple_locales()
    test_ai_translate_to_ptbr_uses_cache_on_second_call()
    test_ai_translate_to_ptbr_cache_miss_on_different_text()
    test_ai_filter_relevant_titles_uses_cache_on_second_call()
    test_google_news_rerun_after_failed_save_uses_cache_instead_of_recalling_ai()
    test_prune_ai_cache_removes_old_entries_and_caps_size()
    test_google_news_ai_merges_duplicate_coverage_of_same_event()
    test_google_news_merge_disabled_keeps_all_entries_separate()
    test_google_news_ai_filter_removes_irrelevant_entry()
    test_google_news_ai_filter_disabled_keeps_all_entries()
    test_main_uses_ai_summary_when_valid()
    test_main_falls_back_to_raw_when_ai_returns_none()
    test_main_reorders_updates_by_ai_rank()
    test_main_keeps_original_order_when_rank_unavailable()
    test_ai_rank_updates_returns_valid_permutation()
    test_ai_rank_updates_returns_none_on_incomplete_response()
    test_weekly_digest_appends_ai_commentary_when_enabled()
    test_telegram_recommend_command_without_ai_configured()
    test_telegram_recommend_command_with_ai_configured()
    test_telegram_addgroup_command_creates_group()
    test_telegram_removegroup_command_deletes_group()
    test_telegram_listgroups_command_replies_with_groups()
    test_telegram_help_command_replies_with_help_text()
    test_process_webhook_update_dispatches_command()
    test_process_webhook_update_ignores_other_chat()
    test_telegram_pausegroup_and_resumegroup_commands()
    test_google_news_dedup_similar_titles()
    test_melon_first_run_then_new_chart_entry()
    test_main_alerts_after_repeated_source_failures()
    test_main_logs_activity_for_ask()
    test_prune_activity_log_removes_old_entries_and_caps_size()
    test_telegram_ask_command_without_ai_configured()
    test_telegram_ask_command_with_no_history()
    test_telegram_ask_command_answers_from_history()
    test_main_tracks_weekly_counts()
    test_main_skips_paused_group()
    test_weekly_digest_builds_summary_and_resets()
    test_weekly_digest_skips_send_when_no_counts()
    test_build_message_batches_groups_small_messages_into_one()
    test_build_message_batches_splits_when_over_telegram_limit()
    test_build_message_batches_empty_list_returns_no_batches()
    test_youtube_diff_logic_with_mock_client()
    print("\nTODOS OS TESTES PASSARAM")
