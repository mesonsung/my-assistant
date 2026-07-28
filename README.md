# hermesAgent（hermes-agent:meson）

基於 [NousResearch hermes-agent](https://github.com/NousResearch/hermes-agent) 的**衍生 Docker 映像**與本機客製。

- 基底：`nousresearch/hermes-agent:latest`（約 2.6GB，為體積下限）
- 映像標籤：`hermes-agent:meson`
- 本機加值：可選 TTS/STT／工具、以及 `skills/`、`scripts/`（建置時 COPY 到 `/opt/hermes-custom`）

上游文件：<https://hermes-agent.nousresearch.com/docs/user-guide/docker>

---

## 專案結構

```
.
├── Dockerfile              # 衍生映像
├── docker-compose.yaml     # hermes gateway + dashboard
├── .dockerignore
├── skills/                 # 自訂 skills（例：english-learning-pack）
├── scripts/                # 自訂腳本（學習包、MCP inspector 等）
├── hermes-data/            # 執行時資料（bind → /opt/data）
└── hermes-output/          # 輸出（bind → /output）
```

> 無 `.env.example`；請在專案根目錄自建 `.env`（已被 `.dockerignore` 排除，不會進映像）。

---

## 快速開始

```bash
cd /home/meson/hermesAgent

# 建置（預設瘦身：不裝 faster-whisper / piper / 大型 apt）
docker compose build

# 啟動
docker compose up -d

# 可選：讓 volume 檔案擁有者對齊目前主機使用者
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose up -d
```

常用指令：

```bash
docker compose ps
docker compose logs -f hermes
docker compose logs -f dashboard
docker compose exec hermes hermes gateway status
docker compose down
```

---

## 服務說明

| 服務 | 容器名 | 指令 | 埠 | 說明 |
|------|--------|------|-----|------|
| `hermes` | `hermes` | `gateway run` | `${HERMES_GATEWAY_PORT:-8642}` → 8642 | Agent gateway |
| `dashboard` | `hermes-dashboard` | `dashboard --host 0.0.0.0` | `${HERMES_DASHBOARD_PORT:-9119}` → 9119 | Web dashboard（basic auth） |

- `dashboard` 依賴 `hermes` **healthy** 後才啟動。
- Dashboard 綁 `0.0.0.0` 方便 LAN；**務必設定 basic auth**。非可信網路請用 SSH tunnel / reverse proxy。
- `hermes` 掛載 `/var/run/docker.sock`，讓 agent 可操作主機 Docker（高權限）；不用可從 compose 移除。

可選 API（compose 內註解）：設定 `API_SERVER_ENABLED=true` 等後，可在 `:8642` 提供 OpenAI-compatible API 與 `/health`。

---

## 環境變數與 secrets

在專案根目錄建立 `.env`（範例為**佔位符**，請自行替換）：

```bash
TZ=Asia/Taipei
HERMES_UID=10000
HERMES_GID=10000

HERMES_GATEWAY_PORT=8642
HERMES_DASHBOARD_PORT=9119

# Dashboard basic auth（必改）
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=your_user
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=your_strong_password
# 建議固定 secret，避免重啟後 session 失效
# HERMES_DASHBOARD_BASIC_AUTH_SECRET=your_long_random_secret

# Dashboard 探測 gateway（多容器）
GATEWAY_HEALTH_URL=http://hermes:8642

# 可選：換基底映像
# HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest

# 可選：建置開關（亦可用於 compose build args）
# INSTALL_FASTER_WHISPER=0
# INSTALL_PIPER_TTS=0
# INSTALL_AGENT_UTILS=0
# INSTALL_OPS_TOOLS=0
# INSTALL_EDGE_TTS=1
# INSTALL_DDGS=1
```

Agent 執行期設定（模型、Telegram 等）通常放在資料目錄內，例如：

- `hermes-data/config.yaml`
- `hermes-data/.env`（如 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_HOME_CHANNEL`）

**不要把真實密碼寫進 README 或 commit。**

---

## 建置選項（瘦身 build args）

上游基底約 **2.6GB**。本衍生層預設只加輕量套件（`edge-tts`、`ddgs`），大型可選依賴**預設關閉**。

| Build arg | 預設 | 用途 |
|-----------|------|------|
| `INSTALL_EDGE_TTS` | `1` | 雲端 TTS（英語學習包等） |
| `INSTALL_DDGS` | `1` | 搜尋 |
| `INSTALL_FASTER_WHISPER` | `0` | 本機 STT（較大：ctranslate2/av 等） |
| `INSTALL_PIPER_TTS` | `0` | 本機 Piper TTS（較大：onnxruntime） |
| `INSTALL_AGENT_UTILS` | `0` | apt：jq/yq、imagemagick、poppler、psql 等 |
| `INSTALL_OPS_TOOLS` | `0` | apt：htop、vim-tiny |
| `HERMES_BASE_IMAGE` | `nousresearch/hermes-agent:latest` | 基底映像 |
| `FASTER_WHISPER_VERSION` | `1.2.1` | 僅在啟用 STT 時使用 |
| `SOUNDFILE_VERSION` | `0.13.1` | 同上 |

完整功能建置：

```bash
docker compose build \
  --build-arg INSTALL_FASTER_WHISPER=1 \
  --build-arg INSTALL_PIPER_TTS=1 \
  --build-arg INSTALL_AGENT_UTILS=1 \
  --build-arg INSTALL_OPS_TOOLS=1
```

或：

```bash
docker build \
  --build-arg INSTALL_FASTER_WHISPER=1 \
  --build-arg INSTALL_PIPER_TTS=1 \
  --build-arg INSTALL_AGENT_UTILS=1 \
  --build-arg INSTALL_OPS_TOOLS=1 \
  -t hermes-agent:meson .
```

**取捨**：預設關 STT/Piper → 無法用本機 `faster-whisper`／Piper；學習包預設走 **Edge TTS**，不受影響。關 `INSTALL_AGENT_UTILS` → 映像內無 `jq`／`convert`／`pdftotext` 等。

---

## Volume／資料目錄

| 主機路徑 | 容器路徑 | 用途 |
|----------|----------|------|
| `./hermes-data` | `/opt/data` | `HERMES_HOME`：設定、`.env`、skills、cron、快取等 |
| `./hermes-output` | `/output` | 輸出（僅 `hermes` 服務掛載） |
| `/var/run/docker.sock` | 同左 | Docker tools（僅 `hermes`） |

`.dockerignore` 會排除 `hermes-data/`、`hermes-output/`、`.env`、模型權重等，避免打進建置 context。

映像內另有種子目錄：`/opt/hermes-custom/{skills,scripts}`（建置時 COPY）。執行期 skills／scripts 通常放在 `$HERMES_HOME`（`/opt/data`）volume；可自行同步或 bind-mount。

---

## 健康檢查與驗證

Compose healthcheck：

- **hermes**：`hermes gateway status`（不依賴 API server；`start_period` 120s）
- **dashboard**：對 `http://127.0.0.1:9119/` 取 HTTP code；`200|301|302|401|403` 皆算 healthy（basic auth 下 401/403 屬預期）

驗證：

```bash
docker compose ps
docker compose exec hermes hermes gateway status
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9119/
# 若已啟用 API_SERVER_*：
# curl -sf http://127.0.0.1:8642/health
```

---

## 自訂 skills／scripts（可選）

已打包範例：

| 路徑 | 說明 |
|------|------|
| `skills/english-learning-pack/` | 國際科技財經英文學習包 skill |
| `scripts/generate_english_learning_pack.py` | 產生學習包（新聞摘要、單字、Edge TTS、可送 Telegram） |
| `scripts/english_learning_pack_cron.py` | cron `--no-agent` 入口 |
| `scripts/start-mcp-inspector.sh` | 本機啟動 MCP Inspector（獨立用途，非 compose 服務） |

學習包依賴映像預設的 `edge-tts`／`ddgs`，以及 `hermes-data` 內的模型與 Telegram 設定。詳見 `skills/english-learning-pack/SKILL.md`。

新增 skill：放到 `skills/<name>/`，重建映像或掛載到 `/opt/data` 對應目錄後使用。

---

## 注意事項（重要）

1. **保留上游 ENTRYPOINT**  
   勿覆寫 entrypoint。必須維持  
   `["/init", "/opt/hermes/docker/main-wrapper.sh"]`  
   讓 s6-overlay 負責 volume chown、監督程序與信號轉發。

2. **映像內保持 `USER root`**  
   s6 的 cont-init 需以 root 啟動，才能 `usermod`／chown，再降權到 `hermes`（預設 UID 10000）。在 Dockerfile 設 `USER hermes` 會破壞 `HERMES_UID` remapping。

3. **不要在 compose 覆寫 PATH**  
   上游已正確設定 Node（`/usr/local`）與 Hermes venv；錯誤覆寫 PATH 會弄壞 CLI／工具。

4. **權限**  
   預設 `HERMES_UID`/`HERMES_GID` 為 `10000`。若要在主機端編輯 `hermes-data`，用 `id -u`／`id -g` 對齊。

5. **安全性**  
   - Dashboard 預設綁全介面：務必改掉 basic auth，並考慮 tunnel／proxy。  
   - `docker.sock` 等於給 agent 主機 Docker 控制權。  
   - 機密只放 `.env`／`hermes-data/.env`，勿寫進映像或 git。
