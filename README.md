# gg-heartbeat

[![Checar novidades das idols](https://github.com/Chiardelli/gg-heartbeat/actions/workflows/check-updates.yml/badge.svg)](https://github.com/Chiardelli/gg-heartbeat/actions/workflows/check-updates.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

> Bot de alertas no Telegram sobre girl groups de kpop, feito por uma gg stan com pouco tempo para scrollar no twitter. ˚.🎀༘⋆

## Índice

- [O que é](#o-que-é)
- [O que ele monitora](#o-que-ele-monitora)
- [Como funciona por baixo dos panos](#como-funciona-por-baixo-dos-panos)
- [Instalação](#instalação)
- [Como usar](#como-usar)
- [Testes](#testes)
- [Contribuindo](#contribuindo)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Licença](#licença)

## O que é

`gg-heartbeat` é um bot que fica de olho nos grupos de kpop que você acompanha e te avisa no Telegram assim que sai algo novo: vídeo no YouTube, álbum/single ou notícia. Essa ideia surgiu para resolver um problema bem específico meu, que é não ter mais o mesmo tempo de quando eu era adolescente e podia ficar no twitter acompanhando tudo em tempo real, mas felizmente, hoje em dia, existe o GitHub Actions para fazer isso por mim.

Atualmente ele monitora apenas o YouTube, Itunes (álbum/single), Melon (música entrou no Top 100 do chart coreano) e faz a consulta na web para notícias, mas futuramente pretendo adicionar outras plataformas

Não tem servidor, banco de dados nem custo de hospedagem: ele roda de hora em hora como um workflow do GitHub Actions, usando o próprio repositório Git como "banco de dados" do que já foi visto.

## O que ele monitora

| Fonte | O que detecta | Precisa de quê |
|---|---|---|
| YouTube | Vídeo novo em um canal | Chave gratuita da YouTube Data API |
| iTunes/Apple Music | Álbum/single novo | Nada (API pública) |
| Google News | Notícia nova sobre o grupo | Nada (RSS público) |
| Melon | Música entrou no Top 100 do chart coreano | Nada (scraping da página pública — mais frágil que as outras fontes, veja [Troubleshooting](#troubleshooting)) |


## Como funciona por baixo dos panos

Um workflow do GitHub Actions roda a cada hora (`.github/workflows/check-updates.yml`), executa `src/main.py`, que:

1. Lê os grupos configurados em `config/groups.yaml`;
2. Pra cada grupo, checa cada fonte e compara com o que já foi visto antes (guardado em `state/seen.json`);
3. Manda uma mensagem no Telegram pra cada novidade encontrada;
4. Commita `state/seen.json` de volta no repositório, pra lembrar o que já foi notificado da próxima vez.

## Instalação

### 1. Criar o bot no Telegram

1. Fale com [@BotFather](https://t.me/BotFather) no Telegram e mande `/newbot`.
2. Siga as instruções (nome + username do bot). No final ele te dá um **token** — é o seu `TELEGRAM_BOT_TOKEN`.
3. Mande uma mensagem qualquer pro seu bot recém-criado (ele precisa ter uma conversa iniciada com você pra poder te mandar mensagens).
4. Pra pegar seu `TELEGRAM_CHAT_ID`, a forma mais simples é falar com [@userinfobot](https://t.me/userinfobot) — ele te devolve seu ID numérico. (Alternativa: acesse `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` depois de mandar uma mensagem pro seu bot, e procure o campo `"chat":{"id": ...}` na resposta.)

### 2. Criar a chave da YouTube Data API (gratuita)

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/), crie um projeto (ou use um existente).
2. Vá em **APIs & Services > Library**, procure "YouTube Data API v3" e clique em **Enable**.
3. Vá em **APIs & Services > Credentials > Create Credentials > API key**. Essa é a sua `YOUTUBE_API_KEY`.
4. Não precisa de cartão de crédito nem billing pra isso e como a cota gratuita é de 10.000 unidades/dia, é mais que suficiente pro uso desse bot.

### 3. iTunes/Apple Music (nada a configurar)

Usa a API pública de busca/lookup da Apple pra detectar álbum/single novo — não precisa de conta nem chave. Só é necessário achar o `artistId` numérico de cada grupo

### 4. Configurar seus grupos

Edite `config/groups.yaml` e substitua pelos grupos que você acompanha. Pra cada grupo:

- **`youtube_channel_ids`**: o ID do canal (começa com `UC...`). Forma mais fácil de achar: vá no canal no YouTube, clique em qualquer vídeo, veja o código-fonte da página (Ctrl+U) e procure por `"channelId"` — ou use um site como [comment-picker.com/youtube-channel-id.php](https://commentpicker.com/youtube-channel-id.php).
- **`itunes_artist_ids`**: acesse `https://itunes.apple.com/search?term=NOME+DO+GRUPO&entity=musicArtist` no navegador e pegue o campo `artistId` do resultado certo.
- **`google_news_query`**: qualquer termo de busca — capriche pra reduzir ruído (ex: `"NewJeans kpop"` em vez de só `"NewJeans"`).
- **`melon_artist_id`** (opcional): acesse [melon.com](https://www.melon.com), busque o grupo, abra a página do artista e pegue o número depois de `artistId=` na URL.

Todos os campos são opcionais — se não quiser monitorar uma fonte pra um grupo, é só remover ou deixar a lista vazia (`[]`). Também dá pra pausar um grupo inteiro sem remover, colocando `paused: true` no bloco dele (ou usando `/pausegroup` no Telegram, se ele foi adicionado por lá).

### 5. Configurar os Secrets no GitHub

No repositório: **Settings > Secrets and variables > Actions > New repository secret**. Crie um secret pra cada uma dessas chaves (com os valores que você pegou nos passos acima):

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `YOUTUBE_API_KEY`

### 6. Permitir que o workflow commite de volta

Em **Settings > Actions > General > Workflow permissions**, selecione **Read and write permissions** e salve. Sem isso, o passo que salva `state/seen.json` vai falhar (o restante — checagem e notificação — funciona normalmente mesmo assim).

### 7. Testar

Depois de configurar os secrets e o `config/groups.yaml`, vá na aba **Actions** do repositório, clique no workflow "Checar novidades das idols" e depois em **Run workflow** pra disparar manualmente. Confira os logs pois na primeira execução o bot só grava a "baseline" de cada fonte (não notifica o histórico todo de uma vez), e por isso não é esperado receber mensagem nenhuma no primeiro run.

## Como usar

No dia a dia você não precisa fazer nada, o workflow roda sozinho de hora em hora e as novidades chegam direto no Telegram.

Comandos disponíveis no Telegram:

- **`/help`**: mostra a lista de comandos disponíveis.
- **`/addgroup Nome Do Grupo`**: adiciona um grupo. O bot tenta achar sozinho o canal do YouTube e o artista no iTunes, salva em `config/groups_bot.yaml` (mesclado automaticamente com `config/groups.yaml`) e responde confirmando o que encontrou. Vale conferir se o match ficou certo, principalmente pra nomes de grupo mais genéricos. Some efeito no próximo run (até 1h, ou dispare manualmente como abaixo).
- **`/removegroup Nome Do Grupo`**: remove um grupo. Só funciona pra grupos adicionados via `/addgroup` (ou seja, que estão em `config/groups_bot.yaml`)
- **`/pausegroup Nome Do Grupo`** / **`/resumegroup Nome Do Grupo`**: pausa/reativa as notificações de um grupo sem perder o histórico (útil pra grupo em hiatus). Mesma restrição do `/removegroup`: só funciona pra grupos adicionados via `/addgroup`.
- **`/listgroups`**: lista todos os grupos configurados (de `config/groups.yaml` e `config/groups_bot.yaml` juntos), indicando origem (`manual`/`via /addgroup`) e se está pausado.

Outras formas de ajustar o bot:

- **Adicionar ou remover um grupo editando o repositório**: edite `config/groups.yaml`, dê commit e push. O próximo run do workflow já considera a mudança.
- **Forçar uma checagem na hora**: aba **Actions** do repositório > workflow "Checar novidades das idols" > **Run workflow**.
- **Ajustar a frequência**: o cron padrão (`0 * * * *`) roda de hora em hora. Pra rodar a cada 30 minutos, troque por `*/30 * * * *` em `.github/workflows/check-updates.yml` — só fique de olho na cota de minutos do Actions se o repositório for privado.
- **Resumo semanal**: além dos alertas em tempo real, um segundo workflow (`.github/workflows/weekly-digest.yml`) roda toda segunda-feira e manda um resumo consolidado ("X novidades essa semana, por grupo/fonte") — não precisa configurar nada além dos secrets já usados pelo workflow principal.
- **Rodar localmente** (útil pra debugar antes de subir uma mudança):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # preencha as variáveis
export $(grep -v '^#' .env | xargs)  # carrega o .env no shell
python src/main.py
```

## Testes

`tests/test_logic.py` valida a lógica de "o que é novo" de cada fonte com dados falsos (sem precisar de credenciais reais ou rede). Rode com:

```bash
python3 tests/test_logic.py
```

Um workflow de CI (`.github/workflows/tests.yml`) roda esses testes automaticamente a cada push/PR.

## Contribuindo

O gg-heartbeat/Sora Bot é um projeto pessoal meu, mas issues e PRs são bem-vindos principalmente pra novas fontes ou correções. ^^

1. Faça um fork e crie uma branch a partir da `main`.
2. Rode `pip install -r requirements.txt` e confirme que `python3 tests/test_logic.py` passa antes e depois da sua mudança.
3. Abra o PR descrevendo o que mudou e por quê.

**Pra adicionar uma fonte nova** (ex: um novo serviço de música ou rede social): crie um módulo em `src/sources/` com uma função `check_<fonte>(group, state)` que devolve uma lista de mensagens de texto, seguindo o padrão dos módulos existentes (`youtube.py`, `itunes.py`, `google_news.py`, `melon.py`) — cada fonte é isolada e só precisa ser registrada em `SOURCE_CHECKS`, em `src/main.py`. A seção [Roadmap](#roadmap) tem algumas ideias de fontes que ainda faltam.

Encontrou um bug ou tem uma sugestão? Abra uma [issue](https://github.com/Chiardelli/gg-heartbeat/issues). :3

## Troubleshooting

- **Não chega nenhuma mensagem**: confira se você mandou uma mensagem pro bot antes (o Telegram só deixa bots iniciarem conversa se o usuário falou com ele primeiro) e se `TELEGRAM_CHAT_ID` está correto.
- **Erro ao commitar o state**: revise o passo 7 da instalação (permissão de escrita do workflow).
- **YouTube retornando erro de cota**: dificilmente vai acontecer com poucos canais, mas se tiver muitos grupos/canais, considere rodar de hora em hora em vez de a cada 30 min.
- **Fonte "X" falhando pra "Grupo" há N execuções seguidas**: alerta automático quando uma fonte quebra de verdade (não é só uma falha isolada) — confira os logs do Actions pra ver o erro completo. A fonte do Melon é a mais sujeita a isso porque não tem API oficial (é scraping da página do chart); se a Melon mudar o layout do site, é só isso que quebra, as outras fontes continuam normais.

## Roadmap

- Separar grupos em "prioridade alta" (checagem mais frequente) e "prioridade baixa".
- Adicionar Genie (outro chart coreano) seguindo o mesmo padrão do `melon.py`.
