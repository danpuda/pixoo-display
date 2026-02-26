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
│ window 0: monitor (ロブ🦞 = DIR)             │
│ window 1: ebay-ph4-lead (PL)                 │
│ window 2: codex-review (QA)                  │
│ window 3: ebay-ph4-impl (DEV)               │
│ window 4: worker-4 (空き)                    │
└──────────────┬──────────────────────────────┘
               │ tmux list-windows -F (tab区切り, 3秒ポーリング)
               ▼
┌─────────────────────────────────────────────┐
│ pixoo_tmux_sync.py (NEW — 監視デーモン)      │
│ - tmux window 一覧取得（tab区切りでパース）  │
│ - window名 → 役割マッピング                  │
│ - capture-pane で最終出力取得（ANSI除去）    │
│ - /tmp/pixoo-agents.json に書き出し          │
└──────────────┬──────────────────────────────┘
               │ JSON 書き出し（既存必須キー互換）
               ▼
┌─────────────────────────────────────────────┐
│ /tmp/pixoo-agents.json                       │
│ { "agents": [                                │
│     {"id": "ebay-ph4-lead",                  │
│      "char": "codex",                        │
│      "role": "PL",                           │
│      "task": "eBay Phase 4 統括",            │
│      "started": 1772077000,                  │
│      "last_seen": 1772077060,                │
│      "scroll_text": "✅ tests passed..."}    │
│   ], "main_active": true }                   │
│                                               │
│ ★ 既存互換必須キー:                          │
│   id, char, task, started, last_seen,        │
│   main_active                                 │
│ ★ 新規追加キー:                              │
│   role, scroll_text, status                  │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ pixoo-display-test.py (既存 — Phase2で改修)  │
│ - Phase1: 既存キーのみで動作（互換保証）     │
│ - Phase2: role 表示追加                      │
│ - Phase3: scroll_text を電光掲示板に反映     │
└──────────────┬──────────────────────────────┘
               │ HTTP POST
               ▼
┌─────────────────────────────────────────────┐
│ Pixoo-64 (192.168.86.42)                    │
└─────────────────────────────────────────────┘
```

## 3. チーム構成（社長-PL-ワーカーモデル）

> **PL（プロジェクトリーダー）は1人だけ。** 残りはワーカー。
> Source: Claude Code 公式 Agent Teams + やまちゃん🗻指示（2026-02-26）

### チームメイト一覧

| 役割 | 略称 | 担当AI | 説明 |
|------|------|--------|------|
| 🦞 社長（Director） | `DIR` | Opus（ロブ🦞/OpenClaw） | 指示出し・判断・報告。コード書かない |
| 🏗️ PL（Project Lead） | `PL` | Claude Code（tmux対話モード） | 1人だけ。設計→実装→テストを統括 |
| ⚙️ コーディングワーカー | `DEV` | Claude Code / Codex | PLの指示でコード書く。複数OK |
| 🔍 品質管理（QA） | `QA` | Codex | レビュー・テスト・バグ発見専任 |
| 🔬 リサーチャー | `RES` | Sonnet（claude-p） | 調査・ドキュメント検索専任 |
| 👁️ セキュリティ | `SEC` | Codex / Gemini | セキュリティレビュー専任 |

### window名 → 役割マッピング

| window名パターン | 役割 | キャラ | 表示略称 |
|-----------------|------|--------|---------|
| `monitor` | 社長（ロブ🦞） | opus | `DIR` |
| `*-lead` | PL（1人のみ） | claude-code | `PL` |
| `*-impl` / `*-dev` | コーディングワーカー | claude-code / codex | `DEV` |
| `*-review` / `*-qa` / `*-fl3*` | 品質管理 | codex | `QA` |
| `*-sec` | セキュリティ | codex | `SEC` |
| `*-research` | リサーチャー | sonnet | `RES` |
| `worker-N` (デフォルト名) | 空きスロット | idle | `---` |

> **注**: `codex-` prefix は役割を決定しない。`codex-review` → QA、`codex-impl` → DEV。
> suffix（末尾の役割キーワード）が役割を決める。

**PL の選出ルール:**
- window名に `-lead` を含むものが PL（**1つだけ**）
- 複数 `-lead` がある場合: **設定ファイルで固定** or 最古の window index
- PL の固定識別: `/tmp/pixoo-tmux-config.json` に `{"pl_window": "ebay-ph4-lead"}` を記載可能
- 設定ファイルなし + `-lead` なし = PL不在（全員DEV扱い）

**判定ロジック（優先順）:**
1. `monitor` → DIR
2. window名に `-lead` → PL（config固定 or 最古1つだけ）
3. window名に `-review` or `-qa` or `-fl3` → QA
4. window名に `-sec` → SEC
5. window名に `-impl` or `-dev` → DEV
6. window名に `-research` → RES
7. `worker-N` パターン → 空き（非表示）
8. その他 → DEV（window名をタスク名として表示）

**tmux list-windows のフォーマット（tab区切り = `:` 衝突回避）:**
```bash
tmux list-windows -t shared -F "#{window_index}\t#{window_name}\t#{pane_pid}"
```

## 4. リアルタイム状態の取得

```bash
# 各 window の最終出力（電光掲示板用）
tmux capture-pane -t shared:{window_index} -p | tail -3

