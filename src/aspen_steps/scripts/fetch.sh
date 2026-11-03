#!/bin/sh
# Fetch a Zoom (or any yt-dlp-supported) recording and check for a real
# captions track before committing to local transcription.
#
# For Zoom links it also saves Zoom's player info (play_info.json) and the
# in-meeting chat (chat.json, chat.md), and downloads the screen-share-only
# stream (share.mp4) when the host recorded one.
#
# Passcode-protected Zoom recordings: set ZOOM_PASSCODE. zoom_play_info.py
# unlocks the recording and saves the session cookies, which every yt-dlp call
# then uses. The cookies are deleted at the end.
#
# Usage: fetch.sh <url> <workdir>
set -e
URL="${1:?usage: fetch.sh <url> <workdir>}"
D="${2:?usage: fetch.sh <url> <workdir>}"
S=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$D"
cd "$D"

echo "$URL" > url.txt

# Zoom first: a passcode unlock has to happen before yt-dlp can see the recording.
DATE_STAMP=""
COOKIES=""
trap 'rm -f zoom_cookies.txt' EXIT
case "$URL" in
  *zoom.us/rec/*)
    echo "=== Zoom player info and chat ==="
    python3 "$S/zoom_play_info.py" "$URL" .
    python3 "$S/chat.py" play_info.json .
    DATE_STAMP=$(jq -r '.fileStartTime / 1000 | strftime("%Y-%m-%d %H:%M:%S GMT")' play_info.json)
    [ -f zoom_cookies.txt ] && COOKIES="--cookies zoom_cookies.txt"
    ;;
esac

echo "=== checking for existing captions/subs ==="
timeout 90 yt-dlp $COOKIES --list-subs --no-warnings "$URL" || true
echo "(if a real language track appears above — not just 'chapter' — prefer"
echo " 'yt-dlp --write-subs --sub-langs <lang>' over transcribing from audio)"

echo "=== pulling metadata (title, duration) ==="
timeout 120 yt-dlp $COOKIES -J --no-warnings "$URL" > info.json
jq '{title, duration, ext}' info.json

# yt-dlp's upload_date/timestamp are null for Zoom shares. The recording
# start is also embedded in the CDN filename yt-dlp resolves, e.g.:
#   .../GMT20260827-171318_Recording_....mp4  ->  2026-08-27 17:13:18 GMT
if [ -z "$DATE_STAMP" ]; then
  REC_URL=$(jq -r '.url // .requested_downloads[0].url // empty' info.json)
  DATE_STAMP=$(echo "$REC_URL" | grep -oE 'GMT[0-9]{8}-[0-9]{6}' | head -1 | sed -E 's/GMT([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})/\1-\2-\3 \4:\5:\6 GMT/')
fi
if [ -n "$DATE_STAMP" ]; then
  echo "$DATE_STAMP" > recording_datetime.txt
  echo "recording datetime: $DATE_STAMP"
else
  echo "WARNING: could not work out the recording datetime — check info.json manually"
fi

echo "=== downloading recording ==="
timeout 900 yt-dlp $COOKIES -o "meeting.mp4" --no-warnings --no-progress "$URL"
ls -la meeting.mp4

# Frames for screenshots come from the screen-share-only stream if the host
# recorded one (play info shareMp4Url, yt-dlp format `share`). Otherwise
# frames.py uses meeting.mp4: yt-dlp's default `view_with_share` (share plus
# camera) when it exists, else `view` (camera).
if [ -f play_info.json ] && jq -e '.shareMp4Url' play_info.json >/dev/null; then
  echo "=== downloading screen-share-only stream ==="
  timeout 900 yt-dlp $COOKIES -f share -o "share.mp4" --no-warnings --no-progress "$URL"
fi

echo "=== extracting 16kHz mono WAV for Whisper ==="
ffmpeg -y -loglevel error -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le meeting.wav
ffprobe -v error -show_entries format=duration -of csv=p=0 meeting.wav

echo "FETCH_DONE"
