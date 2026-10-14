#!/usr/bin/env bash
# Stitch the demo screenshots in docs/demo/ into a captioned walkthrough (GIF + MP4). Needs ffmpeg.
set -euo pipefail
cd "$(dirname "$0")/../docs/demo"
FONT=${FONT:-/System/Library/Fonts/SFNS.ttf}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

frames=(
  "01-scenarios.png|1/6  All 7 scenarios, LLM-agent approver (deterministic model): every expectation met"
  "05-report-misleading-careful.png|2/6  Misleading message: approver checks the registry, ignores the claim, rejects"
  "02-control-guarded.png|3/6  Negative control: a gullible approver tries to approve on the claim"
  "06-report-misleading-gullible-guarded.png|3/6  ...the policy guard blocks it, and the verifier still flags the attempt"
  "03-control-unguarded.png|4/6  Guard OFF: the approval executes"
  "07-report-misleading-gullible-unguarded.png|4/6  ...and the verifier marks the outcome NON-COMPLIANT from the trace"
  "08-report-forgery-attempt.png|5/6  Requester tries to forge an authorization and self-approve: denied + detected"
  "04-report-overview.png|6/6  HTML report: verdicts re-derived by replaying JSONL traces"
)

i=0
for entry in "${frames[@]}"; do
  img=${entry%%|*}; caption=${entry#*|}
  printf '%s' "$caption" > "$TMP/cap$i.txt"
  ffmpeg -loglevel error -y -i "$img" -vf "\
scale=w='min(1240,iw)':h='min(760,ih)':force_original_aspect_ratio=decrease,\
pad=1280:840:(ow-iw)/2:70+(760-ih)/2:color=0xF2F2F0,\
drawbox=x=0:y=0:w=1280:h=56:color=0x1D1D24:t=fill,\
drawtext=fontfile=$FONT:textfile=$TMP/cap$i.txt:fontcolor=white:fontsize=22:x=24:y=17" "$TMP/f$(printf %02d $i).png"
  i=$((i+1))
done

ffmpeg -loglevel error -y -framerate 1/3.5 -i "$TMP/f%02d.png" \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer" \
  -loop 0 demo.gif
ffmpeg -loglevel error -y -framerate 1/3.5 -i "$TMP/f%02d.png" -vf "fps=25,format=yuv420p" -c:v libx264 -movflags +faststart demo.mp4
ls -lh demo.gif demo.mp4
