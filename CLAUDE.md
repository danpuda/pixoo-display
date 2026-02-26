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

### Phase 5.1: 表示レイアウト改善（DIR指示 2026-02-27 追加）
**スコープ**: `pixoo-display-test.py` のアイコンバーレイアウト改修

#### 問題点
- 漢字1文字（監/検/開）が64px LEDで潰れて読めない
- 役割名が分かりにくい（「検」だけでは何のことか不明）
- 表示のバラつき（DEVだけタスク名あり、他はなし）

#### 変更内容
1. **アイコンバーを2段構成に変更**:
   - **1段目（上）**: ワーカー名（タスク名: `ebay-ph4`, `codex-review` 等）— 小さめフォント
   - **2段目（下）**: 役割名 — **大きめ・読めるフォント**で表示
2. **役割名はすべて英字に統一**: `DIR` / `PL` / `DEV` / `QA` / `RES`
   - 漢字（監/検/開/調）は廃止。64px LEDでは読めないため
3. **ROLE_LABELS を英字に変更**:
   ```python
   ROLE_LABELS = {
       "DIR": "DIR",
       "PL":  "PL",
       "DEV": "DEV",
       "QA":  "QA",
       "SEC": "SEC",
       "RES": "RES",
   }
   ```
4. **ICON_BAR_H を調整**: 2段にするため 11px → 16px（スプライトとの兼ね合い確認）
5. **ワーカー名が長い場合は省略**（`ebay-ph4-im...` のように切る）
6. **ロブスター（スプライト）に被らないように配置**: スプライトのcrop開始位置を調整

#### 注意
- スプライトの高さ調整が必要。`bg_frame.crop((0, 4 + ICON_BAR_H, ...)` の部分
- フォントサイズ: 1段目 6px / 2段目 8-9px 目安（64px LEDで読めるか確認）
- タイマー表示は2段目の右端に維持

**完了条件:**
- [ ] 2段構成で表示される
- [ ] 役割名が英字で読める
- [ ] ワーカー名が1段目に表示される
- [ ] スプライトと被らない
- [ ] 全テスト通過
- [ ] **Geminiレビュー実施**（下記手順参照）
- [ ] reviews/codex-phase51-20260227.md + reviews/gemini-phase51-20260227.md 保存
- [ ] git commit + push 完了

### Phase 5.2: ワーカー名視認性改善 + 合計数復活（DIR指示 2026-02-27）
**スコープ**: `pixoo-display-test.py` のワーカー名表示改善 + 合計エージェント数「×N」復活

#### 問題点（やまちゃん🗻フィードバック）
1. **ワーカー名（1段目）のフォントが小さすぎて潰れて読めない**
2. **ワーカー名の文字色が暗すぎてほぼ見えない**（`*2//3` で66%に暗くしてる）
3. **合計エージェント数「×N」が消えた**（Phase 5.1のレイアウト変更時に削除された）

#### 変更内容
1. **ワーカー名の文字色をフル明度にする**:
   - 現在: `wn_color = (color[0]*2//3, color[1]*2//3, color[2]*2//3)` → 暗すぎ
   - 修正: **役割名と同じフル明度**で表示（`*2//3` 削除）
   - ワーカー名と役割名が同等の視認性になるようにする
2. **ワーカー名のフォントサイズを上げる**:
   - 現在: row1_font = 6px → 小さすぎ
   - 修正: **8px に変更**（役割名と同じか近いサイズ）
   - ICON_BAR_H の調整が必要になる場合あり
3. **合計エージェント数「×N」を復活させる**:
   - v6初版（`e4d7e75`）にあった Top-right count 表示を復活
   - `get_count_color()` + `draw_outlined_text()` で右上に描画
   - 参考: v6初版の行340-358（`# --- Top-right count ---` セクション）
   - アイコンバー2段目の右端（タイマーの上 or 1段目の右端）に配置

#### 参考コード（v6初版のカウント表示）
```python
# --- Top-right count ---
if agent_count >= 1:
    count_str = str(agent_count)
    x_label = "x"
    count_color = get_count_color(agent_count)
    x_w, _ = text_bbox_size(ui_font, x_label)
    n_w, _ = text_bbox_size(ui_font, count_str)
    gap = 1
    total_w = x_w + gap + n_w
    x0 = DISPLAY_SIZE - total_w - 1
    y0 = 1
    draw_outlined_text(draw, (x0, y0), x_label, ui_font, fill=(140, 140, 140))
    draw_outlined_text(draw, (x0 + x_w + gap, y0), count_str, ui_font, fill=count_color)
```

#### 注意
- `get_count_color()` 関数がまだ残ってるか確認。なければv6初版からコピー
- カウント位置とワーカー名/タイマーが被らないよう注意
- ICON_BAR_H 変更時はスプライトの `bg_frame.crop` も調整

**完了条件:**
- [ ] ワーカー名がフル明度で表示される
- [ ] ワーカー名のフォントサイズが上がって読める
- [ ] 右上に「×N」（合計エージェント数）が表示される
- [ ] 既存の役割名・タイマー表示と被らない
- [ ] 全テスト通過
- [ ] Codexレビューで🔴が0
- [ ] git commit 完了

### Phase 5.3: アイコンバー背景透過（DIR指示 2026-02-27）
**スコープ**: `pixoo-display-test.py` の `compose_frame()` — アイコンバーの描画方式変更

#### 問題点
アイコンバー（上部18px）が黒塗り背景でスプライト（ロブスター🦞）の頭を隠してしまう。
スクロールテキスト（下部）は透過strip + マスク付きpasteで正しく透過してるのに、
アイコンバーのテキストは黒背景の上に直接描画されている。

