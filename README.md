# Danus 本機研究工作區

把 **Open WebUI 聊天、Danus 數學專案與免費文獻搜尋**整合在同一個網頁。
使用你已經啟動的本機模型，預設入口為 **<http://127.0.0.1:3001/>**。

[English quick start](README.en.md) · [檔案與來源](THIRD_PARTY_NOTICES.md) · [版本紀錄](CHANGELOG.md)

## 能做什麼

- 與本機模型聊天、上傳 PDF 提問。
- 建立數學專案，查看進度、完整寬度的成果、文獻與事實圖。
- 立即停止、重新命名、複製專案與下載成果。
- 移到回收筒、還原，或永久刪除。回收筒內的永久刪除按下即執行，不再二次確認。
- 選擇免費網頁／論文來源；聊天和每個 Danus 專案都能各自開關搜尋。
- 搜尋 arXiv、Crossref、IACR ePrint 與 Matlas；arXiv 支援 HTML／PDF 原文擷取。

這是可自行部署的原始碼套件，包含必要的後端與設定。**模型權重、使用者專案、聊天紀錄、論文快取與私人金鑰不包含在套件中。**

## 1. 準備 Docker 和模型

需要：

1. Docker Desktop（Windows/macOS，使用 Linux containers），或 Linux 的 Docker Engine＋Compose v2。
2. 一個已啟動、容器可以連到的本機模型服務。
3. 首次安裝時可連網，以下載映像和執行依賴。

本版沿用 llama.cpp／KVMem 類型的模型介面，模型端需提供：

| 路徑 | 用途 |
|---|---|
| `GET /health` | 連線狀態 |
| `GET /v1/models` | 取得模型名稱 |
| `POST /v1/chat/completions` | 串流聊天與工具呼叫 |

Danus 使用工具呼叫，模型需能可靠處理工具與長上下文。本版的轉接設定使用 **65,536 tokens**；請讓模型伺服器也提供相應上下文。模型速度、記憶體需求與數學能力取決於你選擇的模型。

此套件**不安裝、不下載，也不啟動你的模型容器**。先用 Docker Desktop 或你原本的方式把模型啟動。例如模型容器已存在時：

```powershell
docker start YOUR_MODEL_CONTAINER
```

將 `YOUR_MODEL_CONTAINER` 換成自己的容器名稱。模型端預設採本機、免驗證介面；此版本沒有把外部模型 API 金鑰自動轉交給模型伺服器。

## 2. 建立本機設定

在本套件資料夾開啟終端機。