# アクティブ判定
# - pane_pid が生きてるか
# - 最終出力が変化してるか（前回との diff）
```

**状態判定（出力diff方式 — pid依存を避ける）:**
| 状態 | 条件 | 表示 |
|------|------|------|
| 🟢 active | capture-pane の出力が前回と異なる | キャラアニメーション |
| 🟡 waiting | 出力変化なし > 30秒 | キャラ静止（暗めドット） |
| ⚫ idle | window名が `worker-N` のまま | 非表示 |
| 🔴 error | 出力に `error` / `Error` / `FAILED` を検知 | 赤点滅ドット |

> **注**: `pane_pid` はシェルPIDであり、実作業プロセスの生死を反映しない。
> 出力 diff で判定する方が信頼性が高い。

**capture-pane の注意事項:**
- `tmux capture-pane -t shared:{idx} -p -e` → ANSIエスケープ付き raw 出力
- **ANSI除去**: `sed 's/\x1b\[[0-9;]*m//g'` でサニタイズ必須
- **alt-screen**: vim/less 使用中は capture-pane が空返答 → `waiting` 扱い
- **制御文字**: `\x00-\x1f` を除去してからスクロールテキストに使う
- **多ペイン**: window に複数 pane がある場合は pane 0 のみ対象

## 5. 画面レイアウト（64x64px）

```
64px幅 × 64px高の制約内レイアウト:

