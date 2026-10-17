#!/usr/bin/env bash
# Render poster.html to ../pitchdle-poster.pdf with headless Chrome. The fonts are local, so it works offline.
set -euo pipefail
cd "$(dirname "$0")"
"${CHROME:-google-chrome}" --headless=new --no-pdf-header-footer --print-to-pdf="../pitchdle-poster.pdf" \
  "file://$PWD/poster.html" 2>/dev/null
echo "Wrote $(cd .. && pwd)/pitchdle-poster.pdf"
