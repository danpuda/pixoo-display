# CLAUDE.md — Pixoo tmux 表示化プロジェクト

## プロジェクト概要
Pixoo-64 LED の表示を「サブエージェント監視」→「tmux エージェントチーム可視化」に作り替える。

## 設計書
**必ず最初に読め**: `docs/DESIGN-tmux-display.md`

## チーム構成
- 🏗️ PL (あなた = Team Lead): タスク分解・DEV指示・一次チェック・Codexレビュー管理
- ⚙️ DEV (Teammate): コーディング・テスト
- 🦞 DIR (ロブ/Opus): チーム外。最終確認のみ

## PL の責務（重要！）
1. 設計書を読んでタスクを分解する
2. DEV に具体的な実装指示を出す
3. DEV の成果物を一次チェックする
4. **Codex レビューを自動実行する**（下記参照）
5. 全Phase完了後に DIR に報告する

## ⚠️ Codex レビュー（QA — 必須！）
各 Phase の実装が完了したら、以下を Bash で実行してレビューを受けろ：

```bash
codex exec --full-auto -C /home/yama/pixoo-display \
  "## コードレビュー
対象: [変更したファイル名]
チェック: バグ・ロジックエラー・エッジケース・セキュリティ
出力: reviews/codex-phaseN-YYYYMMDD.md にファイルとして書き出せ（stdoutではなくファイル）
フォーマット: 🔴致命的/🟡改善/🟢良い点 + スコアX/100
書いたら: git add reviews/ && git commit -m '🤓 QA: Phase N Codex review'
日本語で。"
```

- 🔴致命的 が出たら **必ず修正してから次のPhaseに進め**
- 🟡改善 は判断して対応（全部やらなくてOK）
- 修正後は再レビュー（🔴が0になるまで）
- **レビュー結果は必ず `reviews/` ディレクトリにファイル保存**（stdout出力だけは禁止）
- **`reviews/` にファイルがないPhaseは完了と認めない** — git log で検証される

## 実装フェーズ

### Phase 1: pixoo_tmux_sync.py 新規作成
**スコープ**: tmux → JSON変換のみ。display側は触らない。
- `tmux list-windows -t shared -F "#{window_index}\t#{window_name}\t#{pane_pid}"` でパース
- window名 → 役割マッピング（設計書の判定ロジック参照）
- `/tmp/pixoo-agents.json` に書き出し
- 互換必須キー: `id`, `char`, `task`, `started`, `last_seen`, `main_active`
- 追加キー: `role`, `status`（display側は無視する）
- capture-pane は **しない**（Phase 3）
- `pixoo-sync-wrapper.sh` を修正して新スクリプトを呼ぶ
- **成功条件**: 既存 `pixoo-display-test.py` がそのまま動く

### Phase 2: pixoo-display-test.py に上部アイコンバー追加
**スコープ**: display側の改修。sync側は触らない。
- 上部8px に 5x5ドットアイコン + タイマー
- 色コードで役割識別（設計書の色テーブル参照）
- active/waiting の色分け

### Phase 3: リアルタイム電光掲示板
**スコープ**: sync + display 連携。
- `pixoo_tmux_sync.py` に capture-pane 取得を追加
- ANSI除去 + 制御文字サニタイズ
- `scroll_text` キーに書き出し
- display のスクロールを scroll_text から取得に変更

## 既存コード
- `pixoo_agent_sync.py` — 旧sync（触らない。温存）
- `pixoo-display-test.py` — 描画本体（Phase 2で改修）
- `pixoo-sync-wrapper.sh` — syncデーモン起動（Phase 1で修正）
- `pixoo-display-wrapper.sh` — 描画起動（変更なし）

## コーディング規約
- Python 3.10+
- UTF-8
- docstring必須
- エラーハンドリング必須（tmux未起動・Pixooオフライン対応）
- 既存の `/tmp/pixoo-agents.json` フォーマットとの互換性を壊すな

## Safety ルール
- `rm` 禁止（`trash` を使え）
- 既存ファイルの上書き前に backup を取れ
- git commit は Phase ごとに（細かく）