┌────────────────────────────────────────────────────────────────┐
│ 0                                                           63 │
│ ┌──┐┌──┐┌──┐┌──┐┌──┐           ┌──────────┐  ← row 0-7 (8px) │
│ │PL││D1││D2││QA││  │           │  01:23   │  上部: 5x5アイコン│
│ └──┘└──┘└──┘└──┘└──┘           └──────────┘  + タイマー       │
│ ┌──────────────────────────────────────────┐  ← row 8-51(44px)│
│ │                                          │  中央: キャラ      │
│ │        アクティブワーカーの                │  アニメーション    │
│ │        キャラアニメーション(32x32 centered) │                   │
│ │                                          │                   │
│ └──────────────────────────────────────────┘                   │
│ ▶ ebay-ph4: テスト中...                     ← row 52-63(12px) │
│                                              電光掲示板スクロール│
└────────────────────────────────────────────────────────────────┘
```

**上部アイコンバー（row 0-7, 8px高）:**
- 各メンバーを **5x5px ドット** で横並び（間隔2px → 最大8枠 = 56px）
- タイマーは右端に 5x7 フォントで表示（残り約24px）
- active = 色付きドット / waiting = 暗めドット / idle = 非表示
- ラベルは表示しない（5px では文字が潰れる。色と位置で識別）

**色コード（ドット色で役割識別）:**
| 役割 | 色 | RGB |
|------|-----|-----|
| DIR | 🟣 紫 | (180, 0, 255) |
| PL | 🔵 青 | (0, 120, 255) |
| DEV | 🟢 緑 | (0, 200, 80) |
| QA | 🟡 黄 | (255, 200, 0) |
| SEC | 🔴 赤 | (255, 60, 60) |
| RES | 🟠 橙 | (255, 140, 0) |

**DEV が複数いる場合の表示:**
- 上部バー: DEV ドットを複数並べる（全員表示、最大8枠まで）
- 中央アニメ: **最も active な DEV**（出力変化が最新）のキャラを表示
- 電光掲示板: active な DEV の出力をローテーション（5秒切替え）
- 8枠超えた場合: 古い idle から非表示にする（active 優先）

## 6. 実装計画（フェーズ分割）

### Phase 1: pixoo_tmux_sync.py 作成（sync デーモン差替え）
**スコープ**: tmux → JSON 変換のみ。display 側は触らない。
- tmux list-windows パース（tab区切り）
- window名 → 役割マッピング（判定ロジック実装）
- /tmp/pixoo-agents.json 書き出し
- **Phase1 の互換必須キー**: `id`, `char`, `task`, `started`, `last_seen`, `main_active`
- **Phase1 で追加するキー**: `role`, `status`（display側は無視するだけ）
- **Phase1 では capture-pane しない**（scroll_text は空文字）
- pixoo-sync-wrapper.sh を修正（pixoo_agent_sync.py → pixoo_tmux_sync.py に切替え）
- **成功条件**: 既存 pixoo-display-test.py がそのまま動いてキャラ表示される

### Phase 2: pixoo-display-test.py に上部アイコンバー追加
**スコープ**: display 側の改修。sync 側は触らない。
- 上部 8px に 5x5 ドットアイコン + タイマー
- 色コードで役割識別（PL=青、DEV=緑、QA=黄...）
- active/waiting の色分け
- 既存のキャラアニメーション・スクロールは維持

### Phase 3: リアルタイム電光掲示板（sync + display 連携）
**スコープ**: capture-pane 追加 + display のスクロール改修。
- pixoo_tmux_sync.py に capture-pane 取得を追加
- ANSI除去 + 制御文字サニタイズ
- scroll_text キーに書き出し
- pixoo-display-test.py のスクロールを scroll_text から取得に変更
- 出力 diff で active/waiting 判定

### Phase 4: テスト & 安定化
- 長時間稼働テスト（24h）
- エッジケース: window追加/削除、tmux再起動、Pixoo電源断
- capture-pane の alt-screen / 多ペイン対応
- パフォーマンス確認（CPU/メモリ）

## 7. 実装方針

- **pixoo_agent_sync.py は残す**（claude-p の結果表示に将来使う可能性）
- **pixoo_tmux_sync.py を新規作成**（主系統を切替え）
- **pixoo-display-test.py は最小改修**（role 表示追加のみ）
- **pixoo-sync-wrapper.sh** で起動デーモンを切替え（`pixoo_agent_sync.py` → `pixoo_tmux_sync.py`）
- **pixoo-display-wrapper.sh** は変更なし（Phase 2 まで）

## 8. 担当

| 作業 | 担当 | 理由 |
|------|------|------|
| 設計書（本文書） | 🦞 ロブ（Opus） | 社長仕事 |
| Phase 1-3 実装 | tmux DEV (Claude Code) | Pythonコード生成 |
| Phase 4 テスト | 🦞 ロブ + Codex レビュー | セルフチェック禁止 |
| Pixoo 実機テスト | 🦞 ロブ（exec経由） | Pixoo接続はWSLから |

## 9. リスク

| リスク | 対策 |
|--------|------|
| tmux セッションが落ちてる | フォールバック: "tmux offline" 表示 |
| Pixoo IP変更 | 環境変数 or config ファイル |
| capture-pane の負荷 | ポーリング間隔 3秒（現状と同じ） |
| 既存 sync との競合 | wrapper で排他制御（pidfile） |
