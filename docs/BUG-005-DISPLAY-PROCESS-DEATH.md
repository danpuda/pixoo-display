# BUG-005: display-testプロセス死亡問題

## 症状
`pixoo-display-test.py` が起動後すぐに死ぬ。  
一方で `pixoo_agent_sync.py` は正常に生き残る。

## 原因
`nohup` でバックグラウンド起動するとプロセスが終了する。  
TTY/stdin周りの問題と推測される。

## 修正方法
`nohup` → `setsid` に変更することで解決。

### ❌ これだと死ぬ
```bash
nohup python3 -u pixoo-display-test.py > /tmp/pixoo-display-test.log 2>&1 &
```

### ✅ これで安定
```bash
setsid python3 -u pixoo-display-test.py > /tmp/pixoo-display-test.log 2>&1 &
```

## 追加問題
`/tmp/lob64-*.png` フレームファイルがWSL再起動で消える（volatile）。  
永続化が必要。

## 発見日
2026-02-22 06:00 JST

## ステータス
✅ 修正済み（setsid導入）  
⚠️ フレームファイル永続化は未対応
