<div align="center">

# PurffleShorts — Generador gratuito de YouTube Shorts con IA, videos sin rostro y alternativa a Opus Clip

[English](README.md) · [简体中文](README.zh-CN.md) · **Español** · [Português](README.pt-BR.md) · [हिन्दी](README.hi.md) · [日本語](README.ja.md)

**Un generador de video con IA de código abierto para YouTube Shorts, TikTok e Instagram Reels. Dale un tema, una página web, un post de Reddit o un podcast largo y creará videos verticales terminados (guion, locución, material visual, subtítulos) que luego subirá o programará en YouTube, TikTok e Instagram.**

[![CI](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml/badge.svg)](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Chamanrajragu/purffle-shorts/blob/main/notebooks/PurffleShorts.ipynb)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Chamanrajragu/purffle-shorts?style=social)](https://github.com/Chamanrajragu/purffle-shorts/stargazers)

<img src="docs/hero.gif" alt="Tres Shorts creados por PurffleShorts reproduciéndose uno al lado del otro: un video de datos curiosos sobre flamencos con subtítulos que resaltan cada palabra, un diálogo a dos voces sobre pulpos con etiquetas de nombre para cada hablante y una historia de mensajes de texto en la pantalla animada de un teléfono" width="770">

<sub>Resultado real, sin editar. Voces neuronales gratuitas de Microsoft e imágenes generadas con IA. Los GIF no tienen sonido.</sub>

**Pruébalo sin claves de API y sin registrarte** (necesitas [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from git+https://github.com/Chamanrajragu/purffle-shorts purffle-shorts demo --style chat
```

…o **[ábrelo en Google Colab](https://colab.research.google.com/github/Chamanrajragu/purffle-shorts/blob/main/notebooks/PurffleShorts.ipynb)** y crea videos en tu navegador, sin instalar nada.

**⭐ Si PurffleShorts te ahorra tiempo, una estrella ayuda a que otros creadores lo encuentren.**

</div>

> Esta es una versión breve. La documentación completa (todos los ajustes, modelos de IA, voces, subtítulos, publicación, línea de comandos, Studio y solución de problemas) está en el [README en inglés](README.md).

## ¿Qué es PurffleShorts?

PurffleShorts es una herramienta de automatización de YouTube Shorts para canales sin rostro. Lo inicias y no se detiene: un tema nuevo, un guion escrito por el modelo de IA que elijas y luego revisado y afinado por una segunda pasada de IA, una locución natural con IA, material visual relevante, subtítulos sincronizados con cada palabra hablada, un renderizado pulido y una subida o una publicación programada.

También es un pequeño estudio: puedes editar cualquier línea del guion antes de renderizar, crear diálogos a dos voces, historias de mensajes de texto e historias al estilo Reddit, convertir un artículo o un post de Reddit en un Short, extraer Shorts de un podcast y publicar el mismo video en varios idiomas. Funciona en tu propio equipo (macOS, Windows, Linux o Docker), y los archivos MP4 en 9:16 también sirven para TikTok e Instagram Reels.

## Características

- **Cualquier modelo de IA:** OpenAI GPT, Anthropic Claude, Google Gemini, DeepSeek, Mistral, xAI Grok, Groq, OpenRouter, Together AI, Ollama y LM Studio (locales y gratuitos), o cualquier API compatible con OpenAI. Si defines proveedores de respaldo en `LLM_FALLBACKS`, se prueban en orden cuando falla el principal. En los proveedores que lo admiten (OpenAI, Gemini, OpenRouter, Ollama, LM Studio, Claude), las respuestas siguen un esquema JSON estricto.
- **Script Doctor:** una segunda pasada de IA califica cada guion en seis aspectos (gancho, curiosidad, ritmo, concreción, desenlace y precisión), enumera sus puntos débiles y lo reescribe. La nueva versión se vuelve a calificar y solo se conserva si puntúa al menos igual, así que la puntuación de retención (de 0 a 100) siempre corresponde al guion que recibes. Unas comprobaciones automáticas (un gancho demasiado largo, muletillas, ninguna llamada a la acción, ningún dato concreto) alimentan la revisión.
- **322 voces neuronales gratuitas en 75 idiomas** con sincronización a nivel de palabra, sin necesidad de clave. Dos voces para diálogos e historias de chat.
- **Material visual para cada frase:** videos de stock de Pexels o Pixabay (claves gratuitas), imágenes generadas con IA o tu propia carpeta de medios. Cada candidato se puntúa según lo bien que su propia descripción encaja con la escena.
- **Ritmo rápido:** las escenas de más de 4,5 s se dividen en varias tomas con material distinto, y cada corte cae en una pausa natural entre palabras (`MAX_SHOT_SECONDS`).
- **Videos de fondo (gameplay):** con `--background parkour.mp4` (o `BACKGROUND_VIDEO`), un tramo continuo de tu video de Minecraft parkour, Subway Surfers o similar se reproduce bajo toda la historia, a pantalla completa o en **pantalla dividida** (`--layout split`) con el material de la escena arriba. Usa solo videos que tengas derecho a reutilizar.
- **Subtítulos animados palabra por palabra** en seis estilos, para escritura latina, índica, árabe, tailandesa y CJK. Con voces que no dan la marca de tiempo de cada palabra, el final de cada frase se fija en las pausas reales del audio, así que los subtítulos siguen sincronizados.
- **Audio con calidad de emisión:** una limpieza suave de la voz (corte de graves, de-esser, compresión) y una normalización de sonoridad en dos pasadas que mide la mezcla y aplica una ganancia constante: −14 LUFS sin efecto de bombeo.
- **Edición pensada para la retención:** las palabras clave que marca la IA y todos los números aparecen en otro color, un emoji por escena aparece sobre los subtítulos, y hay efectos de sonido creados por código (un whoosh en cada cambio de escena, un pop con cada mensaje y un golpe bajo el gancho) mezclados 11 dB por debajo de la voz.
- **Portada:** el fotograma más nítido y mejor expuesto de los primeros segundos, nunca uno a mitad de una transición.
- Salida en **9:16, 16:9, 1:1 o 4:5**, renderizada con ffmpeg. No necesitas GPU.
- **Publica también en TikTok e Instagram Reels** (`PUBLISH_TO=youtube,tiktok,instagram`), con un texto adaptado a cada red.
- **Sube a YouTube** o programa cada video en tu siguiente franja horaria libre, con la declaración de contenido generado con IA ya activada.
- **Un video, muchos idiomas:** `--also-lang es,hi` crea copias traducidas que reutilizan el mismo material visual.
- **App web Studio** en tu equipo: redacta, edita, renderiza y explora la biblioteca. El progreso llega al instante, con el porcentaje y el tiempo restante calculados a partir de tu propio equipo, y el botón **Cancel** detiene un trabajo en curso. Si lo ejecutas en un servidor, `STUDIO_PASSWORD` lo protege con contraseña.
- **Google Colab, API REST y Docker:** un [cuaderno de Colab](https://colab.research.google.com/github/Chamanrajragu/purffle-shorts/blob/main/notebooks/PurffleShorts.ipynb) para usarlo en el navegador, una API REST documentada ([docs/api.md](docs/api.md)) con una receta para n8n, y `docker compose` para servidores.
- Una línea de progreso en vivo en la terminal y una caché de voz: al volver a renderizar un guion editado, solo se locutan las líneas que cambiaron.
- **Servidor MCP:** pídele a Claude Desktop, Claude Code o Cursor que cree videos, extraiga clips o suba videos.
- **Aprende de tu canal** (opcional, `LEARN_FROM_STATS`): cuando 8 o más videos tienen estadísticas, el formato de cada video nuevo se elige por muestreo de Thompson a partir de tus vistas reales, y `stats` te dice si la puntuación de retención predice de verdad tus vistas (correlación de Spearman) y qué horas de publicación funcionaron mejor.
- **SEO integrado:** antes de escribir, consulta lo que la gente busca de verdad en YouTube sobre el tema y usa esas frases en el título, la descripción y las etiquetas. También puede elegir temas a partir de esas búsquedas (`TOPIC_SOURCES=search`), traducir el título y la descripción para espectadores de otros idiomas (`LOCALIZE_METADATA=en,pt`) y subir los subtítulos exactos (`UPLOAD_CAPTIONS`).

## Formatos

| Formato | Qué obtienes |
|---|---|
| `facts` · `story` · `listicle` · `myth` · `quiz` · `explainer` · `motivational` · `news` | Un narrador, material visual para cada escena, subtítulos que resaltan cada palabra |
| `dialogue` | Dos personas conversando, cada una con su propia voz; los subtítulos muestran el nombre y el color de quien habla |
| `chat` | Una historia de mensajes de texto: los mensajes aparecen en una pantalla de teléfono animada a medida que se leen en voz alta, con el indicador de "escribiendo..." |
| `reddit` | Una historia en primera persona contada como un post de Reddit: una tarjeta del post mientras se lee el título, y luego la historia con subtítulos |

```bash
purffle-shorts make --style chat --topic "una niñera recibe mensajes de un número desconocido"
purffle-shorts make --style reddit --topic "un vecino que no para de pedirme prestada la escalera"
```

## Inicio rápido

Requiere Python 3.10 o superior. Usa ffmpeg si lo tienes instalado; si no, usa una copia incluida.

```bash
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -e .
python -m purffle_shorts demo                        # un video de ejemplo, sin claves
python -m purffle_shorts studio                      # la app web
```

Después copia `.env.example` a `.env`, añade una clave de IA (o ejecuta Ollama) y una clave gratuita de Pexels o Pixabay, y ejecuta `python -m purffle_shorts doctor` para comprobar la configuración. `python -m purffle_shorts make --topic "why octopuses have three hearts" --no-upload` crea un video; `python -m purffle_shorts auth` conecta tu canal de YouTube; `python -m purffle_shorts run` inicia el piloto automático.

## Convierte videos largos en Shorts

```bash
pip install faster-whisper yt-dlp
purffle-shorts clip podcast.mp4 --count 3 --no-upload
purffle-shorts clip interview.mp4 --crop face        # sigue el rostro de quien habla (pip install opencv-python-headless)
purffle-shorts clip episode.mp4 --prompt "los momentos más divertidos"   # solo los momentos que encajan con tu indicación
```

El video se transcribe, la IA elige los momentos que funcionan por sí solos y cada uno se convierte en un clip vertical con subtítulos. Funciona como Opus Clip, pero en tu propio equipo y sin tarifas por minuto. La transcripción usa `WHISPER_MODEL` (`auto` elige `large-v3-turbo` en una GPU NVIDIA y `small` en la CPU) con detección de voz, para que la música y los silencios no se conviertan en palabras inventadas. Con `--crop face`, el rostro de quien habla se busca dos veces por segundo y se mantiene en el encuadre, que solo cambia cuando cambia el plano. Extrae clips solo de videos que sean tuyos o que tengas permiso para reutilizar.

Cada clip se edita como lo haría un editor. Los **cortes de salto** acortan las pausas largas y quitan titubeos como «um» y «eh»: imagen y sonido se cortan en el mismo fotograma, así que los labios siguen sincronizados. Un **zoom de impacto** cambia el encuadre entre frases. Cada clip trae una **puntuación de viralidad** con su motivo. Se desactivan con `--no-jump-cuts` y `--no-zoom`.

## Úsalo desde Claude y otras apps de IA (MCP)

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

Luego pide, por ejemplo: "crea una historia de texto de 30 segundos sobre un altavoz inteligente embrujado, en español". No se sube nada a menos que lo pidas.

## Preguntas frecuentes

**¿Es gratis?** Sí. Tiene licencia MIT y se ejecuta en tu equipo. Las voces, los modelos de Ollama y las API de Pexels y Pixabay no cuestan nada; solo pagas por las API de pago que elijas, como OpenAI o ElevenLabs.

**¿Puedo probarlo sin una clave de API?** Sí: el comando `demo` renderiza un video de ejemplo sin claves.

**¿Puede publicar en TikTok o Instagram?** Sí: `PUBLISH_TO=youtube,tiktok,instagram`. TikTok se publica a través de [Upload-Post](https://www.upload-post.com) (`UPLOAD_POST_API_KEY`, `UPLOAD_POST_USER`; TikTok requiere un plan de pago), porque la API propia de TikTok solo deja publicar videos públicos a apps auditadas. Instagram puede usar su API oficial gratuita (`INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`) o Upload-Post. Cada red recibe su propio texto y la misma franja horaria, y `upload --id N` reintenta solo lo que falló. Esta integración sigue la API publicada de cada servicio, pero aún no se ha probado con cuentas reales.

**¿Necesito una GPU?** No. El renderizado usa ffmpeg en la CPU. Si tienes una GPU NVIDIA, la transcripción de `clip` la aprovecha.

**¿Está permitido subir videos de forma automatizada?** Usa la YouTube Data API oficial, iniciando sesión con tu propia cuenta de Google, y activa la declaración de contenido sintético de YouTube. Revisa tus videos y respeta las políticas de YouTube.

## Licencia

MIT. Creado por [Chaman Raj](https://github.com/Chamanrajragu) · [purffle.com](https://purffle.com/purffle-shorts/). No está afiliado a YouTube, OpenAI, Anthropic, Google, Microsoft, Pexels, Pixabay, Pollinations ni Reddit.
