"""Persiste o que já foi visto (vídeos, lançamentos, notícias, eventos)
em state/seen.json, pra não notificar a mesma coisa duas vezes.

Como o GitHub Actions roda em máquinas efêmeras, o workflow commita esse
arquivo de volta no repositório a cada execução (veja .github/workflows).
"""
import json
import os


def load_state(path="state/seen.json"):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)


def save_state(state, path="state/seen.json"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