#### 現在のコード（問題箇所）
```python
img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0))  # 黒背景
img.paste(
    bg_frame.crop((0, 4 + ICON_BAR_H, DISPLAY_SIZE, DISPLAY_SIZE)),  # スプライト上部をカット
    (0, ICON_BAR_H),  # 18px下にペースト → 上部18pxは真っ黒
)
draw = ImageDraw.Draw(img)
draw.text(...)  # 黒い背景の上にテキスト → スプライトが隠れる
```

#### 修正方針
1. **スプライトをカットせずフルサイズで描画**（上部マージンだけ残す）
2. **アイコンバーのテキストを透過オーバーレイとして重ねる**（スクロールテキストと同じ方式）
   - `Image.new("RGBA", ..., (0,0,0,0))` で透過レイヤー作成
   - テキストを透過レイヤーに描画
   - `img.paste(overlay, (0,0), overlay)` でマスク付き合成
3. **×N カウント表示も同じ透過レイヤーに描画する**

#### 参考: スクロールテキストの透過方式（正しい例）
```python
strip = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # 透過
# ... テキスト描画 ...
text_region = strip.crop(...)
img.paste(text_region, (dst_x, marquee_y - 2), text_region)  # マスク付き
```

**完了条件:**
- [ ] スプライトの頭がアイコンバー越しに見える
- [ ] テキストは読める（背景透過でもコントラスト確保 — `draw_outlined_text` 使用推奨）
- [ ] ×Nカウントも透過
- [ ] 全テスト通過
- [ ] git commit 完了

## ⚠️ Geminiレビュー手順（Phase 5.1 で必須！）

Codexレビュー完了後、**Geminiレビューも実施すること**。

```bash
# Step 1: レビュー対象のdiffを生成
cd /home/yama/pixoo-display
git diff HEAD~1 > /tmp/pixoo-phase51-diff.txt

# Step 2: Geminiにレビュー依頼（AntiGravity IDE CDP経由）
# CDPブリッジ経由でGeminiサイドバーにプロンプトを送信
curl -s http://localhost:3002/api/chat -X POST -H 'Content-Type: application/json' -d '{
  "provider": "gemini",
  "message": "以下のコードdiffをレビューしてください。\n\n対象: Pixoo-64 Phase 5.1（表示レイアウト改善）\nチェック: バグ・ロジックエラー・レイアウト計算・エッジケース\nフォーマット: 🔴致命的/🟡改善/🟢良い点 + スコアX/100\n日本語で。\n\n```diff\n'$(cat /tmp/pixoo-phase51-diff.txt)'\n```"
}' | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('response','ERROR'))" > reviews/gemini-phase51-20260227.md

# Step 3: もしCDP失敗したら、以下のメッセージをDIRに報告:
# 「CDP不可、Geminiレビュー未実施」（代替禁止！Sonnetで代わりにやるな！）

# Step 4: git add + commit
git add reviews/gemini-phase51-20260227.md
git commit -m "🌀 QA: Phase 5.1 Gemini review"
```

**🔴 重要**: Geminiレビューが失敗した場合は「CDP不可、Geminiレビュー未実施」と正直に報告しろ。
SonnetやCodexで代替するな（偽装禁止 = INC-009教訓）。

### Phase 5.3+5.4: 背景透過 + sync統合（DIR指示 2026-02-27）

**2つまとめてやること。順番: 5.4(wrapper統合) → 5.3(背景透過)**

#### Phase 5.4: sync daemon を display-wrapper に統合
**スコープ**: `pixoo-display-wrapper.sh` の改修

##### 問題点
- `pixoo-sync-wrapper.sh` と `pixoo-display-wrapper.sh` が**別プロセス**で管理されている
- display wrapper は生きてるのに sync wrapper だけ死ぬ → JSON更新停止 → TTL 10分切れ → 全エージェント消える → ロブ🦞フォールバック表示
- これが「tmux表示してたのにいつの間にかロブ🦞に戻ってた」バグの原因

##### 変更内容
1. **`pixoo-display-wrapper.sh` で sync daemon も起動する**:
   ```bash
   # display-wrapper.sh の while true ループの前に:
   # sync daemon をバックグラウンドで起動
   python3 -u /home/yama/pixoo-display/pixoo_tmux_sync.py >> /tmp/pixoo-tmux-sync.log 2>&1 &
   SYNC_PID=$!
   
   # trap で cleanup（display終了時にsyncも殺す）
   cleanup() {
       kill $SYNC_PID 2>/dev/null
       wait $SYNC_PID 2>/dev/null
   }
   trap cleanup EXIT
   ```
2. **while ループ内で sync の生存確認**:
   ```bash
   # display 再起動ループ内で毎回チェック
   if ! kill -0 $SYNC_PID 2>/dev/null; then
       echo "[$(date)] sync daemon died, restarting..." >> "$LOG"
       python3 -u /home/yama/pixoo-display/pixoo_tmux_sync.py >> /tmp/pixoo-tmux-sync.log 2>&1 &
       SYNC_PID=$!
   fi
   ```
3. **`pixoo-sync-wrapper.sh` は温存**（単体テスト用に残す。本番では使わない）

##### 完了条件:
- [ ] display-wrapper 起動で sync も自動起動される
- [ ] display 再起動しても sync が生きてる
- [ ] sync が死んでも display-wrapper が5秒以内に再起動する
- [ ] `pixoo-sync-wrapper.sh` は変更しない（温存）
- [ ] git commit

#### Phase 5.3: アイコンバー背景透過（上記参照）
Phase 5.3 の仕様は上に記載済み。5.4 完了後に着手。

**両Phase完了条件:**
- [ ] Phase 5.4 + 5.3 両方完了
- [ ] 全テスト通過
- [ ] Codexレビューで🔴が0
- [ ] git commit + push 完了
