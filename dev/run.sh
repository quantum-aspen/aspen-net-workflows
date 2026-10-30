#!/bin/sh
# End-to-end run on this machine: mock wiki, real Dagu, real skill scripts, real agent.
#
#   dev/run.sh            seed the mock wiki, start it and Dagu, tick-to-summary in one go
#   dev/run.sh up         just start the mock wiki and Dagu (UI on :18080), to click around
#
# The fixture (dev/make_fixture.py) stands in for the Zoom download: it's copied into the
# job's work dir, so fetch finds the media there and skips itself. Everything after that
# runs for real. AGENT=claude (default here) runs Claude Code on the logged-in account;
# the fixture is synthetic, so that's fine. WHISPER_MODEL=base keeps whisper quick.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEV="$ROOT/dev"
export DAGU_HOME="$DEV/.dagu"
export DATA_DIR="$DEV/data"
export SKILL_DIR="${SKILL_DIR:-$ROOT/../aspen-net-skills/skills/local-meeting-transcript}"
export OUTLINE_URL="http://127.0.0.1:3999" OUTLINE_API_KEY=dev
export AGENT="${AGENT:-claude}" WHISPER_MODEL="${WHISPER_MODEL:-base}" MENTIONS=1
export VIRTUAL_ENV="$ROOT/.venv" PATH="$ROOT/.venv/bin:$PATH"
export DAGU_COORDINATOR_ENABLED=false
cd "$ROOT"

[ -f "$DEV/fixture/meeting.wav" ] || {
  echo "no fixture: uv run --no-project --with edge-tts python dev/make_fixture.py dev/fixture $SKILL_DIR"
  exit 1
}

stop() { kill "$MOCK" "$DAGU" 2>/dev/null || true; }
trap stop EXIT INT TERM

rm -rf "$DATA_DIR" "$DAGU_HOME"
mkdir -p "$DATA_DIR" "$DAGU_HOME"
IDS=$(python3 "$DEV/seed.py" "$DATA_DIR/outline.json")
export MEETINGS_COLLECTION_ID=$(echo "$IDS" | jq -r .collection)
READY=$(echo "$IDS" | jq -r .ready)

# Dagu reads $DAGU_HOME/config.yaml: the repo's, plus what only makes sense locally.
{ cat "$ROOT/dagu.yaml"; printf '\ndags_dir: %s\nauth:\n  mode: none\n' "$ROOT/dags"; } > "$DAGU_HOME/config.yaml"

python3 "$DEV/mock_outline.py" "$DATA_DIR/outline.json" 3999 2> "$DATA_DIR/mock-outline.log" &
MOCK=$!
dagu start-all --port 18080 > "$DATA_DIR/dagu.log" 2>&1 &
DAGU=$!
sleep 3

if [ "${1:-}" = up ]; then
  echo "mock wiki :3999, Dagu UI http://127.0.0.1:18080 — ready page $READY. Ctrl-C to stop."
  wait "$DAGU"
fi

# Stand-in for fetch: the page's work dir already holds the "downloaded" media.
mkdir -p "$DATA_DIR/work/$READY"
cp "$DEV/fixture/"* "$DATA_DIR/work/$READY/"

echo "== poll"
dagu start meeting-poll
echo "== waiting for the meeting run"
for _ in $(seq 1 180); do
  S=$(dagu status meeting 2>/dev/null | grep -o 'Result: [A-Za-z ]*' | head -1 || true)
  case "$S" in *ucceeded*|*ailed*|*borted*|*artial*) break ;; esac
  sleep 10
done
dagu status meeting || true
echo "== the recording page now"
python3 - "$DATA_DIR/outline.json" "$READY" <<'EOF'
import json, sys
st = json.load(open(sys.argv[1]))
d = next(d for d in st["documents"] if d["id"] == sys.argv[2])
s = next(x for x in st["documents"] if x["id"] == d["parentDocumentId"])
print(f"# {d['title']}\n\n{d['text']}\n\n== series page: {s['title']}\n\n{s['text']}")
EOF
