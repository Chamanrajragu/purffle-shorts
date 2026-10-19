<div align="center">

# PurffleShorts — Gerador gratuito de YouTube Shorts com IA e piloto automático de uploads

[English](README.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · **Português** · [हिन्दी](README.hi.md) · [日本語](README.ja.md)

**Um gerador de vídeos open source com IA para YouTube Shorts, TikTok e Instagram Reels. Passe para ele um tema, uma página da web, um post do Reddit ou um podcast longo, e ele cria vídeos verticais prontos (roteiro, narração, imagens, legendas) e depois faz o upload ou agenda a publicação no YouTube.**

[![CI](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml/badge.svg)](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Chamanrajragu/purffle-shorts?style=social)](https://github.com/Chamanrajragu/purffle-shorts/stargazers)

<img src="docs/hero.gif" alt="Três Shorts feitos pelo PurffleShorts rodando lado a lado: um vídeo de curiosidades sobre flamingos com legendas que destacam cada palavra, um diálogo com duas vozes sobre polvos com o nome de quem está falando na tela, e uma história em mensagens de texto na tela animada de um celular" width="770">

<sub>Resultado real, sem edição. Vozes neurais gratuitas da Microsoft e imagens geradas por IA. Os GIFs não têm som.</sub>

**Teste sem nenhuma chave de API e sem cadastro** (precisa do [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from git+https://github.com/Chamanrajragu/purffle-shorts purffle-shorts demo --style chat
```

**⭐ Se o PurffleShorts economiza seu tempo, uma estrela ajuda outros criadores a encontrá-lo.**

</div>

> Esta é uma versão resumida. A documentação completa (todas as configurações, modelos de IA, vozes, legendas, publicação, linha de comando, Studio, solução de problemas) está no [README em inglês](README.md).

## O que é o PurffleShorts?

O PurffleShorts é uma ferramenta de automação de YouTube Shorts para canais dark. É só iniciar que ele segue sozinho: um tema novo, um roteiro escrito pelo modelo de IA que você escolher e depois revisado e enxugado por uma segunda passada de IA, uma narração natural feita por IA, imagens relevantes, legendas sincronizadas com cada palavra falada, uma renderização bem acabada e um upload ou uma publicação agendada.

Ele também é um pequeno estúdio: edite qualquer linha do roteiro antes de renderizar, crie diálogos com duas vozes, histórias em mensagens de texto e histórias no estilo Reddit, transforme um artigo ou um post do Reddit em um Short, corte um podcast em Shorts e publique o mesmo vídeo em vários idiomas. Ele roda no seu próprio computador (macOS, Windows, Linux ou Docker), e os arquivos MP4 em 9:16 também servem para TikTok e Instagram Reels.

## Recursos

- **Qualquer modelo de IA:** OpenAI GPT, Anthropic Claude, Google Gemini, DeepSeek, Mistral, xAI Grok, Groq, OpenRouter, Together AI, Ollama e LM Studio (locais e gratuitos), ou qualquer API compatível com a da OpenAI. Os provedores de reserva listados em `LLM_FALLBACKS` são tentados em ordem se o principal falhar. Nos provedores que oferecem isso (OpenAI, Gemini, OpenRouter, Ollama, LM Studio, Claude), as respostas seguem um esquema JSON estrito.
- **Script Doctor:** uma segunda passada de IA avalia cada roteiro em seis pontos (gancho, curiosidade, ritmo, detalhes concretos, desfecho e precisão), lista o que está fraco e reescreve o texto. A nova versão é avaliada de novo e só fica se tiver nota igual ou maior, então a nota de retenção (de 0 a 100) é sempre a do roteiro que você recebe. Verificações automáticas (gancho longo demais, palavras de enchimento, nenhuma chamada para ação, nenhum número concreto) entram na revisão.
- **322 vozes neurais gratuitas em 75 idiomas** com sincronização palavra por palavra, sem precisar de chave. Duas vozes para diálogos e histórias em chat.
- **Imagens para cada frase:** vídeos de banco do Pexels ou do Pixabay (chaves gratuitas), imagens geradas por IA ou a sua própria pasta de mídia. Cada opção recebe uma nota pelo quanto a própria descrição combina com a cena.
- **Ritmo rápido:** cenas com mais de 4,5 s viram várias tomadas com imagens diferentes, e cada corte cai numa pausa natural entre as palavras (`MAX_SHOT_SECONDS`).
- **Legendas animadas palavra por palavra** em seis estilos, para escrita latina, índica, árabe, tailandesa e CJK. Com vozes que não informam o tempo de cada palavra, o fim de cada frase é fixado nas pausas reais do áudio, e as legendas continuam sincronizadas.
- **Áudio com qualidade de transmissão:** uma limpeza leve da voz (corte de graves, de-esser, compressão) e normalização de loudness em duas passadas, que mede a mixagem e aplica um ganho constante: −14 LUFS sem aquele efeito de "bombeamento".
- **Capa:** o quadro mais nítido e bem exposto dos primeiros segundos, nunca um quadro no meio de uma transição.
- Saída em **9:16, 16:9, 1:1 ou 4:5**, renderizada com ffmpeg. Não precisa de GPU.
- **Faz upload no YouTube** ou agenda cada vídeo no seu próximo horário livre, com a declaração de conteúdo gerado por IA já marcada.
- **Um vídeo, vários idiomas:** `--also-lang es,hi` cria cópias traduzidas que reaproveitam as mesmas imagens.
- **App web Studio** no seu computador: crie rascunhos, edite, renderize e navegue pela biblioteca. O progresso chega na hora, com porcentagem e tempo restante calculados a partir do seu próprio computador, e o botão **Cancel** interrompe um trabalho em andamento. Quando o Studio roda num servidor, `STUDIO_PASSWORD` o protege com senha.
- Uma linha de progresso ao vivo no terminal e um cache de voz: ao renderizar de novo um roteiro editado, só as falas que mudaram são narradas outra vez.
- **Servidor MCP:** peça ao Claude Desktop, ao Claude Code ou ao Cursor para criar, cortar ou fazer upload de vídeos.
- **Aprende com o seu canal** (opcional, `LEARN_FROM_STATS`): quando 8 ou mais vídeos têm estatísticas, o formato de cada vídeo novo é escolhido por amostragem de Thompson com base nas suas visualizações reais, e o `stats` mostra se a nota de retenção realmente prevê as suas visualizações (correlação de Spearman) e quais horários de publicação funcionaram melhor.

## Formatos

| Formato | O que você recebe |
|---|---|
| `facts` · `story` · `listicle` · `myth` · `quiz` · `explainer` · `motivational` · `news` | Um narrador, imagens para cada cena, legendas com destaque em cada palavra |
| `dialogue` | Duas pessoas conversando, cada uma com a sua própria voz; as legendas mostram o nome e a cor de quem está falando |
| `chat` | Uma história em mensagens de texto: as mensagens vão aparecendo na tela animada de um celular enquanto são lidas em voz alta, com indicador de digitação |
| `reddit` | Uma história em primeira pessoa contada como um post do Reddit: um card do post enquanto o título é lido, e depois a história com legendas |

```bash
purffle-shorts make --style chat --topic "uma babá recebe mensagens de um número desconhecido"
purffle-shorts make --style reddit --topic "um vizinho que vive pegando minha escada emprestada"
```

## Início rápido

Precisa do Python 3.10 ou mais recente. O ffmpeg é usado se estiver instalado; caso contrário, é usada uma cópia que já vem incluída.

```bash
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -e .
python -m purffle_shorts demo                        # um vídeo de exemplo, sem chaves
python -m purffle_shorts studio                      # o app web
```

Depois copie `.env.example` para `.env`, adicione uma chave de IA (ou rode o Ollama) e uma chave gratuita do Pexels ou do Pixabay, e rode `python -m purffle_shorts doctor` para verificar a configuração. `python -m purffle_shorts make --topic "why octopuses have three hearts" --no-upload` cria um vídeo; `python -m purffle_shorts auth` conecta o seu canal do YouTube; `python -m purffle_shorts run` liga o piloto automático.

## Corte vídeos longos em Shorts

```bash
pip install faster-whisper yt-dlp
purffle-shorts clip podcast.mp4 --count 3 --no-upload
purffle-shorts clip interview.mp4 --crop face        # segue o rosto de quem está falando (pip install opencv-python-headless)
```

O vídeo é transcrito, a IA escolhe os trechos que fazem sentido sozinhos e cada um vira um clipe vertical com legendas. Funciona como o Opus Clip, mas no seu próprio computador e sem cobrança por minuto. A transcrição usa `WHISPER_MODEL` (`auto` escolhe `large-v3-turbo` numa GPU NVIDIA e `small` na CPU) com detecção de voz, para que música e silêncio não virem palavras inventadas. Com `--crop face`, o rosto de quem está falando é localizado duas vezes por segundo e fica no enquadramento, que só muda quando a câmera muda de plano. Corte apenas vídeos que sejam seus ou que você tenha permissão para reutilizar.

## Use pelo Claude e por outros apps de IA (MCP)

```json
{
  "mcpServers": {
    "purffle-shorts": {
      "command": "purffle-shorts",
      "args": ["mcp"],
      "env": { "PURFFLE_HOME": "/path/to/your/purffle/folder" }
    }
  }
}
```

Depois é só pedir, por exemplo: "crie uma história em mensagens de texto de 30 segundos sobre uma caixa de som inteligente assombrada, em espanhol". Nenhum upload é feito a menos que você peça.

## Perguntas frequentes

**É grátis?** Sim. Tem licença MIT e roda no seu computador. As vozes, os modelos do Ollama e as APIs do Pexels e do Pixabay não custam nada; você só paga pelas APIs pagas que escolher usar, como OpenAI ou ElevenLabs.

**Dá para testar sem chave de API?** Sim: o comando `demo` renderiza um vídeo de exemplo sem nenhuma chave.

**Ele posta no TikTok ou no Instagram?** Ele só faz upload no YouTube. Cada vídeo é um MP4 padrão com imagem de capa e legendas, então você pode postar esse mesmo arquivo no TikTok e no Reels por conta própria (depois do upload no YouTube o MP4 é apagado, a menos que você defina `KEEP_VIDEOS=true`).

**Preciso de GPU?** Não. A renderização usa o ffmpeg na CPU. Se você tiver uma GPU NVIDIA, a transcrição do `clip` aproveita a placa.

**O upload automatizado é permitido?** Ele usa a YouTube Data API oficial com o seu próprio login do Google e marca a declaração de conteúdo sintético do YouTube. Revise seus vídeos e siga as políticas do YouTube.

## Licença

MIT. Feito por [Chaman Raj](https://github.com/Chamanrajragu) · [purffle.com](https://purffle.com/purffle-shorts/). Sem vínculo com YouTube, OpenAI, Anthropic, Google, Microsoft, Pexels, Pixabay, Pollinations ou Reddit.
