# Pixoo Display プロジェクト仕様書

**最終更新**: 2026-02-23  
**プロジェクト**: Divoom Pixoo-64 サブエージェント可視化システム  
**コード行数**: Python 1,477行（3ファイル）+ Bash 24行（2ファイル）

---

## 1. システム概要

### 1.1 目的
OpenClawのサブエージェント稼働状況をDivoom Pixoo-64 LEDディスプレイにリアルタイム表示する。複数サブエージェントの並行稼働を視覚化し、進捗状況を物理デバイスで監視可能にする。

### 1.2 アーキテクチャ図（テキスト）

```
┌─────────────────────────────────────────────────────────────────┐
│ OpenClaw セッションディレクトリ                                   │
│ ~/.openclaw/agents/main/sessions/*.jsonl                        │
│ ~/.openclaw/agents/main/sessions/sessions.json                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │ ファイル監視（3秒ポーリング）
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ pixoo_agent_sync.py (監視デーモン)                                │
│ - JSONL解析（model検出、completion判定）                          │
│ - アクティブサブエージェント抽出                                   │
│ - sessions.json読み取り（label/model取得）                        │
└──────────────────────┬──────────────────────────────────────────┘
                       │ JSON書き出し（atomic write）
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ /tmp/pixoo-agents.json (共有状態ファイル)                         │
│ {                                                                │
│   "agents": [{"id","char","task","started","last_seen"}],       │
│   "main_active": bool                                            │
│ }                                                                │
└──────────────────────┬──────────────────────────────────────────┘
                       │ ファイル監視（1秒ポーリング）
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ pixoo-display-test.py (描画デーモン)                              │
│ - フレームアニメーション合成（4フレーム/char × 7キャラ）           │
│ - スクロールテキスト描画（Pilmoji）                                │
│ - タイマー表示（rainbow色）                                       │
│ - スリープモード判定（20分アイドル）                               │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP POST (10FPS画像転送)
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Divoom Pixoo-64 (192.168.86.42)                                 │
│ 64x64 RGB LEDマトリクス表示                                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ pixoo-agent-ctl.py (手動操作CLI)                                 │
│ - 手動add/remove/clear（テスト用）                                │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 設計思想
- **疎結合**: 3つのプロセスが独立稼働（sync/display/ctl）
- **JSONベース**: `/tmp/pixoo-agents.json` を介したデータ交換
- **可用性重視**: wrapperスクリプトによる自動再起動
- **ベストエフォート**: エラーは握りつぶして継続稼働（ログのみ）

---

## 2. コンポーネント仕様

### 2.1 pixoo_agent_sync.py（セッション監視デーモン）

**責務**: OpenClawセッションJSONLを監視し、アクティブなサブエージェントを検出

**入力**:
- `~/.openclaw/agents/main/sessions/*.jsonl` — セッション履歴ファイル
- `~/.openclaw/agents/main/sessions/sessions.json` — OpenClaw管理メタデータ

**出力**:
- `/tmp/pixoo-agents.json` — アクティブエージェント状態（atomic write）

**データフロー**:
1. 3秒ごとにセッションディレクトリをscan
2. 各JSONLファイルから以下を抽出:
   - モデル名（`_get_model_from_tail()` — 末尾50KB/200KB/全文の段階的読み込み）
   - セッション開始時刻（`get_session_started()` — 先頭行の`type=session`）
   - 完了状態（`is_session_completed()` — 末尾の`stopReason`）
   - ラベル（`sessions.json` → JSONL先頭のuser message）
3. アクティブ判定（以下を満たすもの）:
   - 最終更新が15分以内（`ACTIVE_WINDOW_SEC`）
   - 完了していない（`stopReason` が `stop/error/cancelled` 以外）
   - メインセッションでない（`sessions.json` の `agent:main:main` と照合）
   - ファイルサイズ≥1KB
4. キャラクター推論（優先順位）:
   1. `sessions.json` のlabelから推論（`infer_char_from_label()`）
   2. `sessions.json` のmodelフィールド
   3. JSONL末尾のassistant messageの`model`フィールド
   4. JSONL先頭のuser messageテキストから推論
   5. fallback: `"opus"`
5. 手動登録エージェント（`source='manual'`）の保持（TTL 10分）
6. atomic write: tempfile → rename（display daemon読み込み競合回避）

**主要関数**:
- `find_active_subagents()` — アクティブエージェント検出（メインロジック）
- `get_session_model(filepath)` — モデル名取得（キャッシング）
- `is_session_completed(filepath)` — 完了判定
- `sync_state(agents, main_active)` — JSON書き出し

**設定パラメータ**:
| パラメータ | 値 | 意味 |
|-----------|-----|------|
| `SESSIONS_DIR` | `~/.openclaw/agents/main/sessions/` | セッションJSONL格納先 |
| `STATE_FILE` | `/tmp/pixoo-agents.json` | 出力JSON |
| `POLL_SEC` | 3.0 | ポーリング間隔 |
| `ACTIVE_WINDOW_SEC` | 900 (15分) | アクティブ判定ウィンドウ |
| `MAX_AGE_SEC` | 1800 (30分) | 完了済みセッションの最大age |
| `MAX_AGE_RUNNING_SEC` | 14400 (4時間) | 実行中セッションのcap |
| `AGENT_TTL_SEC` | 600 (10分) | 手動登録エージェントのTTL |

**モデルマッピング**:
```python
MODEL_TO_CHAR = {
    "claude-opus-4-6": "opus",
    "claude-sonnet-4-5": "sonnet",
    "claude-haiku-3-5": "haiku",
    "gpt-5.2": "kusomegane",
    "gpt-5.3-codex": "codex",
    "gemini-3-pro-low": "gemini",
    "grok-4": "grok",
}
```

**ラベル推論マッピング**:
```python
LABEL_SUFFIX_TO_CHAR = {
    "🤓": "kusomegane",
    "🟠": "sonnet",
    "🌀": "gemini",
    # ... 英語・日本語キーワード
}
```

---

### 2.2 pixoo-display-test.py（描画デーモン）

**責務**: `/tmp/pixoo-agents.json` を読み、Pixoo-64にアニメーション描画

**入力**:
- `/tmp/pixoo-agents.json` — エージェント状態
- `/tmp/lob64-{char}-frame{1-4}.png` — キャラクターフレーム画像（28枚）
- `/home/yama/.fonts/meiryo.ttc` — フォント
- Gitリポジトリ（最新commit取得用）

**出力**:
- Pixoo-64 HTTP API (`http://192.168.86.42/post` への画像POST)

**データフロー**:
1. 1秒ごとに`/tmp/pixoo-agents.json`をポーリング
2. アクティブエージェント数に応じて表示モード決定:
   - `agents=0` → ロブ🦞のみ表示
   - `agents≥1` → サブエージェントのみ表示（5秒ローテーション）
3. フレーム合成（`compose_frame()`）:
   - 背景: キャラクターフレーム（4px上シフト）
   - スクロールテキスト: 最新サブエージェントのtask OR git commit（pre-render cache）
   - 右上: エージェント数（`x3` 等、グラデーション色）
   - 右下: タイマー（rainbow色サイクル、サブエージェントのみ）
4. アニメーション更新:
   - フレーム切り替え: 250ms間隔
   - スクロール: 100ms間隔（1px/step）
   - 色サイクル: フレームごと（8色ループ）
5. スリープモード判定:
   - 条件: `agents=0` AND `main_active=false` AND 20分経過
   - 動作: sleep-frame表示 + スクロールテキスト "ロブ就寝中...zzZ"
6. Pixoo送信: `pixoo.draw_image()` + `pixoo.push()` （10FPS）

**主要関数**:
- `run(duration_sec)` — メインループ
- `compose_frame()` — フレーム合成（PIL）
- `read_agent_state()` — JSON読み取り + TTL期限切れ削除
- `get_latest_task_text()` — 最新サブエージェントのtask取得
- `get_latest_git_commits()` — Git最新commit取得（30秒cache）
- `ScrollTextCache.get_strip()` — スクロールテキストのpre-render cache

**設定パラメータ**:
| パラメータ | 値 | 意味 |
|-----------|-----|------|
| `PIXOO_IP` | `192.168.86.42` | Pixoo-64のIPアドレス |
| `DISPLAY_SIZE` | 64 | ディスプレイ解像度 |
| `FRAME_INTERVAL_MS` | 250 | アニメーションフレーム間隔 |
| `SCROLL_SPEED_MS` | 100 | スクロール更新間隔 |
| `CHARACTER_SWAP_SEC` | 5.0 | キャラクター切り替え間隔 |
| `SLEEP_AFTER_SEC` | 1200 (20分) | スリープモード発動までの時間 |
| `AGENT_TTL_SEC` | 600 (10分) | エージェント自動削除のTTL |
| `SCROLL_FONT_SIZE` | 10 | スクロールテキストフォントサイズ |
| `UI_FONT_SIZE` | 8 | UI要素フォントサイズ |
| `GIT_REPOS` | 11リポジトリ | Git commit監視対象 |
| `GIT_POLL_SEC` | 30 | Git再スキャン間隔 |

**タイマー色サイクル**:
```python
TIMER_COLORS = [
    (255, 50, 50),    # 赤
    (255, 160, 0),    # オレンジ
    (255, 255, 0),    # 黄
    (0, 255, 80),     # 緑
    (0, 220, 255),    # シアン
    (80, 120, 255),   # 青
    (180, 60, 255),   # 紫
    (255, 60, 200),   # ピンク
]
```

**エージェント数グラデーション**:
```python
def get_count_color(count: int):
    # 1=bright green → 7=deep red (7段階固定パレット)
    PALETTE = {
        1: (0, 255, 80),
        2: (100, 255, 0),
        3: (200, 230, 0),
        4: (255, 200, 0),
        5: (255, 120, 0),
        6: (255, 50, 0),
        7: (255, 0, 0),
    }
```

---

### 2.3 pixoo-agent-ctl.py（手動操作CLI）

**責務**: テスト用の手動エージェント登録/削除

**サブコマンド**:
```bash
python3 pixoo-agent-ctl.py add <char> "<task>"      # 追加（ID返却）
python3 pixoo-agent-ctl.py remove <id_or_char>      # ID or 最初のchar削除
python3 pixoo-agent-ctl.py remove-all <char>        # char全削除
python3 pixoo-agent-ctl.py clear                    # 全削除
python3 pixoo-agent-ctl.py list                     # 一覧表示
```

**動作**:
- `/tmp/pixoo-agents.json` を直接read/write
- `source='manual'` タグ付き（sync daemonと区別）
- UUID生成（8文字短縮版）

**問題点**:
- syncとのrace condition（同時書き込みで破損リスク）
- lockファイルなし
- あくまでテスト用（本番運用は想定外）

---

### 2.4 pixoo-display-wrapper.sh / pixoo-sync-wrapper.sh

**責務**: デーモンの自動再起動

**動作**:
```bash
while true; do
    python3 -u <script>.py 2>&1 | tee -a <log>
    sleep 5
done
```

**問題点**:
- systemd未対応（手動tmux起動が前提）
- 無限ループ（killしないと止まらない）
- exit code無視（すべてのエラーで再起動）
- PIDファイルなし（多重起動検出不可）

---

## 3. データ形式

### 3.1 `/tmp/pixoo-agents.json` スキーマ

```json
{
  "agents": [
    {
      "id": "a3f7c21b",           // UUID短縮（8文字）
      "char": "sonnet",            // キャラクター名
      "task": "Twitter分析実行中",  // 表示用タスク名
      "started": 1708646400.5,     // Unix timestamp（セッション開始）
      "last_seen": 1708646410.2,   // Unix timestamp（最終検出）
      "source": "auto"             // "auto" or "manual"
    }
  ],
  "main_active": true              // ロブ🦞活動フラグ
}
```

**フィールド詳細**:
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|-----|------|
| `id` | string | ✅ | エージェントID（UUID 8文字） |
| `char` | string | ✅ | キャラクター名（`opus/sonnet/haiku/gemini/kusomegane/codex/grok`） |
| `task` | string | ✅ | タスク名（60文字まで） |
| `started` | float | ✅ | セッション開始時刻（Unix timestamp） |
| `last_seen` | float | ✅ | sync daemonが最後に検出した時刻 |
| `source` | string | ✅ | `"auto"` = sync検出、`"manual"` = ctl.py登録 |

---

### 3.2 セッションJSONL構造（OpenClaw）

**ファイル名**: `~/.openclaw/agents/main/sessions/<session-id>.jsonl`

**行フォーマット**（各行がJSON object）:

```jsonl
{"type":"session","timestamp":"2026-02-23T00:00:00.000Z",...}
{"type":"model_change","modelId":"claude-sonnet-4-5",...}
{"type":"message","message":"{\"role\":\"user\",\"content\":[...]}"}
{"type":"message","message":"{\"role\":\"assistant\",\"content\":[...],\"model\":\"gpt-5.2\",\"stopReason\":\"toolUse\"}"}
```

**主要typeと用途**:
| type | 用途 | sync daemonの使い方 |
|------|------|---------------------|
| `session` | セッション開始 | `timestamp` → `started` |
| `model_change` | モデル切り替え | fallback用（実際のAPI modelより優先度低） |
| `message` | 会話メッセージ | `role=assistant` の `model` / `stopReason` を読む |

**model検出ロジック**（優先順位）:
1. **末尾assistant messageの`model`フィールド** ← 最も正確（実際のAPI応答）
2. `model_change` の `modelId` ← OpenClaw設定値（APIフォールバック時に不正確）
3. fallback: `"opus"`

**completion判定ロジック**:
- 末尾assistant messageの`stopReason`が以下:
  - `"stop"` / `"error"` / `"cancelled"` → 完了
  - `"toolUse"` → 継続中（ただし10分更新なしで完了扱い）
  - なし → 継続中（ただし10分更新なしで完了扱い）

---

### 3.3 sessions.json構造（OpenClaw）

**ファイル名**: `~/.openclaw/agents/main/sessions/sessions.json`

**構造**:
```json
{
  "agent:main:main": {
    "sessionId": "abc123...",
    "model": "claude-opus-4-6",
    "label": ""
  },
  "agent:main:subagent:twitter-research-grok": {
    "sessionId": "def456...",
    "model": "grok-4",
    "label": "🦊 Twitter調査"
  }
}
```

**キー命名規則**:
- `agent:main:main` → メインセッション
- `agent:main:subagent:<slug>` → サブエージェント
- `agent:main:cron:<slug>` → cronジョブ（除外対象）
- `agent:main:openai:*` → OpenAI relay（除外対象）
- `agent:main:discord:*` → Discord relay（除外対象）

**sync daemonの使い方**:
1. `agent:main:main` の `sessionId` → メインセッション確定（display対象外）
2. `:subagent:` を含まないキー → `excluded_ids` に追加
3. `label` → キャラクター推論に使用
4. `model` → キャラクター推論に使用（`label` より低優先）

---

## 4. 表示仕様

### 4.1 フレーム構成

**64x64ピクセル レイアウト**:

```
 0                                               63
 ┌─────────────────────────────────────────────┐ 0
 │          [エージェント数: x3]               │
 │                                              │
 │                                              │
 │                                              │
 │         (キャラクターアニメーション)          │
 │              4px上シフト                     │
 │                                              │
 │                                              │
 │                                              │
 │                          [タイマー 2:34]     │ 50
 │ [スクロールテキスト→→→→→→→→→→→]          │ 55
 └─────────────────────────────────────────────┘ 63
```

**レイヤー構成**（描画順）:
1. 背景: 黒（0,0,0）
2. キャラクターフレーム（64x64, 4px上シフト）
3. スクロールテキスト（Y=55, Pilmoji pre-render）
4. タイマー（右下, rainbow色, サブエージェントのみ）
5. エージェント数（右上, グラデーション色）

---

### 4.2 キャラクターマッピング

| キャラクター | フレーム画像 | 表示条件 |
|------------|------------|---------|
| opus (ロブ🦞) | `/tmp/lob64-opus-frame{1-4}.png` | メインセッション or アイドル時 |
| sonnet | `/tmp/lob64-sonnet-frame{1-4}.png` | `model=claude-sonnet-4-5` |
| haiku | `/tmp/lob64-haiku-frame{1-4}.png` | `model=claude-haiku-*` |
| gemini | `/tmp/lob64-gemini-frame{1-4}.png` | `model=gemini-3-*` |
| kusomegane | `/tmp/lob64-kusomegane-frame{1-4}.png` | `model=gpt-5.2` |
| codex | `/tmp/lob64-codex-frame{1-4}.png` | `model=gpt-5.3-codex` |
| grok | `/tmp/lob64-grok-frame{1-4}.png` | `model=grok-4` |

**フレーム要件**:
- サイズ: 64x64 RGB
- フォーマット: PNG
- フレーム数: 4枚/キャラ
- 合計: 28枚（7キャラ × 4フレーム）
- Sleep用: 4枚（`lob64-opus-sleep-frame{1-4}.png`）

---

### 4.3 ティッカー表示

**表示内容（優先順位）**:
1. **最新サブエージェントのtask** — `agents`が存在する場合
2. **Git最新commit** — アイドル時のデフォルト（30秒cache）
3. **TODOタスク** — fallback（未使用、GIT_POLL導入後は削除予定）
4. **SLEEP_TICKER** — スリープモード時

**Git commit形式**:
```
🔧 [openclaw] 3a57c3a 記憶弱化修正 (2m前)
```

**スクロール仕様**:
- 速度: 100ms/step（10FPS）
- ステップ: 1px/frame
- ループ: テキスト幅 + 64px（完全消失後に右端から再登場）
- フォント: Meiryo 10pt（CJK対応）
- 描画: Pilmoji（絵文字サポート） + 黒アウトライン

**pre-render cache導入**:
- 理由: Pilmojiのper-frame描画がCPU負荷高（20FPS → 10FPSに削減）
- 実装: `ScrollTextCache` クラス
- 動作: テキスト全体を1回だけ透明背景の横長stripに描画 → 各フレームでcrop＆paste

---

### 4.4 スリープモード

**発動条件**:
- `agents = 0` （サブエージェントなし）
- `main_active = false` （ロブ🦞もアイドル）
- 上記状態が20分継続

**動作**:
- フレーム: `lob64-opus-sleep-frame{1-4}.png`
- ティッカー: `"ロブ就寝中...zzZ"`
- タイマー: 非表示
- エージェント数: 非表示

**復帰条件**:
- `agents > 0` OR `main_active = true`

**問題点**:
- 20分固定（設定ファイルなし）
- 復帰時のログ出力のみ（通知なし）

---

## 5. 設定パラメータ一覧

### 5.1 pixoo_agent_sync.py

| 定数名 | 現在値 | 単位 | 意味 | 変更影響 |
|--------|--------|------|------|---------|
| `SESSIONS_DIR` | `~/.openclaw/agents/main/sessions/` | path | セッションJSONL格納先 | 🔴 OpenClaw構造変更時に必須 |
| `SESSIONS_JSON_STORE` | `sessions.json` | path | OpenClawメタデータ | 🔴 同上 |
| `STATE_FILE` | `/tmp/pixoo-agents.json` | path | 出力先 | 🟡 display側も変更必要 |
| `POLL_SEC` | 3.0 | 秒 | ポーリング間隔 | 🟢 低くするとCPU負荷増 |
| `ACTIVE_WINDOW_SEC` | 900 (15分) | 秒 | アクティブ判定窓 | 🟡 短いと誤消失、長いとゾンビ残留 |
| `MAX_AGE_SEC` | 1800 (30分) | 秒 | 完了セッションの最大age | 🟢 cleanup遅延のみ |
| `MAX_AGE_RUNNING_SEC` | 14400 (4時間) | 秒 | 実行中セッションのcap | 🟢 同上 |
| `AGENT_TTL_SEC` | 600 (10分) | 秒 | 手動登録TTL | 🟢 ctl.pyテスト時のみ影響 |
| `MAIN_SESSION_MODEL` | `"claude-opus-4-6"` | string | メインセッションのモデル | 🔴 Opus以外に変えたら全壊 |

### 5.2 pixoo-display-test.py

| 定数名 | 現在値 | 単位 | 意味 | 変更影響 |
|--------|--------|------|------|---------|
| `PIXOO_IP` | `192.168.86.42` | IP | Pixoo-64アドレス | 🔴 デバイス変更時に必須 |
| `DISPLAY_SIZE` | 64 | px | ディスプレイ解像度 | 🔴 Pixoo-64専用（変更不可） |
| `FRAME_INTERVAL_MS` | 250 | ms | アニメーション間隔 | 🟢 速くするとヌルヌル、CPU増 |
| `SCROLL_SPEED_MS` | 100 | ms | スクロール更新間隔 | 🟢 同上 |
| `TEXT_STEP_PX` | 1 | px | スクロールステップ | 🟢 大きいと速く流れる |
| `CHARACTER_SWAP_SEC` | 5.0 | 秒 | キャラクター切り替え | 🟢 短いとせわしない |
| `STATE_POLL_SEC` | 1.0 | 秒 | JSON監視間隔 | 🟢 短いと反応速、CPU増 |
| `SLEEP_AFTER_SEC` | 1200 (20分) | 秒 | スリープ発動時間 | 🟡 短いとロブ思考中に寝る |
| `AGENT_TTL_SEC` | 600 (10分) | 秒 | エージェント自動削除 | 🟢 安全ネット（sync側と合わせる） |
| `SCROLL_FONT_SIZE` | 10 | pt | スクロールテキスト | 🟢 大きいと読みやすい、幅増 |
| `UI_FONT_SIZE` | 8 | pt | タイマー・カウント | 🟢 同上 |
| `GIT_POLL_SEC` | 30 | 秒 | Git再スキャン間隔 | 🟢 短いと最新commit検出速 |
| `TODO_POLL_SEC` | 60 | 秒 | TODO再読込間隔（未使用） | ⚪ 削除予定 |

### 5.3 環境依存パス

| 種別 | パス | 存在必須 | 用途 |
|------|------|---------|------|
| フレーム画像 | `/tmp/lob64-*-frame*.png` | ✅ | キャラクター描画 |
| フォント | `/home/yama/.fonts/meiryo.ttc` | ✅ | CJK文字描画 |
| Gitリポジトリ | `/mnt/c/Users/danpu/.../openclaw` 他11個 | ⚠️ | commit監視（なくても起動可） |
| TODO | `/mnt/c/Users/danpu/.../todo-priority.md` | ⚠️ | fallback ticker（未使用） |

---

## 6. 既知の問題点（厳しめ評価）

### 🔴 致命的な問題

#### 6.1 `/tmp/` 依存によるデータ揮発性
**問題**: 
- `/tmp/pixoo-agents.json` がWSL再起動で消失
- `/tmp/lob64-*.png` も同様に消失
- systemdのtmpfiles.d未対応

**影響**:
- WSL再起動後に表示が壊れる（フレーム画像なし）
- sync daemon起動前はJSON不在で空画面

**修正案**:
- `~/.cache/pixoo-display/` に移行
- systemd tmpfiles.d でフレーム画像を自動復元
- 起動時チェックスクリプト追加

---

#### 6.2 ハードコードされた設定値
**問題**:
- IPアドレス (`192.168.86.42`)
- パス (`~/.openclaw/`, `/home/yama/`)
- モデル名 (`claude-opus-4-6`)

**影響**:
- 環境移植性ゼロ
- DHCP変更でIPが変わったら全壊
- OpenClawのディレクトリ構造変更で即死

**修正案**:
- `config.toml` or `settings.yaml` 導入
- 環境変数サポート (`PIXOO_IP`, `OPENCLAW_HOME`)
- mDNS対応（`pixoo-64.local`）

---

#### 6.3 プロセス管理の脆弱性
**問題**:
- systemd未対応（手動tmux起動）
- PIDファイルなし（多重起動検出不可）
- 無限再起動ループ（exit code無視）
- killしないと止まらない

**影響**:
- サーバー再起動で自動起動しない
- 2つ起動すると競合して壊れる
- メモリリーク時も再起動し続ける

**修正案**:
- systemd unit file作成
- PIDファイル + flock
- exit code判定（0=正常終了は再起動しない）

---

### 🟡 重大な問題

#### 6.4 model推論ロジックの複雑性
**問題**:
- 4段階fallback（sessions.json label → model → JSONL tail → JSONL head）
- label推論の曖昧性（emoji/英語/日本語の混在）
- キャッシュの不整合リスク（`_model_cache` がstaleになる）

**影響**:
- デバッグ困難（「なぜこのキャラになった？」が追えない）
- 新モデル追加時にマッピング漏れリスク
- APIフォールバック時の挙動が不透明

**修正案**:
- 推論ロジックを1箇所に集約（`ModelDetector` クラス）
- デバッグログ強化（「どのステップでモデル決定したか」を記録）
- キャッシュ無効化タイミングを明確化

---

#### 6.5 エラーハンドリング不足
**問題**:
- JSON parse error → 握りつぶし（空配列返却）
- Pixoo HTTP error → 握りつぶし（ログなし）
- font load失敗 → default font（CJK表示不可）
- Git repo不在 → 無視（fallback ticker）

**影響**:
- 障害発生時に気づかない
- ログを見ても原因不明
- 正常動作との区別がつかない

**修正案**:
- 構造化ログ（JSON logging）
- リトライ機能（exponential backoff）
- health check endpoint追加
- Pixoo通信エラー時は画面に表示

---

#### 6.6 テストコード不在
**問題**:
- ユニットテストなし
- 統合テストなし
- モックPixoo APIなし

**影響**:
- リファクタリング不可（壊れたか確認できない）
- 新機能追加時の regression リスク
- CI/CD不可

**修正案**:
- pytest導入
- モックPixoo Server（Flask）
- モックセッションJSONL生成ツール
- GitHub Actions CI

---

### 🟢 軽微な問題

#### 6.7 不要なコード残留
**問題**:
- `TODO_FILE` / `TODO_POLL_SEC` （Git commit導入後は未使用）
- `_ensure_pixoo_import_works_without_tk()` （tkinter stub）
- `get_top_priority_task()` （未使用関数）

**影響**:
- コード可読性低下
- 保守コスト増

**修正案**:
- Dead code削除
- `# TODO: remove` コメント付け

---

#### 6.8 ctl.pyとsyncのrace condition
**問題**:
- 両方が`/tmp/pixoo-agents.json`を読み書き
- lockなし
- atomic write未対応（ctl.py側）

**影響**:
- 同時書き込みでJSON破損（稀）
- テスト中のみ発生（本番運用想定外）

**修正案**:
- ctl.py側もatomic write導入
- flock使用
- または「ctlは読み取り専用」に変更

---

#### 6.9 スクロールテキストの長さ制限なし
**問題**:
- task名が1000文字でも受け入れる
- 描画時にメモリ消費増
- 1周するのに10分かかる

**影響**:
- 実用性低下
- メモリリーク疑惑

**修正案**:
- 60文字でtruncate + `"..."`
- 既に`SPEC.md`では60文字としているが実装は未対応

---

#### 6.10 キャラクターローテーションの一貫性問題
**問題**:
- エージェント増減時にindexがズレる（修正済みだがロジック複雑）
- `current_display_char` と `display_idx` の2重管理
- ログが膨大（rotation debug用）

**影響**:
- 保守コスト高
- 将来のバグ混入リスク

**修正案**:
- `display_list` を `{char: [entries]}` の辞書に変更
- index管理を廃止してchar nameベースに統一

---

## 7. 依存関係

### 7.1 外部サービス

| サービス | 種類 | 用途 | 障害時の動作 |
|---------|------|------|------------|
| Divoom Pixoo-64 | ハードウェア | 表示デバイス | 起動失敗（`Pixoo(IP)` exception） |
| OpenClaw | ソフトウェア | セッションJSONL生成 | 空配列返却（エラーログなし） |

### 7.2 ファイルパス依存

| パス | 種類 | 読み取り | 書き込み | 不在時の動作 |
|------|------|---------|---------|------------|
| `~/.openclaw/agents/main/sessions/` | dir | sync | - | 空配列返却 |
| `~/.openclaw/agents/main/sessions/sessions.json` | file | sync | - | fallback（空辞書） |
| `/tmp/pixoo-agents.json` | file | display, ctl | sync, ctl | display: 空配列、sync: 新規作成 |
| `/tmp/lob64-*-frame*.png` | file | display | - | 起動失敗（`RuntimeError`） |
| `/home/yama/.fonts/meiryo.ttc` | file | display | - | fallback（DejaVu、CJK不可） |
| `/mnt/c/Users/danpu/.../openclaw` | dir | display | - | Git監視スキップ（ログなし） |

### 7.3 ネットワーク依存

| 接続先 | プロトコル | ポート | 用途 | タイムアウト |
|--------|----------|-------|------|------------|
| 192.168.86.42 | HTTP | 80 | Pixoo API (`/post`) | なし（デフォルトsocket timeout） |

### 7.4 Python依存パッケージ

```
Pillow >= 9.0     # 画像処理
pilmoji >= 2.0    # 絵文字描画
pixoo             # Pixoo-64 API wrapper
```

**問題点**:
- `requirements.txt` なし（手動pip install）
- バージョン固定なし（将来の互換性リスク）

---

## 8. デプロイ手順（現状）

### 8.1 初回セットアップ

```bash
# 1. 依存パッケージインストール
pip3 install Pillow pilmoji pixoo

# 2. フレーム画像配置
cp ~/pixoo-frames/*.png /tmp/

# 3. フォントインストール
cp meiryo.ttc ~/.fonts/
fc-cache -fv

# 4. 起動（tmux推奨）
tmux new-session -d -s pixoo-sync ./pixoo-sync-wrapper.sh
tmux new-session -d -s pixoo-display ./pixoo-display-wrapper.sh
```

### 8.2 停止方法

```bash
# PIDを探して手動kill
ps aux | grep pixoo
kill <PID>

# または tmux attach → Ctrl+C
```

**問題点**:
- デプロイ手順がREADMEに書いてない
- systemdなし（サーバー再起動で消える）
- 依存パッケージの自動インストールなし

---

## 9. 改善提案（優先順位順）

### P0（即対応）
1. **`/tmp/` 脱却** → `~/.cache/pixoo-display/` 移行
2. **設定ファイル導入** → `config.toml`
3. **systemd unit file** 作成

### P1（重要）
4. **テストコード** 追加（pytest + モックPixoo）
5. **エラーハンドリング強化** （構造化ログ、リトライ）
6. **requirements.txt** 作成

### P2（通常）
7. **model推論ロジック統合** （`ModelDetector` クラス）
8. **Dead code削除** （TODO_FILE等）
9. **health check endpoint** 追加（HTTP server）

### P3（低優先）
10. **mDNS対応** （`pixoo-64.local`）
11. **WebUI** 追加（現在稼働中エージェント一覧）
12. **Prometheus metrics** 出力

---

## 10. まとめ

### 10.1 良い点
- **動作は安定** — 2週間稼働実績あり
- **可視化効果高** — サブエージェント活動が一目瞭然
- **疎結合設計** — 3プロセス独立稼働（1つ死んでも他は動く）

### 10.2 悪い点（正直に）
- **環境依存度MAX** — IPアドレス、パス、モデル名が全部ハードコード
- **テスト不可能** — モックなし、ユニットテストなし
- **障害検知できない** — エラーログ不足、health checkなし
- **デプロイ手順が属人的** — systemd未対応、手動tmux起動
- **設計書不在** — このSPEC.mdを書くまでドキュメントゼロ

### 10.3 総評
**「動いてるけど本番運用は無理」** なプロトタイプ。  
個人デスク向けの実験作品としては十分だが、以下を満たさないと他人に渡せない：
- 設定ファイル化
- systemd対応
- テストコード
- エラーハンドリング

**現状評価**: 🟡 **動作確認済み、要改善多数**

---

## 変更履歴

| 日付 | 変更内容 | 担当 |
|------|---------|------|
| 2026-02-23 | 初版作成（本仕様書） | Sonnet🟠 |
| 2026-02-18 | sessions.json統合修正 | Sonnet🟠 |
| 2026-02-17 | model cache導入、label推論強化 | Codex😎 |
| 2026-02-16 | v6初期実装 | - |

---

**作成者**: Claude Sonnet 4.5 (サブエージェント)  
**レビュー**: 未実施（要FL3チェック）  
**次のアクション**: やまちゃん🗻による承認 → Git commit
