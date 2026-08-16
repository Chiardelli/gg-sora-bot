/**
 * Retransmissor entre o Telegram e o GitHub Actions.
 *
 * Recebe o webhook do Telegram (push, instantâneo) e dispara um
 * `repository_dispatch` no GitHub, que aciona o workflow
 * `.github/workflows/telegram-webhook.yml` — esse sim roda o
 * `telegram_commands.py` de verdade e responde no Telegram.
 *
 * Esse worker é só uma ponte: não conhece a lógica de comandos, não guarda
 * nada, e o token do GitHub que ele usa só precisa da permissão "Actions:
 * write" (não escreve conteúdo no repositório diretamente).
 */
export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok");
    }

    const secretHeader = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (secretHeader !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch (err) {
      return new Response("bad request", { status: 400 });
    }

    const ghResp = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "gg-heartbeat-telegram-relay",
      },
      body: JSON.stringify({
        event_type: "telegram-command",
        client_payload: update,
      }),
    });

    if (!ghResp.ok) {
      console.error("falha ao disparar repository_dispatch:", ghResp.status, await ghResp.text());
    }

    // sempre responde 200 pro Telegram, mesmo se o dispatch falhar —
    // evita o Telegram reenviar o mesmo update indefinidamente
    return new Response("ok");
  },
};
