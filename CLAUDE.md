# CLAUDE.md — Pixoo tmux 表示化プロジェクト

## プロジェクト概要
Pixoo-64 LED (64x64) の表示を tmux エージェントチーム可視化に使う。

## 設計書
**必ず最初に読め**: `docs/DESIGN-tmux-display.md`

## チーム構成
- 🏗️ PL (あなた = Team Lead): タスク分解・DEV指示・一次チェック
- ⚙️ DEV (Teammate): コーディング・テスト
- 🦞 DIR (ロブ/Opus): チーム外。最終確認のみ
- 🤓 QA (Codex): **ACP経由でDIRが呼ぶ**（PLは直接呼ばなくてよい）

## ⚠️ プロジェクト運営ルール（2026-02-27更新・必読）

### 全Phase一括実行
- Phase 1からNまで全部やれ。通常はDIRに確認不要
- ⚠️ 例外: 破壊的操作・不明点はDIR承認必須

### 各Phase完了手順
1. 実装
2. テスト実行（unit + integration）→ 全パスまで修正
3. git commit -m "Phase X: ..."
4. 次Phaseへ

### 全Phase完了後
1. 最終テスト全件パス確認
2. mainにpush（ブランチ切らない。main一本運用）
3. 最終報告: commit一覧・テストログ・未解決リスク

### ファイル編集
- 新規ファイル → Write OK
- 既存ファイル → **Edit必須**（Write=全上書き→消失事故あり）

---

## 🎯 現在のタスク: ワーカー名表示改善（GitHub Issue #2）

### 問題
`pixoo-display-test.py` のアイコンバー上段（Row 1）のワーカー名が：
1. **フォントが小さすぎ**（8px → 64x64 LEDで潰れる）
2. **暗く見える場合がある**（ステータスによる減光処理）
3. **絵文字が□になる**（8pxフォントでは描画不能）

### 現在の設定
```python
ICON_BAR_H = 18                  # バー全体の高さ
ICON_BAR_ROW1_FONT_SIZE = 8      # ← ワーカー名（これが小さい）
ICON_BAR_ROW2_FONT_SIZE = 9      # ロールラベル
row1_y = 0                        # ワーカー名の描画位置
row2_y = 9                        # ロールラベルの描画位置
```

### 調査してから実装
1. **フォントサイズ比較テスト**: 8px/10px/11px/12px でテスト画像を生成して比較
   - `python3 -c` でPILを使ってサンプル画像を生成→保存
   - 64x64に収まるか、文字が読めるかを確認
2. **ICON_BAR_Hの調整**: フォント拡大に合わせてバー高さも調整（最大22px、電光掲示板は42px以上確保）
3. **絵文字対応**: ワーカー名から絵文字を除去してASCII/日本語のみにするか、Noto Color Emojiを試すか判断
4. **2段→1段統合の検討**: ワーカー名とロールを1行にまとめて大フォントにする案も検討

### 修正対象ファイル
- `pixoo-display-test.py` — メイン描画ロジック（compose_frame関数内）

### テスト
- `python3 -m pytest tests/` で既存52テスト全パス必須
- 修正後にサンプルフレーム画像を `tests/sample_frame.png` に保存して目視確認用に出力

### Git
- mainに直commit+push
- コミットメッセージ: `🔤 fix: ワーカー名フォント改善（Issue #2）`
