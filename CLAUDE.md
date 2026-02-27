# CLAUDE.md — DEV指示書（あなたはDEV。コードを書いてcommitするまでが仕事）

## 🔴 絶対ルール
- **git push は絶対にするな。commitまでが仕事。pushはPL（別のSonnet）がやる**
- 既存ファイルはEdit必須（Write=全上書き→消失事故あり）

## タスク: ワーカー名スクロールの滑らかループ修正

### 問題
`advance_worker_scroll()` は末尾でPAUSE_TICKS分停止→offset=0にリセットするが、
リセット後に先頭がいきなり表示されるので「詰まった感じ」に見える。

### 要件
- 末尾に到達 → PAUSE → 先頭に巻き戻し → 先頭でもPAUSE → また右からスクロール
- ループが滑らかに繰り返されること
- スクロール速度はそのまま（SCROLL_SPEED_MS = 150）

### 実装方針
`advance_worker_scroll()` を修正:

```
offset 0 ~ stop_point: 通常スクロール（1px/tick左へ）
stop_point ~ stop_point+PAUSE: 末尾停止
stop_point+PAUSE+1: offset=0にリセット（先頭へ）
0 ~ PAUSE: 先頭停止（ここが新規追加！）
PAUSE+1 ~: また右からスクロール開始
```

要は「先頭でもN tick分停止してから動き出す」を追加するだけ。
方法: offsetに「負の値」を使う（-PAUSE ~ 0 は先頭停止、0以上は通常スクロール）
→ compose_frame側で `effective_offset = max(0, worker_scroll_offset)` にすればいい。

### テスト
- `python3 -m pytest tests/ -q` で全テスト全パス必須
- advance_worker_scrollのテストケース更新

### Git
- `git commit`（**pushしない！！！**）
- コミットメッセージ: `🔤 fix: ワーカー名スクロールに先頭PAUSE追加（滑らかループ）`
