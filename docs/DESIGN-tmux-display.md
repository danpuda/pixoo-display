---
created: 2026-02-26
type: design
status: draft
---
# 🎨 Pixoo tmux エージェントチーム表示 — 設計書

> **目的**: Pixoo-64 の表示を「サブエージェント監視」→「tmux エージェントチーム可視化」に作り替える
> **背景**: sessions_spawn 廃止 → claude-p 移行完了。サブエージェント表示は不要に。
>           代わりに tmux の shared セッションにエージェントチーム（PL/レビュアー等）が常駐。

---

## 1. 現状 → 変更後

### 現状（v6）
```
データソース: ~/.openclaw/agents/main/sessions/*.jsonl
  → pixoo_agent_sync.py が JSONL 解析
  → /tmp/pixoo-agents.json に書き出し
  → pixoo-display-test.py が描画
表示: サブエージェント（Sonnet/Haiku等）のキャラ + タスク名スクロール
```

### 変更後（v7）
```
データソース: tmux list-windows -t shared -F "#{window_index}:#{window_name}:#{pane_pid}"
  → pixoo_tmux_sync.py が tmux 状態をパース
  → /tmp/pixoo-agents.json に同じ形式で書き出し（互換性維持）
  → pixoo-display-test.py は最小限の変更で対応
表示: tmux ワーカーの名前 + 役割 + リアルタイム状態
```

## 2. アーキテクチャ

```
┌─────────────────────────────────────────────┐
│ tmux shared セッション                        │
│ window 0: monitor                            │
│ window 1: ebay-ph4-impl (Claude Code = PL-1) │
│ window 2: codex-review (Codex = Reviewer)    │
│ window 3: worker-3 (空き)                    │
│ ...                                           │
└──────────────┬──────────────────────────────┘
               │ `tmux list-windows` (3秒ポーリング)
               ▼
┌─────────────────────────────────────────────┐
│ pixoo_tmux_sync.py (NEW — 監視デーモン)      │
│ - tmux window 一覧取得                       │
│ - window名 → 役割マッピング                  │
│ - pane の最終出力行を取得（電光掲示板用）    │
│ - /tmp/pixoo-agents.json に書き出し          │
└──────────────┬──────────────────────────────┘
               │ JSON 書き出し（既存と互換）
               ▼
┌─────────────────────────────────────────────┐
│ /tmp/pixoo-agents.json                       │
│ { "agents": [                                │
│     {"id": "ebay-ph4-impl",                  │
│      "char": "claude-code",                  │
│      "role": "PL-1",                         │
│      "task": "eBay Phase 4 実装中",          │
│      "status": "active",                     │
│      "scroll_text": "最後の出力行..."}       │
│   ], "main_active": true }                   │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ pixoo-display-test.py (既存 — 小改修)        │
│ - role 表示追加（PL-1 / REV / PL-2）        │
│ - scroll_text を電光掲示板に反映             │
│ - キャラマッピング微調整                     │
└──────────────┬──────────────────────────────┘
               │ HTTP POST
               ▼
┌─────────────────────────────────────────────┐
│ Pixoo-64 (192.168.86.42)                    │
└─────────────────────────────────────────────┘
```

## 3. window名 → 役割マッピング

| window名パターン | 役割 | キャラ | 表示略称 |
|-----------------|------|--------|---------|
| `*-impl` / `*-dev` | PL-1 (Claude Code) | claude-code | `PL1` |
| `codex-*` | PL-2 / Reviewer (Codex) | codex | `PL2` or `REV` |
| `*-review` / `*-fl3*` | Reviewer | reviewer | `REV` |
| `monitor` | Monitor (ロブ🦞) | opus | `MON` |
| `worker-N` (デフォルト名) | Idle slot | idle | `---` |

**判定ロジック（優先順）:**
1. window名に `review` or `fl3` → REV
2. window名が `codex-` で始まる → PL2/REV
3. window名に `impl` or `dev` → PL1
4. window名が `monitor` → MON
5. その他 → タスク名として表示

## 4. リアルタイム状態の取得

```bash
# 各 window の最終出力（電光掲示板用）
tmux capture-pane -t shared:{window_index} -p | tail -3

# アクティブ判定
# - pane_pid が生きてるか
# - 最終出力が変化してるか（前回との diff）
```

**状態判定:**
| 状態 | 条件 | 表示 |
|------|------|------|
| 🟢 active | 出力が変化中 | キャラアニメーション |
| 🟡 waiting | pid生存 + 出力変化なし(>30秒) | キャラ静止 |
| ⚫ idle | window名が `worker-N` のまま | 非表示 or グレー |
| 🔴 error | pid死亡 or エラー出力検知 | 目がバッテン |

## 5. 画面レイアウト（64x64px）

```
┌──────────────────────────────────────────┐
│ [PL1🦞] [PL2🤓] [REV🤓]  ⏱ 01:23:45   │  ← 上部: 役割+キャラアイコン+タイマー
│                                          │
│    ┌──────────────────────────┐           │
│    │   メインキャラ表示        │           │  ← 中央: アクティブなPLのアニメーション
│    │   (アニメーション)        │           │
│    └──────────────────────────┘           │
│                                          │
│ ▶ ebay-ph4: API連携テスト中... ◀         │  ← 下部: 電光掲示板スクロール
└──────────────────────────────────────────┘
```

**上部アイコンバー（新規追加）:**
- 各ワーカーを 8x8px アイコンで横並び表示
- 役割ラベル（3文字）を下に
- アクティブなワーカーは色付き、idle はグレー

## 6. 実装計画（フェーズ分割）

### Phase 1: pixoo_tmux_sync.py 作成（sync デーモン差替え）
- tmux list-windows パース
- window名 → 役割マッピング
- /tmp/pixoo-agents.json 書き出し（既存形式互換）
- **既存の pixoo-display-test.py はそのまま動く**（最低限の互換）

### Phase 2: pixoo-display-test.py に role 表示追加
- 上部アイコンバーの追加
- 役割ラベル表示（PL1/PL2/REV/MON）
- アクティブ/待機の色分け

### Phase 3: リアルタイム電光掲示板
- tmux capture-pane で最終出力取得
- スクロールテキストに反映
- 出力変化の検知 → active/waiting 判定

### Phase 4: テスト & 安定化
- 長時間稼働テスト
- エッジケース（window追加/削除、tmux再起動）
- パフォーマンス確認

## 7. 実装方針

- **pixoo_agent_sync.py は残す**（claude-p の結果表示に将来使う可能性）
- **pixoo_tmux_sync.py を新規作成**（主系統を切替え）
- **pixoo-display-test.py は最小改修**（role 表示追加のみ）
- **wrapper.sh で起動デーモンを切替え**

## 8. 担当

| 作業 | 担当 | 理由 |
|------|------|------|
| 設計書（本文書） | 🦞 ロブ（Opus） | 社長仕事 |
| Phase 1-3 実装 | tmux PL (Claude Code) | Pythonコード生成 |
| Phase 4 テスト | 🦞 ロブ + Codex レビュー | セルフチェック禁止 |
| Pixoo 実機テスト | 🦞 ロブ（exec経由） | Pixoo接続はWSLから |

## 9. リスク

| リスク | 対策 |
|--------|------|
| tmux セッションが落ちてる | フォールバック: "tmux offline" 表示 |
| Pixoo IP変更 | 環境変数 or config ファイル |
| capture-pane の負荷 | ポーリング間隔 3秒（現状と同じ） |
| 既存 sync との競合 | wrapper で排他制御（pidfile） |
