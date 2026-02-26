# Phase 5 コードレビュー（Codex）

対象: `pixoo-display-test.py`

## 🔴致命的

1. `/tmp` 状態ファイルの内容が少し壊れるだけで表示ループ全体が落ちる（型/文字コードの未防御）
   - `read_agent_state()` は `json.JSONDecodeError` と `OSError` しか握っておらず、`UnicodeDecodeError` や `TypeError` はそのまま上位に伝播します。
   - `last_seen` / `started` が文字列などになった場合、TTL 判定の減算で `TypeError` になり得ます。
   - 参照: `pixoo-display-test.py:66`, `pixoo-display-test.py:195`, `pixoo-display-test.py:201`, `pixoo-display-test.py:209`
   - 影響: `/tmp/pixoo-agents.json` の一時破損・不正書式・想定外型で、常駐表示が停止します（ローカル DoS）。
   - 対応案: 読み込み境界で `UnicodeDecodeError`/`TypeError`/`ValueError` を吸収し、timestamp は `float()` で正規化して不正値を破棄する。

2. `scroll_text` / `task` に長さ上限がなく、巨大な横長画像を確保してメモリ枯渇を起こし得る
   - エージェント由来の `scroll_text` / `task` は未制限で ticker に入り、そのまま `_scroll_cache.get_strip()` で幅計測→`Image.new("RGBA", (w, h))` を行います。
   - `git` 由来メッセージは 60 文字で切っている一方、状態ファイル由来文字列には上限がありません。
   - 参照: `pixoo-display-test.py:249`, `pixoo-display-test.py:256`, `pixoo-display-test.py:264`, `pixoo-display-test.py:363`, `pixoo-display-test.py:372`, `pixoo-display-test.py:644`, `pixoo-display-test.py:646`
   - 影響: `/tmp` 状態ファイルに極端に長い文字列を書かれると、メモリ使用量が急増してプロセス停止・OOM の原因になります（セキュリティ/可用性）。
   - 対応案: 文字数上限（例: 120〜200 chars）と描画幅上限（px）を設け、超過時は省略記号に切る。

## 🟡改善

1. 同じ `char` のサブエージェントが複数いると、表示継続対象の復元が別個体にすり替わる
   - `display_list` に一意キーが入っておらず、再構築時の復元が最終的に `char` 名だけの一致にフォールバックしています。
   - 同一キャラ複数体のケースでは、タイマー/ラベル対象が意図せず別エージェントへ切り替わる可能性があります。
   - 参照: `pixoo-display-test.py:606`, `pixoo-display-test.py:610`, `pixoo-display-test.py:673`, `pixoo-display-test.py:681`, `pixoo-display-test.py:683`
   - 対応案: `display_list` に `id`（または tmux pane/window の一意キー）を保持し、それで復元する。

2. Sleep/Wake 時の ticker 文言切替が最大 `STATE_POLL_SEC` 遅延する
   - `new_ticker` の決定が `is_sleeping` の遷移処理より先にあるため、同じ poll 周期内で sleep/wake 状態が変わっても ticker は次回 poll まで古い文言のままです。
   - 参照: `pixoo-display-test.py:635`, `pixoo-display-test.py:639`, `pixoo-display-test.py:651`, `pixoo-display-test.py:654`, `pixoo-display-test.py:659`, `pixoo-display-test.py:661`
   - 影響: 復帰直後に `SLEEP_TICKER` が残る、または sleep 直後も通常 ticker が残るなど、表示整合性が少し崩れます。
   - 対応案: sleep 判定/復帰判定を先に行い、その後 ticker を決定する順序に入れ替える。

3. アイコンバーのラベル幅制御がなく、タイマー表示と重なり得る
   - `max_icon_x` を計算していますが未使用で、`DEV` 複数時の `task` 追記ラベルもピクセル幅で切っていません。
   - 参照: `pixoo-display-test.py:449`, `pixoo-display-test.py:464`, `pixoo-display-test.py:471`, `pixoo-display-test.py:485`, `pixoo-display-test.py:493`
   - 影響: 上部 11px バーでラベルとタイマーが重なり、可読性が大きく落ちるケースがあります。
   - 対応案: `textbbox` でピクセル幅を見て `max_icon_x` 内に収まるまで詰める。

## 🟢良い点

- `git log` 取得が `subprocess.run([...])` の配列引数 + `timeout=5` で実装されており、コマンドインジェクション/ハング耐性の基本ができている。
  - 参照: `pixoo-display-test.py:305`
- スクロール文字列を strip キャッシュ化して毎フレームの `Pilmoji` 描画を避けており、64x64 常時描画として堅実な最適化になっている。
  - 参照: `pixoo-display-test.py:350`, `pixoo-display-test.py:359`, `pixoo-display-test.py:499`
- `push_key` による dirty-frame 判定と、送信失敗時の backoff + 再接続試行は、常駐デバイス制御として実運用寄りの設計。
  - 参照: `pixoo-display-test.py:569`, `pixoo-display-test.py:760`, `pixoo-display-test.py:783`, `pixoo-display-test.py:789`, `pixoo-display-test.py:791`
- 状態ファイル読み込み側を read-only に保つ意図がコメントで明示されており、書き込み競合回避の設計判断が明確。
  - 参照: `pixoo-display-test.py:205`

## スコア 74/100

- 主な減点理由は、`/tmp` 状態ファイル入力に対する堅牢性不足（クラッシュ/DoS）と、同一キャラ複数体・sleep/wake 時の表示整合性の弱さ。
- 描画キャッシュ、送信最適化、再接続処理は良く、運用志向の改善は入っています。