## 完了条件
- [ ] Phase 1: pixoo_tmux_sync.py が動いて既存 display が表示する
- [ ] Phase 2: 上部アイコンバーが64x64に収まって表示される
- [ ] Phase 3: tmux 出力がスクロールテキストに反映される
- [ ] 全Phase: Codex レビューで🔴が0
- [ ] git commit + push 完了

### Phase 4: テスト & 安定化（設計書準拠）
**スコープ**: 長時間稼働テスト + エッジケース + 🟡改善対応
1. **determine_status フリッカー修正**（🟡68/100 → 80以上目標）
   - `last_change_times` をエラー時に更新し続ける問題
   - waiting→error→active→waitingのフリッカー残りを修正
2. **Pixoo初期化時の例外保護**（🟡残留リスク）
   - Pixoo()コンストラクタが例外投げずに戻るケースの対処
   - reconnectログの偽陽性修正（"reconnected" → "reconnect attempted"）
3. **エッジケーステスト**
   - window追加/削除シミュレーション
   - tmux再起動時の挙動
   - capture-pane alt-screen対応確認
4. **全テスト実行** `python3 -m pytest tests/ -v` が通ること
5. **git commit + push**

**完了条件:**
- [ ] 全テスト通過
- [ ] 🔴致命的: 0件
- [ ] 🟡改善のフリッカー問題修正
- [ ] reviews/ にCodexレビュー保存
- [ ] git push完了

### Phase 5: 表示仕様改善（DIR指示 2026-02-27）
**スコープ**: `pixoo-display-test.py` のアイコンバー表示改修 + 暗さ修正 + CPU最適化

#### 5-A: アイコンバー表示方式変更（仕様変更）
**現状**: 全エージェントの役割ラベル（監 PL 開 開 開）をアイコンバーに一括表示
**変更**: **現在表示中のキャラクターの役割だけ**をアイコンバーに表示する

- キャラローテーション時に、そのキャラの `role` だけを表示
- 例: Sonnet表示中 → `PL` のみ表示 / Codex(DEV)表示中 → `開` のみ表示
- DIR（監督）は `main_active=true` の時だけ表示（これは変更なし）
- ただし、DEVが複数いる場合は **タスク名も横に出す**（どのDEVかわかるように）
  - 例: `開:ebay-ph4` / `開:pixoo-dev`
- 表示中キャラの役割は **フル明度** で大きめに表示（視認性重視）
- タイマー表示は維持（右端）

#### 5-B: 暗さ修正（バグ修正）
**原因**: `status != "active"` 時に色を `// 3`（1/3）にしている
```python
# 現在（L478付近）
elif status != "active":
    color = (color[0] // 3, color[1] // 3, color[2] // 3)
```

**修正**:
- `waiting` → **フル明度**（waiting は正常状態。暗くする意味がない）
- `error` → 赤（`(255, 0, 0)` — これは現状維持）
- `idle`/その他 → **2/3明度**（`* 2 // 3`）
- ※ 5-A で表示方式が変わるので、暗さの適用先は「現在表示中のキャラのラベル」のみ

#### 5-C: CPU最適化（改善）
**現状**: display-test.py が常時 **CPU 9.7%** 食っている
**原因候補**:
- 5秒ごとのキャラスワップ + Pilmoji描画
- scroll text の毎フレーム更新

**確認・最適化ポイント**:
- `SCROLL_SPEED_MS = 100`（10FPS）は適切か？→ 必要に応じて150-200msに下げる
- `STATE_POLL_SEC = 1.0` → 3.0 で十分（sync側が3秒ポーリング）
- フレームのダーティフラグ: 変化がない時はPixooへの送信をスキップ
- キャラスワップ時のみ `push_frame` すれば大幅削減

**完了条件:**
- [ ] 表示中キャラの役割だけがアイコンバーに表示される
- [ ] waiting状態のラベルがフル明度で表示される
- [ ] CPU使用率が 5% 以下に改善
- [ ] 全テスト通過（`python3 -m pytest tests/ -v`）
- [ ] reviews/codex-phase5-20260227.md にCodexレビュー保存
- [ ] git commit + push 完了
