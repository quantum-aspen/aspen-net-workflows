"""`aspen-steps <step> [doc id]`: one command per workflow step.

Exit codes tell Dagu what to do next: 0 done, 1 worth retrying, 2 needs a person
(retrying won't help). A failing step also writes its reason to errors/<step>.txt in
the work dir, which the failure handler puts on the recording page. One file per step,
because steps run in parallel and one's success mustn't erase another's failure."""

import argparse
import logging
import sys

from . import media, meeting, review
from .config import Config
from .errors import NeedsPerson
from .outline import OutlineError

# What the recording page says while each step runs.
PROGRESS = {
    "window": "queued",
    "fetch": "working: downloading the recording",
    "transcribe": "working: transcribing",
    "review": "working: checking the transcript",
    "summarise": "working: writing the summary",
    "publish": "working: publishing",
}

PER_MEETING = {
    "window": lambda cfg, wd: meeting.wait_for_window(cfg),
    "fetch": media.fetch,
    "transcribe": media.transcribe,
    "review": review.review,
    "frames": media.frames,
    "context": meeting.context,
    "summarise": meeting.summarise,
    "publish": meeting.publish,
    "clean": lambda cfg, wd: media.clean(wd),
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="aspen-steps")
    ap.add_argument("step", choices=["poll", "claim", "fail", *PER_MEETING])
    ap.add_argument("doc_id", nargs="?")
    args = ap.parse_args(argv)
    cfg = Config.from_env()

    if args.step == "poll":
        meeting.poll(cfg)
        return 0
    if not args.doc_id:
        ap.error(f"{args.step} needs the recording page's document id")
    if args.step == "fail":
        meeting.fail(cfg, args.doc_id)
        return 0
    if args.step == "claim":  # poll does this for each ticked page; by hand, for trying one out
        try:
            print(meeting.claim(cfg, args.doc_id).name)  # the page's id, for DOC_ID
        except NeedsPerson as e:
            print(f"can't claim it: {e}", file=sys.stderr)
            return 2
        return 0

    wd = cfg.work_dir(args.doc_id)
    if not (wd / "job.json").exists():
        print(f"no job for {args.doc_id}: {wd / 'job.json'} is missing (claim writes it)", file=sys.stderr)
        return 2
    try:
        if msg := PROGRESS.get(args.step):
            try:
                meeting.status(cfg, args.doc_id, msg)
            except OutlineError as e:  # progress is nice to have; the step still runs
                print(f"couldn't update the page's status: {e}", file=sys.stderr)
        PER_MEETING[args.step](cfg, wd)
    except NeedsPerson as e:
        meeting.record_error(wd, args.step, str(e))
        print(f"needs a person: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — every other failure is worth a retry
        meeting.record_error(wd, args.step, f"{args.step}: {e}")
        print(f"{args.step} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    (wd / "errors" / f"{args.step}.txt").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
