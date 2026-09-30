<div align="center">

# PurffleShorts — मुफ़्त AI YouTube Shorts जनरेटर और अपलोड ऑटोपायलट

[English](README.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · **हिन्दी** · [日本語](README.ja.md)

**YouTube Shorts, TikTok और Instagram Reels के लिए एक ओपन-सोर्स AI वीडियो जनरेटर। इसे कोई टॉपिक, वेब पेज, Reddit पोस्ट या लंबा पॉडकास्ट दीजिए, और यह पूरी तरह तैयार वर्टिकल वीडियो बना देता है (स्क्रिप्ट, वॉइसओवर, फुटेज, कैप्शन), फिर उन्हें YouTube पर अपलोड या शेड्यूल कर देता है।**

[![CI](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml/badge.svg)](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Chamanrajragu/purffle-shorts?style=social)](https://github.com/Chamanrajragu/purffle-shorts/stargazers)

<img src="docs/hero.gif" alt="PurffleShorts से बने तीन Shorts एक साथ चलते हुए: फ्लेमिंगो पर एक फैक्ट्स वीडियो जिसके कैप्शन में शब्द-दर-शब्द हाइलाइट होता है, ऑक्टोपस पर दो आवाज़ों वाला डायलॉग जिसमें बोलने वाले के नाम का टैग दिखता है, और एक एनिमेटेड फ़ोन स्क्रीन पर टेक्स्ट-मैसेज वाली कहानी" width="770">

<sub>असली आउटपुट, कोई एडिटिंग नहीं। मुफ़्त Microsoft न्यूरल आवाज़ें और AI इमेज। GIF में आवाज़ नहीं होती।</sub>

**बिना API key और बिना साइन-अप के आज़माएँ** ([uv](https://docs.astral.sh/uv/) चाहिए):

```bash
uvx --from git+https://github.com/Chamanrajragu/purffle-shorts purffle-shorts demo --style chat
```

**⭐ अगर PurffleShorts से आपका समय बचता है, तो एक स्टार दूसरे क्रिएटर्स को इसे ढूँढने में मदद करता है।**

</div>

> यह छोटा वर्ज़न है। पूरा डॉक्यूमेंटेशन (सारी सेटिंग्स, AI मॉडल, आवाज़ें, कैप्शन, पब्लिशिंग, कमांड लाइन, Studio, ट्रबलशूटिंग) [अंग्रेज़ी README](README.md) में है।

## PurffleShorts क्या है?

PurffleShorts फ़ेसलेस चैनलों के लिए एक YouTube Shorts ऑटोमेशन टूल है। एक बार चालू कर दीजिए, फिर यह चलता रहता है: हर बार नया टॉपिक, आपके चुने हुए AI मॉडल से लिखी गई स्क्रिप्ट जिसे फिर एक दूसरा AI पास रिव्यू करके और कसा हुआ बनाता है, नैचुरल AI वॉइसओवर, टॉपिक से जुड़ी फुटेज, हर बोले गए शब्द के साथ सिंक होने वाले कैप्शन, साफ़-सुथरा फ़ाइनल रेंडर, और फिर अपलोड या शेड्यूल्ड रिलीज़।

यह एक छोटा-सा स्टूडियो भी है: रेंडर करने से पहले स्क्रिप्ट की कोई भी लाइन एडिट करें, दो आवाज़ों वाले डायलॉग, टेक्स्ट-मैसेज कहानियाँ और Reddit-स्टाइल कहानियाँ बनाएँ, किसी आर्टिकल या Reddit पोस्ट को Short में बदलें, किसी पॉडकास्ट से Shorts क्लिप निकालें, और एक ही वीडियो कई भाषाओं में पब्लिश करें। यह आपके अपने कंप्यूटर पर चलता है (macOS, Windows, Linux या Docker), और 9:16 वाली MP4 फ़ाइलें TikTok और Instagram Reels के लिए भी काम करती हैं।

## फ़ीचर्स

- **कोई भी AI मॉडल:** OpenAI GPT, Anthropic Claude, Google Gemini, DeepSeek, Mistral, xAI Grok, Groq, OpenRouter, Together AI, Ollama और LM Studio (लोकल और मुफ़्त), या कोई भी OpenAI-compatible API, `LLM_FALLBACKS` में बैकअप प्रोवाइडर लिख दें, तो मुख्य प्रोवाइडर फ़ेल होने पर वे क्रम से आज़माए जाते हैं।
- **Script Doctor:** एक दूसरा AI पास हर स्क्रिप्ट को 0 से 100 तक स्कोर देता है कि वह दर्शकों को कितनी अच्छी तरह बाँधे रखती है, कमज़ोर हिस्सों की लिस्ट बनाता है और स्क्रिप्ट को दोबारा लिखता है।
- **75 भाषाओं में 322 मुफ़्त न्यूरल आवाज़ें**, शब्द-स्तर की टाइमिंग के साथ, कोई key नहीं चाहिए। डायलॉग और चैट कहानियों के लिए दो आवाज़ें।
- **हर वाक्य के लिए फुटेज:** Pexels या Pixabay से स्टॉक वीडियो (मुफ़्त keys), AI इमेज, या आपका अपना मीडिया फ़ोल्डर।
- **शब्द-दर-शब्द एनिमेटेड कैप्शन** छह स्टाइल में, लैटिन, इंडिक, अरबी, थाई और CJK लिपियों के लिए।
- **9:16, 16:9, 1:1 या 4:5** आउटपुट, ffmpeg से रेंडर होता है। GPU की ज़रूरत नहीं।
- **YouTube पर अपलोड** करता है या हर वीडियो को आपके अगले ख़ाली टाइम स्लॉट में शेड्यूल करता है, AI-कंटेंट डिस्क्लोज़र सेट करके।
- **एक वीडियो, कई भाषाएँ:** `--also-lang es,hi` अनुवादित कॉपियाँ बनाता है जिनमें वही फुटेज दोबारा इस्तेमाल होती है।
- **Studio वेब ऐप** आपके कंप्यूटर पर: ड्राफ़्ट करें, एडिट करें, रेंडर करें, प्रोग्रेस लाइव देखें, लाइब्रेरी ब्राउज़ करें।
- **MCP सर्वर:** Claude Desktop, Claude Code या Cursor से कहिए कि वीडियो बनाए, क्लिप करे या अपलोड करे।

## फ़ॉर्मैट

| फ़ॉर्मैट | आपको क्या मिलता है |
|---|---|
| `facts` · `story` · `listicle` · `myth` · `quiz` · `explainer` · `motivational` · `news` | एक नैरेटर, हर सीन के लिए फुटेज, शब्द-हाइलाइट वाले कैप्शन |
| `dialogue` | दो लोग बात करते हुए, हर एक की अपनी आवाज़; कैप्शन में बोलने वाले का नाम और रंग दिखता है |
| `chat` | टेक्स्ट-मैसेज वाली कहानी: मैसेज जैसे-जैसे पढ़े जाते हैं, एनिमेटेड फ़ोन स्क्रीन पर पॉप होते जाते हैं, साथ में टाइपिंग इंडिकेटर |
| `reddit` | Reddit पोस्ट की तरह सुनाई गई फ़र्स्ट-पर्सन कहानी: टाइटल पढ़े जाते वक़्त एक पोस्ट कार्ड, फिर कैप्शन के साथ कहानी |

```bash
purffle-shorts make --style chat --topic "एक बेबीसिटर को किसी अनजान नंबर से मैसेज आने लगते हैं"
purffle-shorts make --style reddit --topic "एक पड़ोसी जो बार-बार मेरी सीढ़ी उधार ले जाता है"
```

## क्विक स्टार्ट

Python 3.10 या उससे नया वर्ज़न चाहिए। ffmpeg इंस्टॉल हो तो वही इस्तेमाल होता है; वरना साथ में आने वाली (bundled) कॉपी इस्तेमाल होती है।

```bash
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -e .
python -m purffle_shorts demo                        # एक सैंपल वीडियो, बिना किसी key के
python -m purffle_shorts studio                      # वेब ऐप
```

फिर `.env.example` को `.env` में कॉपी करें, एक AI key जोड़ें (या Ollama चलाएँ) और एक मुफ़्त Pexels या Pixabay key डालें, और सेटअप जाँचने के लिए `python -m purffle_shorts doctor` चलाएँ। `python -m purffle_shorts make --topic "why octopuses have three hearts" --no-upload` एक वीडियो बनाता है; `python -m purffle_shorts auth` आपका YouTube चैनल कनेक्ट करता है; `python -m purffle_shorts run` ऑटोपायलट शुरू करता है।

## लंबे वीडियो से Shorts क्लिप बनाएँ

```bash
pip install faster-whisper yt-dlp
purffle-shorts clip podcast.mp4 --count 3 --no-upload
```

वीडियो को ट्रांसक्राइब किया जाता है, AI ऐसे पल चुनता है जो अपने-आप में पूरे हों, और हर पल कैप्शन वाली एक वर्टिकल क्लिप बन जाता है। यह Opus Clip की तरह काम करता है, लेकिन आपके अपने कंप्यूटर पर और बिना प्रति-मिनट फ़ीस के। सिर्फ़ वही वीडियो क्लिप करें जो आपके अपने हों या जिन्हें दोबारा इस्तेमाल करने की आपके पास इजाज़त हो।

## Claude और दूसरे AI ऐप्स से इस्तेमाल करें (MCP)

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

फिर कुछ ऐसा कहिए: "एक भूतिया स्मार्ट स्पीकर पर 30 सेकंड की टेक्स्ट स्टोरी बनाओ, स्पैनिश में"। जब तक आप ख़ुद न कहें, कुछ भी अपलोड नहीं होता।

## अक्सर पूछे जाने वाले सवाल

**क्या यह मुफ़्त है?** हाँ। यह MIT लाइसेंस के तहत है और आपके कंप्यूटर पर चलता है। आवाज़ें, Ollama मॉडल और Pexels व Pixabay API का कोई ख़र्च नहीं है; आप सिर्फ़ उन पेड API के पैसे देते हैं जिन्हें आप ख़ुद चुनते हैं, जैसे OpenAI या ElevenLabs।

**क्या इसे बिना API key के आज़मा सकते हैं?** हाँ: `demo` कमांड बिना किसी key के एक सैंपल वीडियो रेंडर करता है।

**क्या यह TikTok या Instagram पर पोस्ट कर सकता है?** यह सिर्फ़ YouTube पर अपलोड करता है। हर वीडियो कवर इमेज और सबटाइटल के साथ एक स्टैंडर्ड MP4 होता है, इसलिए आप वही फ़ाइल TikTok और Reels पर ख़ुद पोस्ट कर सकते हैं (YouTube पर अपलोड के बाद MP4 डिलीट हो जाती है, जब तक आप `KEEP_VIDEOS=true` न करें)।

**क्या GPU चाहिए?** नहीं। रेंडरिंग CPU पर ffmpeg से होती है।

**क्या ऑटोमैटिक अपलोड करने की इजाज़त है?** यह आपके अपने Google साइन-इन के साथ ऑफ़िशियल YouTube Data API इस्तेमाल करता है और YouTube का सिंथेटिक-कंटेंट डिस्क्लोज़र सेट करता है। अपने वीडियो रिव्यू करें और YouTube की पॉलिसी का पालन करें।

## लाइसेंस

MIT। [Chaman Raj](https://github.com/Chamanrajragu) ने बनाया · [purffle.com](https://purffle.com/purffle-shorts/)। इसका YouTube, OpenAI, Anthropic, Google, Microsoft, Pexels, Pixabay, Pollinations या Reddit से कोई संबंध नहीं है।
