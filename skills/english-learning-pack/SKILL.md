---
name: english-learning-pack
description: "Use when generating the daily International Tech/Finance English learning pack (國際科技財經英文學習包) for Telegram — fetches news, writes summary/vocab, and creates TTS audio."
version: 1.0.0
author: meson
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [english, learning, cron, telegram, tts, news, education]
---

# English Learning Pack Generator

## When to use

Load this skill when the user or a cron job asks to:

- 產生「國際科技財經英文學習包」
- Run the daily 7:00 English learning pack
- Generate tech/finance news summary with vocabulary and TTS for Telegram

## Tool command

Run the bundled Python tool (do **not** reimplement the workflow manually):

```bash
python3 ~/.hermes/scripts/generate_english_learning_pack.py --send-telegram
```

Options:

| Flag | Effect |
|------|--------|
| `--send-telegram` | Send 3 threaded Telegram messages + all audio files |
| `--json-only` | Print machine-readable JSON to stdout |

Output artifacts land in `~/.hermes/cron/output/english_learning_pack/YYYY-MM-DD/`.

## What the tool does

1. Fetches headlines from Google News (tech/finance) and Hacker News
2. Uses the configured LLM (Ollama) to pick the best article and generate:
   - 300–350 word English summary
   - Traditional Chinese translation
   - 5–8 vocabulary items (IPA, 中文意思, example sentence)
   - Grammar focus + learning tips
3. Generates TTS (Edge TTS, slower pace for learners):
   - `summary_YYYY-MM-DD.mp3` — rate **-25%**
   - `word_NN_<word>.mp3` — same rate as summary, word then pause then example
4. Formats **3 Telegram MarkdownV2 messages** (message 2 replies to 1, message 3 replies to 2)

## Cron integration（推薦：`--no-agent` 省 token）

每天 7:00 全自動、不走 Agent，每次約 **5,000–7,000 token**（僅 Ollama LLM）：

```bash
hermes cron edit 553949ef05af \
  --no-agent \
  --script english_learning_pack_cron.py
```

`english_learning_pack_cron.py` 會自動呼叫主腳本的 `--cron` 模式。

行為：
- 成功：發送 3 則 Telegram + 音檔，**stdout 留空**（不重複發訊息）
- 失敗：stdout 輸出錯誤，cron 會發警报到 Telegram

手動測試：

```bash
python3 ~/.hermes/scripts/generate_english_learning_pack.py --send-telegram
```

## Completion criteria

- `pack.json` exists under today's output directory
- 5–8 vocabulary audio files exist in `~/.hermes/audio_cache/`
- `summary_*.mp3` exists
- If `--send-telegram`: no API errors; 3 messages delivered

## Dependencies

- LLM: `config.yaml` → `model.base_url` / `model.default` (Ollama)
- TTS: Edge TTS (default) or Hermes `text_to_speech` backend
- Telegram: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_HOME_CHANNEL` in `~/.hermes/.env`
- Optional TTS tuning: `ENGLISH_PACK_SUMMARY_RATE` (default `-25%`, applies to summary and vocab)
