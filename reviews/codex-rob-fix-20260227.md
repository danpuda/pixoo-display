# ロブ🦞修正レビュー（commit `eb2476d`）

対象: `git show eb2476d`

## 先に結論（重要度順）

1. 🟡改善（item 3）: `determine_status` のフリッカー修正は前進だが、`last_change_times` をエラー時に更新し続けるため、`waiting -> error -> active -> waiting` のフリッカーが残るケースがあります（`pixoo_tmux_sync.py:123`, `pixoo_tmux_sync.py:140`）。
2. 🟢良い点（item 2）: 表示側の JSON 書き戻し削除で、sync daemon の atomic write 方針と責務分離が一致し、競合リスクを大きく下げています（`pixoo-display-test.py:205`）。
3. 🟢良い点（item 1）: Pixoo 送信失敗時にループ継続＋再接続リトライを入れたことで、即死回避として有効です（`pixoo-display-test.py:742`）。

---

## 1. Pixoo送信部 try/except + reconnect追加（`pixoo-display-test.py` 744付近）

**評価: 🟢良い点 + スコア 86/100**

- `pixoo.push()` 例外でプロセス全体が落ちる経路を潰せており、運用面の効果が大きいです（`pixoo-display-test.py:742`）。
- 5秒バックオフがあるので、切断中の高頻度例外ループを避けられます（`pixoo-display-test.py:747`）。
- 再接続失敗時も次フレームで再試行する設計は妥当です（`pixoo-display-test.py:752`）。

改善ポイント（軽微）:

- `Pixoo(PIXOO_IP)` は内部で接続検証失敗しても例外を投げずに戻る実装のため、`[i] Pixoo reconnected` ログが偽陽性になる可能性があります（ライブラリ挙動依存）。ログ文言は「reconnect attempted / object recreated」の方が正確です。
- `except Exception` が広く、通信以外の描画バグも同じ扱いになるため、将来的には送信系例外を分けると原因追跡しやすくなります。

## 2. `read_agent_state` のJSON書き戻し削除（`pixoo-display-test.py` 200付近）

**評価: 🟢良い点 + スコア 96/100**

- 表示側を read-only にしたのは正しいです。sync daemon 側の atomic write（`tempfile + os.replace`）方針と整合し、並行書き込み競合を避けられます（`pixoo-display-test.py:205`, `pixoo_tmux_sync.py:336`）。
- display 側は TTL を表示上の安全弁として使うだけなので、ここで永続化更新しない責務分離は明確です（`pixoo-display-test.py:198`）。
- コメントが具体的で、将来の再発防止に効きます（`pixoo-display-test.py:205`）。

注意点（仕様として許容可能）:

- sync daemon 停止中は期限切れ agent がファイル上に残り続けるため、TTL expired ログが表示側で毎回出続けます（挙動上のノイズ）。ただし今回の修正目的（競合排除）としては妥当です。

## 3. `determine_status` のエラー状態フリッカー修正（`pixoo_tmux_sync.py` 120付近）

**評価: 🟡改善 + スコア 68/100**

良い点:

- エラー時に `last_outputs` を更新しない変更は、エラー文字列を「通常出力の最新値」として記録しない点で筋が良いです（`pixoo_tmux_sync.py:121`）。
- 以前より `error -> active` の誤判定を減らせるケースがあります（エラー解除後に通常出力が本当に変化した場合の判定がより自然）。

残課題（今回の修正だけでは未解消）:

- エラー時に `last_change_times[window_name] = now` を更新しているため（`pixoo_tmux_sync.py:123`）、エラー解除後に出力がエラー前と同一でも、`now - last_change` が小さくなり `active` に戻ります（`pixoo_tmux_sync.py:140`-`pixoo_tmux_sync.py:144`）。
- そのため、`waiting -> error -> active -> waiting` のフリッカーは依然として発生し得ます（`WAITING_THRESHOLD_SEC` 30秒の間 `active` になりうる）。

再現イメージ:

1. 既に `waiting`（出力は長時間不変）
2. 一時的に `Traceback` が出て `error`
3. エラーが消えて、出力がエラー前と同じ不変テキストに戻る
4. `last_change_times` がエラー時刻に更新されているため `active`
5. 30秒後に再び `waiting`

改善案（参考）:

- 「フリッカー抑制」を優先するなら、エラー時は `last_outputs` だけでなく `last_change_times` も更新しない、またはエラー専用の時刻トラッキングを分離する方が確実です。

---

## 総評

- item 1 / item 2 は運用上の事故を減らす良い修正です。
- item 3 は方向性は正しいですが、コメントに書かれているレベルまでフリッカーを完全には抑え切れていません。次の小修正で詰める価値があります。
