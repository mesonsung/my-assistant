#!/usr/bin/env python3
"""
generate_english_learning_pack.py

Hermes Agent tool: 國際科技財經英文學習包產生器。

用法:
  python3 ~/.hermes/scripts/generate_english_learning_pack.py
  python3 ~/.hermes/scripts/generate_english_learning_pack.py --send-telegram
  python3 ~/.hermes/scripts/generate_english_learning_pack.py --json-only

Cron 範例:
  hermes cron edit <job-id> --script generate_english_learning_pack.py
  # 或將 cron prompt 改為簡短指令，由 agent 呼叫此腳本
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
CONFIG_PATH = HERMES_HOME / "config.yaml"
ENV_PATH = HERMES_HOME / ".env"
OUTPUT_ROOT = HERMES_HOME / "cron" / "output" / "english_learning_pack"
AUDIO_DIR = HERMES_HOME / "audio_cache"

# TTS 語速（Edge TTS rate 格式，負值越慢）
SUMMARY_TTS_RATE = os.environ.get("ENGLISH_PACK_SUMMARY_RATE", "-25%")
TTS_VOICE = os.environ.get("ENGLISH_PACK_TTS_VOICE", "en-US-GuyNeural")

USER_AGENT = (
    "Mozilla/5.0 (compatible; HermesEnglishPack/1.0; +https://hermes-agent.nousresearch.com)"
)

NEWS_SOURCES = [
    ("Google News Tech", "https://news.google.com/rss/search?q=technology&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Finance", "https://news.google.com/rss/search?q=finance&hl=en-US&gl=US&ceid=US:en"),
    ("Hacker News", "hn"),
]


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: str
    snippet: str = ""


@dataclass
class VocabItem:
    word: str
    ipa: str
    meaning_zh: str
    example: str
    audio_path: str = ""


@dataclass
class LearningPack:
    title: str
    source: str
    date: str
    url: str
    summary_en: str
    summary_zh: str
    vocabulary: list[VocabItem] = field(default_factory=list)
    grammar_focus: list[str] = field(default_factory=list)
    learning_tips: list[str] = field(default_factory=list)
    summary_audio: str = ""
    output_dir: str = ""


def ensure_hermes_venv() -> None:
    """Re-exec with Hermes venv Python so edge_tts / tools.* are available."""
    venv_py = Path("/opt/hermes/.venv/bin/python")
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), *sys.argv])


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_yaml_model_config() -> tuple[str, str]:
    """Resolve LLM endpoint for this tool (defaults to local Ollama)."""
    base_url = os.environ.get("ENGLISH_PACK_LLM_BASE_URL", "http://host.docker.internal:11434/v1")
    model = os.environ.get("ENGLISH_PACK_LLM_MODEL", "gemma4:cloud")
    if not CONFIG_PATH.exists():
        return base_url.rstrip("/"), model
    try:
        import yaml  # type: ignore

        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        m = cfg.get("model") or {}
        provider = m.get("provider", "")
        cfg_base = (m.get("base_url") or "").strip()
        cfg_model = (m.get("default") or "").strip()
        # Use Hermes custom/Ollama endpoint when configured
        if provider == "custom" and cfg_base:
            base_url = cfg_base
            if cfg_model:
                model = cfg_model
        elif cfg_base and "11434" in cfg_base:
            base_url = cfg_base
            if cfg_model:
                model = cfg_model
    except Exception:
        pass
    return base_url.rstrip("/"), model


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_rss(xml_bytes: bytes, source_name: str, limit: int = 8) -> list[NewsItem]:
    items: list[NewsItem] = []
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return items
    for item in channel.findall("item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        desc = re.sub(r"\s+", " ", unescape(desc)).strip()
        if title and link:
            items.append(NewsItem(title=title, url=link, source=source_name, published=pub, snippet=desc))
    return items


def fetch_hn_top(limit: int = 8) -> list[NewsItem]:
    ids = json.loads(http_get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=20))
    items: list[NewsItem] = []
    for story_id in ids[:limit]:
        story = json.loads(
            http_get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=20)
        )
        if not story or story.get("type") != "story":
            continue
        title = (story.get("title") or "").strip()
        url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        ts = story.get("time")
        published = ""
        if ts:
            published = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        items.append(NewsItem(title=title, url=url, source="Hacker News", published=published))
    return items


def fetch_all_headlines(limit_per_source: int = 8) -> list[NewsItem]:
    headlines: list[NewsItem] = []
    for name, url in NEWS_SOURCES:
        try:
            if url == "hn":
                headlines.extend(fetch_hn_top(limit_per_source))
            else:
                headlines.extend(parse_rss(http_get(url), name, limit_per_source))
        except Exception as exc:
            print(f"[warn] failed to fetch {name}: {exc}", file=sys.stderr)
    return headlines[: max(10, limit_per_source)]


def fetch_article_text(url: str, max_chars: int = 12000) -> str:
    try:
        html = http_get(url, timeout=25).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:max_chars]


def ollama_chat(base_url: str, model: str, messages: list[dict[str, str]], temperature: float = 0.4) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def extract_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def select_best_article(headlines: list[NewsItem], base_url: str, model: str) -> NewsItem:
    listing = []
    for i, h in enumerate(headlines[:10], 1):
        listing.append(f"{i}. [{h.source}] {h.title}\n   URL: {h.url}\n   Snippet: {h.snippet[:200]}")
    prompt = textwrap.dedent(
        f"""
        You are an expert English teacher. From the following up to 10 tech/finance headlines,
        pick exactly ONE article index (1-10) with the highest learning value for B2-C1 learners
        (depth, professional vocabulary, clear thesis). Reply ONLY with JSON:
        {{"index": <int>, "reason": "<short reason in English>"}}

        Headlines:
        {chr(10).join(listing)}
        """
    ).strip()
    raw = ollama_chat(base_url, model, [{"role": "user", "content": prompt}], temperature=0.2)
    data = extract_json_block(raw)
    idx = int(data["index"]) - 1
    idx = max(0, min(idx, len(headlines[:10]) - 1))
    return headlines[idx]


def generate_pack_content(
    article: NewsItem, article_text: str, base_url: str, model: str
) -> dict[str, Any]:
    today = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    prompt = textwrap.dedent(
        f"""
        You are a strict, reliable English learning pack generator.

        Article metadata:
        - Title: {article.title}
        - Source: {article.source}
        - URL: {article.url}
        - Date: {today}

        Article text (may be truncated):
        {article_text[:9000]}

        Produce JSON ONLY with this exact schema:
        {{
          "summary_en": "<300-350 English words, fluent, high information density>",
          "summary_zh": "<natural Traditional Chinese translation of the summary>",
          "vocabulary": [
            {{"word": "...", "ipa": "/.../", "meaning_zh": "...", "example": "..."}}
          ],
          "grammar_focus": ["...", "...", "..."],
          "learning_tips": ["...", "..."]
        }}

        Rules:
        - vocabulary: exactly 5 to 8 advanced/professional words from the summary
        - grammar_focus: 3-4 bullet points in Traditional Chinese
        - learning_tips: 2-3 bullet points in Traditional Chinese
        - summary_en must be 300-350 words (count carefully)
        - example sentences must naturally include the vocabulary word
        """
    ).strip()
    raw = ollama_chat(base_url, model, [{"role": "user", "content": prompt}], temperature=0.5)
    return extract_json_block(raw)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))


def slugify(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", word.lower()).strip("_")[:40] or "word"


def synthesize_edge_tts(text: str, output_path: Path, rate: str = "+0%") -> None:
    import edge_tts  # type: ignore

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, TTS_VOICE, rate=rate)
        await communicate.save(str(output_path))

    asyncio.run(_run())


def synthesize_summary_tts(text: str, output_path: Path) -> None:
    # 摘要朗讀：固定較慢語速，方便學習者聽清
    synthesize_edge_tts(text, output_path, rate=SUMMARY_TTS_RATE)


def synthesize_word_tts(word: str, example: str, output_path: Path) -> None:
    # 單字 + 停頓 + 例句；語速與摘要相同
    spoken = f"{word}. ... ... ... {example}"
    synthesize_edge_tts(spoken, output_path, rate=SUMMARY_TTS_RATE)


def escape_telegram_md_v2(text: str) -> str:
    special = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", text)


def build_messages(pack: LearningPack) -> list[str]:
    vocab_lines = []
    for i, v in enumerate(pack.vocabulary, 1):
        audio_name = Path(v.audio_path).name if v.audio_path else f"word_{i:02d}_{slugify(v.word)}.mp3"
        block = (
            f"• {escape_telegram_md_v2(v.word)} {escape_telegram_md_v2(v.ipa)}\n"
            f"  中文意思：{escape_telegram_md_v2(v.meaning_zh)}\n"
            f"  例句：{escape_telegram_md_v2(v.example)}\n"
            f"  🔊 {escape_telegram_md_v2(audio_name)}"
        )
        vocab_lines.append(block)

    grammar = "\n".join(f"\\- {escape_telegram_md_v2(g)}" for g in pack.grammar_focus)
    tips = "\n".join(f"\\- {escape_telegram_md_v2(t)}" for t in pack.learning_tips)

    msg1 = (
        f"📌 今日國際科技財經英文學習包\n"
        f"📰 {escape_telegram_md_v2(pack.title)}\n"
        f"來源：{escape_telegram_md_v2(pack.source)} \\| 日期：{escape_telegram_md_v2(pack.date)}\n\n"
        f"🗣️ 英文重點摘要 \\(300\\-350字\\)\n"
        f"{escape_telegram_md_v2(pack.summary_en)}"
    )
    msg2 = (
        f"🇹🇼 中文翻譯\n"
        f"{escape_telegram_md_v2(pack.summary_zh)}\n\n"
        f"🔊 摘要朗讀\n"
        f"{escape_telegram_md_v2(Path(pack.summary_audio).name)}"
    )
    msg3 = (
        f"🔑 重點生字 \\({len(pack.vocabulary)}個\\)\n"
        + "\n\n".join(vocab_lines)
        + f"\n\n📝 Grammar Focus\n{grammar}\n\n💡 Learning Tips\n{tips}"
    )
    return [msg1, msg2, msg3]


def deliver_telegram_pack(
    token: str,
    chat_id: str,
    messages: list[str],
    summary_audio: str,
    word_audios: list[str],
) -> None:
    """Send 3 MarkdownV2 messages, then audio (summary → msg2, words → msg3)."""

    def api(method: str, data: dict[str, Any], files: dict[str, tuple[str, bytes, str]] | None = None) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{token}/{method}"
        if files:
            boundary = "----HermesBoundary"
            body = b""
            for key, val in data.items():
                body += f"--{boundary}\r\n".encode()
                body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                body += f"{val}\r\n".encode()
            for key, (filename, content, mime) in files.items():
                body += f"--{boundary}\r\n".encode()
                body += (
                    f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                ).encode()
                body += f"Content-Type: {mime}\r\n\r\n".encode()
                body += content + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
        else:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=encoded,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

    msg_ids: list[int] = []
    for i, text in enumerate(messages):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": "true",
        }
        if i > 0 and msg_ids:
            payload["reply_to_message_id"] = msg_ids[-1]
        result = api("sendMessage", payload)
        if not result.get("ok"):
            raise RuntimeError(f"sendMessage failed: {result}")
        msg_ids.append(result["result"]["message_id"])

    def send_audio(path: str, reply_to: int | None) -> None:
        if not path or not Path(path).exists():
            return
        payload: dict[str, Any] = {"chat_id": chat_id}
        if reply_to is not None:
            payload["reply_to_message_id"] = str(reply_to)
        content = Path(path).read_bytes()
        result = api(
            "sendAudio",
            payload,
            files={"audio": (Path(path).name, content, "audio/mpeg")},
        )
        if not result.get("ok"):
            raise RuntimeError(f"sendAudio failed for {path}: {result}")

    reply_summary = msg_ids[1] if len(msg_ids) > 1 else None
    reply_vocab = msg_ids[2] if len(msg_ids) > 2 else None
    send_audio(summary_audio, reply_summary)
    for path in word_audios:
        send_audio(path, reply_vocab)


def send_telegram_messages(
    token: str,
    chat_id: str,
    messages: list[str],
    audio_files: list[tuple[str, str | None]],
) -> None:
    """Legacy wrapper — prefer deliver_telegram_pack."""
    summary = audio_files[0][0] if audio_files else ""
    words = [p for p, _ in audio_files[1:]]
    deliver_telegram_pack(token, chat_id, messages, summary, words)


def generate_pack(send_telegram: bool = False, json_only: bool = False, quiet: bool = False) -> dict[str, Any]:
    base_url, model = load_yaml_model_config()
    env = {**load_dotenv(ENV_PATH), **os.environ}

    headlines = fetch_all_headlines()
    if not headlines:
        raise RuntimeError("No headlines fetched from any source")

    chosen = select_best_article(headlines, base_url, model)
    article_text = fetch_article_text(chosen.url)
    if not article_text:
        article_text = chosen.snippet or chosen.title

    content = generate_pack_content(chosen, article_text, base_url, model)
    wc = word_count(content["summary_en"])
    if wc < 280 or wc > 380:
        print(f"[warn] summary word count {wc}, expected 300-350", file=sys.stderr)

    today = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    out_dir = OUTPUT_ROOT / today
    out_dir.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    pack = LearningPack(
        title=chosen.title,
        source=chosen.source,
        date=today,
        url=chosen.url,
        summary_en=content["summary_en"].strip(),
        summary_zh=content["summary_zh"].strip(),
        grammar_focus=[str(x) for x in content.get("grammar_focus", [])][:4],
        learning_tips=[str(x) for x in content.get("learning_tips", [])][:3],
        output_dir=str(out_dir),
    )

    vocab_raw = content.get("vocabulary") or []
    if not (5 <= len(vocab_raw) <= 8):
        print(f"[warn] vocabulary count {len(vocab_raw)}, expected 5-8", file=sys.stderr)

    for i, item in enumerate(vocab_raw[:8], 1):
        word = str(item.get("word", "")).strip()
        if not word:
            continue
        audio_path = AUDIO_DIR / f"word_{i:02d}_{slugify(word)}.mp3"
        synthesize_word_tts(word, str(item.get("example", "")).strip(), audio_path)
        pack.vocabulary.append(
            VocabItem(
                word=word,
                ipa=str(item.get("ipa", "")).strip(),
                meaning_zh=str(item.get("meaning_zh", "")).strip(),
                example=str(item.get("example", "")).strip(),
                audio_path=str(audio_path),
            )
        )

    summary_audio = AUDIO_DIR / f"summary_{today}.mp3"
    synthesize_summary_tts(pack.summary_en, summary_audio)
    pack.summary_audio = str(summary_audio)

    messages = build_messages(pack)
    (out_dir / "messages.json").write_text(
        json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "pack.json").write_text(
        json.dumps(
            {
                "title": pack.title,
                "source": pack.source,
                "date": pack.date,
                "url": pack.url,
                "summary_en": pack.summary_en,
                "summary_zh": pack.summary_zh,
                "vocabulary": [v.__dict__ for v in pack.vocabulary],
                "grammar_focus": pack.grammar_focus,
                "learning_tips": pack.learning_tips,
                "summary_audio": pack.summary_audio,
                "messages": messages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = {
        "success": True,
        "output_dir": str(out_dir),
        "pack_json": str(out_dir / "pack.json"),
        "messages": messages,
        "summary_audio": pack.summary_audio,
        "word_audio": [v.audio_path for v in pack.vocabulary],
        "article": {"title": pack.title, "url": pack.url, "source": pack.source},
    }

    if send_telegram:
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = (env.get("TELEGRAM_HOME_CHANNEL") or env.get("TELEGRAM_ALLOWED_USERS") or "").strip()
        if not token or not chat_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_HOME_CHANNEL/TELEGRAM_ALLOWED_USERS required")
        deliver_telegram_pack(
            token,
            chat_id,
            messages,
            pack.summary_audio,
            [v.audio_path for v in pack.vocabulary],
        )
        result["telegram_sent"] = True

    if quiet:
        print(
            f"[ok] {pack.title[:60]}… | vocab={len(pack.vocabulary)} | {out_dir}",
            file=sys.stderr,
        )
    elif json_only or not quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    ensure_hermes_venv()
    parser = argparse.ArgumentParser(description="Generate International Tech/Finance English Learning Pack")
    parser.add_argument("--send-telegram", action="store_true", help="Send 3 Telegram messages with audio")
    parser.add_argument("--json-only", action="store_true", help="Print machine-readable JSON to stdout")
    parser.add_argument(
        "--cron",
        action="store_true",
        help="Cron no_agent mode: --send-telegram, empty stdout on success, error text on failure",
    )
    args = parser.parse_args()
    try:
        if args.cron:
            generate_pack(send_telegram=True, quiet=True)
            return 0
        generate_pack(send_telegram=args.send_telegram, json_only=args.json_only)
        return 0
    except Exception as exc:
        msg = f"❌ 國際科技財經英文學習包失敗：{exc}"
        if args.cron:
            print(msg)
        else:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
