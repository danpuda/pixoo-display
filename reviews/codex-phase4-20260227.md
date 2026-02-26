# Phase 4 コードレビュー（Codex）

対象: `pixoo_tmux_sync.py`, `pixoo-display-test.py`, `tests/test_tmux_sync.py`

## 🔴致命的

- なし

## 🟡改善

1. `waiting` 判定の閾値がコメント仕様と 1 poll 分ずれる（off-by-one）
   - `WAITING_THRESHOLD_SEC` のコメントは「この秒数になったら waiting」を示していますが、実装は `>` 比較なのでちょうど 30.0 秒では `active` のままです。
   - 参照: `pixoo_tmux_sync.py:29`, `pixoo_tmux_sync.py:145`
   - テストも `+1` 秒のケースしかなく、境界値（ちょうど閾値）を検証していません。
   - 参照: `tests/test_tmux_sync.py:166`
   - 影響: ステータス切替が 1 poll 遅れる可能性があり、表示仕様と実挙動がズレます。

2. `build_agents()` が `window_name` を ID/first_seen キーに使っており、同名 tmux window で衝突する
   - PL 選定では `window_index` を使って同名バグ回避している一方、`id`/`started`/`first_seen` は `window_name` ベースのままです。
   - 参照: `pixoo_tmux_sync.py:290`, `pixoo_tmux_sync.py:314`, `pixoo_tmux_sync.py:320`, `pixoo_tmux_sync.py:333`
   - 同名 window が同時に存在すると `id` が重複し、`started` も共有されます（再現確認済み）。ログの差分検知でも `set` 化で情報が潰れます。
   - 参照: `pixoo_tmux_sync.py:424`
   - 影響: 表示/監視側でエージェント識別が不安定になり、追加・削除判定や経過時間表示が誤る可能性があります。

3. Pixoo 初期化リトライが `try/except KeyboardInterrupt` の外にあり、起動中停止時の UX が悪い
   - 初期化失敗時のリトライ自体は良いですが、`time.sleep(5)` を含むリトライループがメイン `try` より前にあります。
   - 参照: `pixoo-display-test.py:518`, `pixoo-display-test.py:525`, `pixoo-display-test.py:568`
   - 影響: 起動時リトライ中に `Ctrl+C` した場合、通常ループ時のようなハンドリング（`[i] Stopped`）にならず traceback で落ちる可能性があります。加えて最終失敗後も 5 秒 sleep してから例外になるため失敗通知が遅れます。

4. `/tmp` の設定 JSON を無条件に信頼して読み込んでいる（ローカル多人数環境では改ざん余地）
   - `/tmp/pixoo-tmux-config.json` は誰でも書ける前提の場所で、所有者/権限チェックなしで読み込んでいます。
   - 参照: `pixoo_tmux_sync.py:27`, `pixoo_tmux_sync.py:151`
   - 影響: 同一ホストの他ユーザーが PL 指定を変えるなど、表示ロジックに干渉可能です（重大度は低いが、共有環境なら対策推奨）。

## 🟢良い点

- `determine_status()` の flicker 修正方針は妥当で、静的 error 出力時に `last_change_times` を更新しない回帰テストも追加されている。
  - 参照: `pixoo_tmux_sync.py:124`, `tests/test_tmux_sync.py:191`, `tests/test_tmux_sync.py:205`, `tests/test_tmux_sync.py:229`
- `write_state()` が `mkstemp + os.replace` で原子的に書き込んでおり、表示側との race を意識した実装になっている。
  - 参照: `pixoo_tmux_sync.py:340`
- `subprocess.run([...])` の引数配列化 + `timeout` 付きで、コマンドインジェクション/ハング耐性の基本ができている。
  - 参照: `pixoo_tmux_sync.py:72`, `pixoo_tmux_sync.py:227`, `pixoo-display-test.py:279`
- `tests/test_tmux_sync.py` は role 判定・sanitize・flicker 回帰・window 増減までカバーしており、回帰防止としてかなり有効。

## スコア 84/100

- 主な減点理由は、境界値の仕様ズレ（waiting 閾値）と同名 window 衝突の識別不整合。
- 致命的クラッシュ級は見当たらず、全体としては堅実。`pytest -q tests/test_tmux_sync.py` は手元で `50 passed`。
