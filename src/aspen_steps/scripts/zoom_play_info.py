#!/usr/bin/env python3
"""Fetch Zoom's player-info JSON for a cloud-recording share link.

Usage: zoom_play_info.py <share-or-play-url> <workdir>

Writes <workdir>/play_info.json: the `result` object of
/nws/recording/1.0/play/info/<fileId>. It holds the in-meeting chat
(`xmppList`), the recording start (`fileStartTime`, epoch ms) and the
screen-share on/off ranges (`vttRanges.share`). Download the video itself
with yt-dlp, which does this same dance; the stream URLs here return 403
to a plain request.

Share links no longer redirect to /rec/play/. The play page URL comes from
/nws/recording/1.0/play/share-info/<shareId> (`redirectUrl`); loading that
page sets the session cookies play/info needs. Stdlib only, so it runs with
any python3.

Passcodes: if share-info says the recording needs one, set ZOOM_PASSCODE (an
env var, so it stays out of process lists and logs). It's checked with
/nws/recording/1.0/validate-meeting-passwd, and the unlocked session's cookies
are saved to <workdir>/zoom_cookies.txt for `yt-dlp --cookies`. yt-dlp can't
do this itself: its --video-password only knows Zoom's older passcode form.
"""
import http.cookiejar
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


def get(opener, url, referer=None, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if referer:
        req.add_header("Referer", referer)
    if accept:
        req.add_header("Accept", accept)
    with opener.open(req, timeout=60) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def get_json(opener, url, referer):
    _, body = get(opener, url, referer, "application/json")
    data = json.loads(body)
    if not data.get("status"):
        sys.exit(f"Zoom API error from {url}: {data.get('errorCode')} {data.get('errorMessage')}")
    return data["result"]


def unlock(opener, origin, info, referer):
    """Submit ZOOM_PASSCODE for a share-info result that asks for one."""
    passcode = os.environ.get("ZOOM_PASSCODE")
    if not passcode:
        sys.exit("this recording needs a passcode: set ZOOM_PASSCODE")
    # Seen with useWhichPasswd=meeting. The recording-level variant is a guess
    # by analogy (yt-dlp's older form flow had both); untested.
    kind = "meeting-passwd" if info.get("useWhichPasswd") == "meeting" else "passwd"
    req = urllib.request.Request(
        f"{origin}/nws/recording/1.0/validate-{kind}",
        data=urllib.parse.urlencode({
            "id": info["meetingId"], "passwd": passcode, "action": info.get("action", ""),
        }).encode(),
        headers={"User-Agent": UA, "Accept": "application/json", "Referer": referer},
    )
    with opener.open(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if not data.get("status"):
        sys.exit(f"Zoom rejected the passcode: {data.get('errorCode')} {data.get('errorMessage')}")
    print("passcode accepted", flush=True)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    url, workdir = sys.argv[1], Path(sys.argv[2])
    workdir.mkdir(parents=True, exist_ok=True)

    jar = http.cookiejar.MozillaCookieJar(str(workdir / "zoom_cookies.txt"))
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))

    play_url = url
    share = re.search(r"/rec/share/([^/?#]+)", url)
    if share:
        _, page = get(opener, url)  # share page sets the initial cookies
        # yt-dlp keys share-info on the page's meetingId; the URL's share id also works
        mid = re.search(r"meetingId:\s*'([^']+)'", page)
        share_id = mid.group(1) if mid else share.group(1)
        info_url = f"{origin}/nws/recording/1.0/play/share-info/{share_id}"
        info = get_json(opener, info_url, url)
        if info.get("componentName") == "need-password":
            unlock(opener, origin, info, url)
            info = get_json(opener, info_url, url)
            if info.get("componentName") == "need-password":
                sys.exit("Zoom still asks for a passcode after accepting it")
            # Session cookies, so keep them though they have no expiry.
            jar.save(ignore_discard=True, ignore_expires=True)
        play_url = urllib.parse.urljoin(origin, info["redirectUrl"])

    final_url, html = get(opener, play_url, referer=url)
    fid = re.search(r"fileId:\s*'([^']+)'", html) or re.search(r"/rec/play/([^/?#]+)", final_url)
    if not fid:
        sys.exit(f"no fileId found on play page {final_url}")

    # Same query as yt-dlp. With canPlayFromShare=true instead, Zoom leaves
    # out viewMp4WithshareUrl, so the stream keys no longer match yt-dlp's formats.
    result = get_json(
        opener,
        f"{origin}/nws/recording/1.0/play/info/{fid.group(1)}?continueMode=true",
        final_url,
    )
    result["_playUrl"] = final_url
    (workdir / "play_info.json").write_text(json.dumps(result, indent=1))
    if Path(jar.filename).exists():  # unlocked with a passcode: keep the play page's cookies too
        jar.save(ignore_discard=True, ignore_expires=True)

    print(json.dumps({
        "fileId": fid.group(1),
        "topic": (result.get("meet") or {}).get("topic"),
        "fileStartTime": result.get("fileStartTime"),
        "duration": result.get("duration"),
        "hasTranscript": result.get("hasTranscript"),
        "chatMessages": len(result.get("xmppList") or []),
        # yt-dlp formats: viewMp4Url -> view (camera), shareMp4Url -> share
        # (screen share only), viewMp4WithshareUrl -> view_with_share (both)
        "streams": [k for k in ("viewMp4Url", "shareMp4Url", "viewMp4WithshareUrl") if result.get(k)],
        "shareRanges": (result.get("vttRanges") or {}).get("share"),
    }, indent=1))


if __name__ == "__main__":
    main()
