# KoeGuide 🏛️🎤

Municipal FAQ Voice AI Agent for foreign residents in Japan.

**KoeGuide** (声ガイド) connects residents to a friendly AI concierge named **Mado** (窓) that answers questions about Japanese municipal services — move-in registration, health insurance, garbage collection, and more — all through natural voice conversation.

Built with [Vocal Bridge](https://vocalbridgeai.com) + LiveKit WebRTC.

## Features

- **Voice AI Concierge** — Ask questions by voice in Japanese or English; Mado responds with clear, concise answers
- **Interactive Info Cards** — Real-time UI cards with details (location, hours, fees, required documents) synced via Client Actions
- **Municipality Garbage Scraping** — Input any municipality's garbage collection page URL → auto-scrape → AI answers based on real data
- **Admin Panel** — Add/remove municipalities, trigger scraping, deploy updated prompts to the agent
- **i18n** — UI toggles between English and Japanese
- **STT Language Selector** — Switch speech recognition language (Japanese / English / Multi) from the header

## Architecture

```
Browser (LiveKit WebRTC) ←→ Vocal Bridge (STT → Claude → TTS) ←→ Client Actions (data channel)
         ↕
   Flask Backend (server.py)
     ├── /api/voice-token    → Vocal Bridge token API
     ├── /api/municipalities → CRUD + scraping
     ├── /api/garbage-info   → API Tool endpoint
     ├── /api/stt-language   → STT language config
     └── /api/deploy-prompt  → Prompt rebuild + vb prompt set
```

### Scraping Pipeline

```
Admin inputs URL → scraper.py (requests + BeautifulSoup)
  → Extract text from main page + sub-pages
  → Optional: Claude API structured extraction
  → Cache to municipality_data/<id>.json
  → prompt_builder.py embeds data into agent prompt
  → vb prompt set deploys to Vocal Bridge
```

## Setup

### Prerequisites

- Python 3.10+
- [Vocal Bridge CLI](https://vocalbridgeai.com) (`pip install vocal-bridge`)
- macOS (uses Keychain for API key storage)

### Install

```bash
pip install -r requirements.txt
```

### API Key

Store your Vocal Bridge API key in macOS Keychain:

```bash
security add-generic-password -s "vocal-bridge" -a "api-key" -w
# (paste your key when prompted)
```

Then authenticate the CLI:

```bash
vb auth login
```

### Run

```bash
python server.py
```

- Main app: http://localhost:5555
- Admin panel: http://localhost:5555/admin

## File Structure

```
├── server.py            # Flask backend
├── index.html           # Main voice UI
├── style.css            # Styles (navy theme)
├── app.js               # LiveKit client + i18n + Client Actions
├── admin.html           # Municipality admin panel
├── scraper.py           # Web scraper (BS4 + optional Claude API)
├── prompt_builder.py    # Prompt assembly + deployment
├── faq-data.json        # 20 static FAQ entries
├── municipalities.json  # Registered municipalities
├── municipality_data/   # Scraped data cache
├── api-tools.json       # Vocal Bridge API Tool definition
├── prompt_base.txt      # Base agent prompt
└── prompt-addition.txt  # Client Actions instructions
```

## Tech Stack

- **Voice**: Vocal Bridge SDK + LiveKit WebRTC
- **LLM**: Claude (via Vocal Bridge)
- **STT**: AssemblyAI Universal Streaming
- **TTS**: ElevenLabs Multilingual v2
- **Backend**: Flask
- **Scraping**: BeautifulSoup4 + requests

## License

MIT