**Windows PowerShell：**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare.ps1
notepad .env
```

**Linux / macOS：**

```bash
bash scripts/prepare.sh
# 使用文字編輯器開啟 .env
```

準備腳本只會複製不存在的範本，保留已存在的設定。它會建立：

```text
.env
danus-setup/codex-danus.env
danus-setup/danus.env
```

在 `.env` 設定兩個值：

```dotenv
MODEL_BASE_URL=http://host.docker.internal:8080
MODEL_NAME=你的模型服務回傳的實際模型名稱
COMPOSE_PROJECT_NAME=danus-webui
```

- `MODEL_BASE_URL` 必須是 **Docker 容器可以連線**的模型網址；結尾不要加 `/v1` 或 `/`。
- Docker Desktop 上，`host.docker.internal` 通常用來連到主機發布的模型服務。
- Linux 請確認模型服務的監聽位址可由容器存取；若模型在同一個 Docker 網路，也可使用可解析的模型容器名稱。
- `MODEL_NAME` 不是檔案路徑，而是 `/v1/models` 回傳的 `id`。

例如在主機取得可用名稱：

```powershell
(Invoke-RestMethod http://127.0.0.1:8080/v1/models).data.id
```

或：

```bash
curl http://127.0.0.1:8080/v1/models
```

`local-model` 是 Danus 轉接服務內部使用的固定別名，**不必把它改成模型檔名**。實際模型由 `.env` 的 `MODEL_NAME` 決定。

## 3. 首次啟動

**Windows：**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

完成第 2 步後，也可以雙擊 `webui/start.bat`。它只管理這份套件的服務，不會尋找或啟動特定名稱的模型容器。

**Linux / macOS：**

```bash
bash scripts/start.sh
```

首次啟動會建置既有 Dockerfile，等待服務就緒，並設定 Open WebUI 的「本機研究助理」。套件內的 `danus-setup/Dockerfile` 與原始工作區的版本相同；通常不需要修改 Dockerfile。

也可手動執行相同步驟：

```bash
docker compose up -d --build
docker compose ps
# 等待 3001/api/search/settings 和 3000/health 可連線後：
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
```

初次會下載 Node、Python 依賴與容器內的 Codex CLI；使用本機模型橋接，不需要 ChatGPT 登入。這些下載會保存在 Docker 資料卷，初次耗時取決於網速。

### 開啟網頁

| 入口 | 網址 |
|---|---|
| 整合工作區 | <http://127.0.0.1:3001/> |
| Open WebUI 獨立聊天 | <http://127.0.0.1:3000/> |
| 搜尋設定 | <http://127.0.0.1:3001/#settings> |
| 後端／舊版控制頁 | <http://127.0.0.1:7860/> |

預設的 `3000`、`3001`、`7860` 必須未被其他程式占用。若你已有另一套工作區在使用這些埠，請在另一台電腦使用本套件，或先自行規劃不同連接埠。

## 4. 日常使用

### 聊天和 PDF

在「聊天」選「本機研究助理」，直接提問或按附件按鈕上傳 PDF。聊天室上方的搜尋按鈕可切換是否查外部資料。

### Danus 數學專案

1. 按左側 **＋**，輸入名稱與數學問題。
2. 選擇搜尋模式：跟隨預設、開啟，或只使用現有資料。
3. 按「建立並開始」，在「進度」查看工作記錄。
4. 在「成果」閱讀已通過 Danus 驗證的命題與證明；「文獻」顯示查詢來源；「事實圖」顯示依賴。
5. 「立即停止」中止目前 worker；已保存內容仍保留。重新啟動 Docker 後，需在專案按「繼續推理」。

Danus 的驗證也是由模型執行，並非形式證明；關鍵數學結果仍需人工核對。網頁提供單一 worker 的常用流程；完整主代理、多 worker 與論文撰寫流程請參考 [Danus 文件](danus-setup/Danus/docs/operating-guide.md)。

### 搜尋來源與開關

- **一般網頁**：Bing、Brave、Google、DuckDuckGo，經由自架 SearXNG 整合。
- **免費資料 API**：Wikipedia、DuckDuckGo 即時答案。即時答案主要提供摘要與定義。
- **論文**：arXiv、Crossref、IACR ePrint、Matlas。

所有已接入來源免金鑰、無按次 API 費用，但可能被限流或要求 CAPTCHA。「測試選取來源」可查看當下連線狀態。預設勾選 Bing、Wikipedia 與論文來源。

「聊天」與「Danus 預設」分別控制。每個專案可覆寫 Danus 預設，驗證程序也會沿用專案選擇。關閉時，整合的搜尋、論文閱讀與定理搜尋工具會拒絕新查詢；已送出的請求可能繼續完成。

這個開關控制工具，並非容器網路防火牆。Danus 工作程序仍有容器網路能力，代理指引要求遵守使用者的搜尋選擇。

模型推理在你的模型服務執行；一般搜尋詞會送給所選外部來源。ePrint 使用官方 OAI-PMH 書目資料建立本機索引，初次準備後可搜尋歷史目錄，依使用需求最多每日更新一次。

ePrint 搜尋取得題名、作者與摘要，不會自動下載受網站存取規則限制的 PDF。可從來源取得 PDF 後上傳聊天。arXiv 原文擷取優先使用保留 LaTeX 的 HTML，必要時退回 PDF 文字；擷取結果須核對公式與符號。

## 5. 重開機、停止與資料

開啟 Docker Desktop，啟動自己的模型，再開啟工作區網址。需要手動補啟動時：

```bash
docker compose up -d
```

停止本套件的服務並保留資料：

```bash
docker compose down
```

資料放在這個 Compose 專案自己的 named volumes：

- `danus-runtime`：專案、成果、回收筒、搜尋設定、文獻快取與工具執行環境。
- `open-webui-data`：聊天紀錄、附件與 Open WebUI 設定。

實際 volume 名稱會加上 `COMPOSE_PROJECT_NAME` 前綴。備份時請備份這兩個資料卷；分享 Git 原始碼不會包含它們。移除 volume 會失去其中資料。

## 6. 常見問題

**畫面顯示模型未連線**

先確認自己的模型容器正在執行，並檢查 `.env` 的網址和名稱。容器內的 `127.0.0.1` 指容器本身，不是你的 Windows/macOS 主機。

**`COPY ... .env` 找不到檔案**

先執行 `scripts/prepare.ps1` 或 `scripts/prepare.sh`。這些本機設定依設計不會放入 Git，因此必須由範本建立。

**聊天有模型，但沒有搜尋工具**

確認搜尋開關已開啟，重新整理並建立新聊天、選「本機研究助理」。可重跑：

```bash
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
```

**ePrint 第一次查詢還沒有結果**

官方目錄可能仍在初始化，稍後重試。也可主動準備一次：

```bash
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python -m danus.integrations.iacr
```

**其他啟動問題**

```bash
docker compose ps
docker compose logs --tail 80
```

**想改連接埠**

需同步調整 `docker-compose.yml`、`webui/portal.js`／`portal.html` 裡的聊天網址，以及 `scripts/start.*` 的等待／開啟網址。一般安裝建議保留預設值。

**LaTeX 與報告功能**

既有 Dockerfile 提供 TeX Live。論文草稿流程由 Danus 主代理執行；本套件不包含額外安裝好的 Tectonic 執行資料。Danus 的 human-summary PDF 另需 Chromium，本版沒有自動安裝。

## 7. 分享到 GitHub / GitLab

本套件已攜帶修改後的 Danus 原始碼快照，**不需要另外初始化 submodule**。保留 [LICENSE](LICENSE)、[第三方聲明](THIRD_PARTY_NOTICES.md) 與各套件的授權檔案。

如果取得的是 ZIP，解壓縮後在套件根目錄執行：

```bash
git init -b main
git add .
git commit -m "Initial release"
git remote add origin https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY.git
git push -u origin main
```

如果取得的是已初始化 Git 的資料夾，從 `git remote add origin` 那一行開始。請以自己的遠端儲存庫網址替換範例。

如果取得的是 `.bundle`，先還原成一般 Git 資料夾：

```bash
git clone /path/to/danus-webui-v0.1.0.bundle danus-webui
cd danus-webui
git remote set-url origin https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY.git
git push -u origin main
```

`.gitignore` 會排除實際 `.env`、模型、執行資料與常見金鑰檔；上傳前仍應查看 `git status`。只分享這個套件資料夾的內容。

### 原始碼上傳與公開架站

本套件預設只綁定 `127.0.0.1`，Open WebUI 為本機免登入模式。它適合每位使用者在自己的電腦執行。上傳原始碼到 GitHub 不會把聊天或模型對外開放。

若要改成網際網路上的多人服務，需要另外設計登入、權限、TLS 與反向代理；不能直接把目前免登入的服務公開。這也不是只上傳 HTML 就能工作的靜態網站，後端仍需要 Docker 與可用模型。

## 開發與測試

```bash
docker compose exec -T -e PYTHONPATH=/opt/webui local-llm-webui /opt/danus/runtime/venv/bin/python -m unittest discover -s /opt/webui/tests -v
```

測試使用臨時專案，涵蓋停止／回收筒、論文擷取、ePrint 索引、搜尋開關、來源篩選與驗證程序的設定傳遞。

這份發行套件的檢查範圍與限制見 [VALIDATION.md](VALIDATION.md)。

## 目錄

```text
webui/                    整合介面、必要後端、搜尋設定、測試、靜態套件
danus-setup/Danus/         修改後的 Danus 原始碼快照與原始授權
danus-setup/Dockerfile     原樣保留的整合服務 Dockerfile
danus-setup/start.sh       原樣保留的容器啟動程式
danus-setup/*.env.example  不含私人資料的本機設定範本
danus-setup/proxy-config/  內部協定轉接設定
scripts/                  準備設定與首次啟動輔助程式
docker-compose.yml        可分享的獨立 Compose 專案
.env.example              自行填入模型網址與名稱
```

## 授權與來源

本套件原始碼採 [Apache-2.0](LICENSE)，第三方檔案依各自授權。Danus 上游為 [frenzymath/Danus](https://github.com/frenzymath/Danus)，基準提交 `6d92e8d415933ca2ef52fd1a4da73fdfcd418f1c`。詳見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
