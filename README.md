# 🦞 Pixoo Display — OpenClaw サブエージェント可視化

Divoom Pixoo-64 にOpenClawのサブエージェント稼働状況をリアルタイム表示するシステム。

## コンポーネント

| ファイル | 行数 | 役割 |
|---------|------|------|
| `pixoo_agent_sync.py` | 604 | セッションJSONL監視 → `/tmp/pixoo-agents.json` 書き出し |
| `pixoo-display-test.py` | 589 | JSONを読んでPixoo-64にフレーム送信（5秒ローテーション） |
| `pixoo-agent-ctl.py` | 148 | 手動でエージェント状態を操作するCLI |
| `pixoo-display-wrapper.sh` | 12 | displayデーモンのラッパー（tee付きログ出力） |

## 依存

- Python 3.12+
- Pixoo-64 デバイス（LAN接続）
- `pixoo-notify-proxy` (HTTP Proxy, 別リポジトリ)
- OpenClaw セッションディレクトリ: `~/.openclaw/agents/main/sessions/`

## 起動

```bash
# Sync daemon（バックグラウンド）
nohup python3 -u pixoo_agent_sync.py > /tmp/pixoo-agent-sync.log 2>&1 &

# Display daemon（tmuxセッション内で実行推奨）
tmux new-session -d -s pixoo ./pixoo-display-wrapper.sh
```

## キャラクターマッピング

| モデル | キャラクター | 絵文字 |
|--------|------------|--------|
| claude-opus-4-6 | opus (ロブ🦞) | 🦞 |
| claude-sonnet-4-5 | sonnet | 🟠 |
| gpt-5.2 | kusomegane | 🤓 |
| gpt-5.3-codex | codex | 😎 |
| gemini-3-pro-* | gemini | 🌀 |
| grok-4 | grok | ⚡ |

## 修正履歴

### 2026-02-18
- **main session判定バグ修正** (🟠Sonnet): sessions.jsonの`agent:main:main`キーから確定取得。旧「最大opusファイル」ロジックはフォールバックに降格
- **gemini-3-pro-high** モデルマッピング追加
- **sessions.json読み込み統合**: `_load_session_store()` 1回読み

### 2026-02-17 (Codex 5.3 修正)
- model cache導入（ポーリング高速化）
- progressive tail reading（大ファイル対応）
- label-based model inference（APIフォールバック時のchar検出）
- atomic JSON writes（display daemon読み込み競合防止）
- opus→sonnet fallback削除（正直にopusと表示）

### 2026-02-16
- 初期実装（v6）
- 5秒キャラクターローテーション
- スリープモード（アイドル時）
- スクロールテキスト（タスク名/TODO表示）
