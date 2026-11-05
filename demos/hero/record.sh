#!/bin/bash
# The README hero, end to end: the terminal take (a stack made, then
# started), the stack seeded, the Overseer take, the two stitched with a
# short crossfade, and the README's copies made from that.
#
#   demos/hero/record.sh [all|terminal|overseer|stitch]
#
# Each take is kept in TAKES (default: aegis-hero in the temp folder), so a
# change to one re-records only that one: `overseer` records against the
# stack already running, `stitch` only re-joins what is there.
#
# Records the aegis-demo stack in DEMO_DIR (default: ../aegis-demo beside
# this checkout), set up once beforehand: its .env holding a model key and
# AI_CHAT_SHOW_CALLS=false, its agent named Illiana on her model. `all` and
# `terminal` stop and restart it; its Redis keeps no data, so the metrics are
# seeded after the boot, not before.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DEMO_DIR="${DEMO_DIR:-$(cd "$REPO/.." && pwd)/aegis-demo}"
TAKES="${TAKES:-${TMPDIR:-/tmp}/aegis-hero}"
STEP="${1:-all}"
FADE=0.4
mkdir -p "$TAKES"
cd "$DEMO_DIR"

url() {
  echo "http://127.0.0.1:$(docker compose port webserver 8000 | cut -d: -f2)"
}

terminal() {
  echo "Stopping and building the stack..."
  make stop >/dev/null
  make build >/dev/null
  echo "Recording the terminal take..."
  local work
  work="$(mktemp -d)"
  (cd "$work" && AEGIS_REPO="$REPO" DEMO_PARENT="$(dirname "$DEMO_DIR")" vhs "$HERE/terminal.tape")
  mv "$work/terminal.mp4" "$TAKES/terminal.mp4"
  rm -rf "$work"

  echo "Waiting for $(url)..."
  until curl -sf "$(url)/health" >/dev/null; do sleep 2; done
  # A minute of real samples first: the seeder fills back from each series'
  # oldest point, and a series not yet sampled is not there to fill.
  echo "Sampling, then seeding the charts and the errors..."
  sleep 60
  docker compose exec -T webserver python - <"$HERE/seed_metrics.py"
  uv run aegis-demo load-test run -t failure_testing -n 20 --no-wait >/dev/null 2>&1
  sleep 10
}

overseer() {
  echo "Recording the Overseer take..."
  local at
  at="$(url)"
  (cd "$REPO" && uv run --no-project --with playwright python -I "$HERE/overseer.py" "$at" "$TAKES/overseer")
}

stitch() {
  echo "Stitching..."
  local length
  length="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TAKES/terminal.mp4")"
  ffmpeg -loglevel error -y -i "$TAKES/terminal.mp4" -i "$TAKES/overseer/overseer.mp4" \
    -filter_complex "[0:v]fps=60,format=yuv420p[a];[1:v]fps=60,format=yuv420p[b];[a][b]xfade=transition=fade:duration=$FADE:offset=$(echo "$length - $FADE" | bc)[v]" \
    -map "[v]" -c:v libx264 -preset slow -crf 16 -movflags faststart "$TAKES/hero.mp4"
  # The README's copies: an animated WebP for GitHub (it plays no repo-path
  # video), the MP4 the docs site plays in its place (scripts/gen_docs.py).
  ffmpeg -loglevel error -y -i "$TAKES/hero.mp4" -vf "scale=1920:1080:flags=lanczos,fps=30" \
    -c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p -movflags faststart -an "$REPO/docs/images/aegis-hero.mp4"
  # Full 1080p from the master, since GitHub opens a clicked image at its
  # own size; quality high enough that the near-black stays clean (~15 MB).
  ffmpeg -loglevel error -y -i "$TAKES/hero.mp4" -vf "fps=15,scale=1920:-1:flags=lanczos" \
    -c:v libwebp_anim -lossless 0 -quality 95 -compression_level 6 -preset text -loop 0 -an "$REPO/docs/images/aegis-hero.webp"
  echo "Wrote $TAKES/hero.mp4 ($(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TAKES/hero.mp4")s) and docs/images/aegis-hero.{mp4,webp}"
}

case "$STEP" in
  all) terminal; overseer; stitch ;;
  terminal) terminal; stitch ;;
  overseer) overseer; stitch ;;
  stitch) stitch ;;
  *) echo "usage: $0 [all|terminal|overseer|stitch]" >&2; exit 2 ;;
esac
