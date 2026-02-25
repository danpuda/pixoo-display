#!/bin/bash
# ensure-sprites.sh — WSL起動時にPixoo用スプライトを/tmpにコピー
# lobster-desktop-widget/assets/sprites/ → /tmp/lob64-*.png

SPRITES="/home/yama/lobster-desktop-widget/assets/sprites"
DEST="/tmp"

if [ ! -d "$SPRITES" ]; then
    echo "[ERROR] Sprite source not found: $SPRITES" >&2
    exit 1
fi

COPIED=0
for char in opus sonnet haiku gemini kusomegane codex grok; do
    for i in 1 2 3 4; do
        src="$SPRITES/${char}-frame${i}.png"
        dst="$DEST/lob64-${char}-frame${i}.png"
        if [ -f "$src" ] && [ ! -f "$dst" ]; then
            cp "$src" "$dst"
            ((COPIED++))
        fi
    done
done

# sleep frames
for i in 1 2 3 4; do
    src="$SPRITES/sleep-frame${i}.png"
    dst="$DEST/lob64-opus-sleep-frame${i}.png"
    if [ -f "$src" ] && [ ! -f "$dst" ]; then
        cp "$src" "$dst"
        ((COPIED++))
    fi
done

if [ "$COPIED" -gt 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Copied $COPIED sprite(s) to $DEST"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All sprites already in place"
fi
