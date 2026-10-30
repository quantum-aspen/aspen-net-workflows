"""Fills a fresh mock-Outline state file with a small Meetings collection.

Usage: python dev/seed.py <state.json> [recording url]

Prints {"collection": id, "ready": id, …} so scripts can find the pages. Holds a series
with a summary table and an earlier summary, a series without a table, the Meeting
summary template, a roster, and recording pages in each state the poller must tell
apart. The template is modelled on the wiki's; check it against the real one.
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mock_outline import State, new_doc  # noqa: E402

TEMPLATE = """:::tip
Fill in every !!placeholder!!, then delete this box.
:::

| | |
|---|---|
| **Date** | !!YYYY-MM-DD!! |
| **Recording** | !!Zoom share link!! |
| **Attendees** | !!names!! |
| **Notes by** | !!who wrote these notes!! |

:::warning
An AI wrote this summary from the recording. Check anything important against the recording before acting on it.
:::

## Summary

!!Two or three sentences: what the meeting was about and what came out of it.!!

## Topics

### 1. !!Topic!!

!!What was discussed.!!

## Decisions

- !!Decision!!

## Action items

| Action | Owner | Due |
|---|---|---|
| !!Action!! | !!Owner or TBD!! | !!Due date or TBD!! |
"""

RECORDING = """Paste the Zoom recording's share link below. If it has a passcode, add a line `passcode: …`. Then tick the box.

{url}
passcode: {passcode}

- [{mark}] Ready to transcribe
"""


def main():
    path = Path(sys.argv[1])
    url = (
        sys.argv[2] if len(sys.argv) > 2 else "https://illinois.zoom.us/rec/share/SYNTHETIC-fixture-recording"
    )
    path.unlink(missing_ok=True)
    st = State(path)
    coll = str(uuid.uuid4())
    st.data["collections"].append({"id": coll, "name": "Meetings"})
    st.data["users"] = [
        {"id": str(uuid.uuid4()), "name": n, "email": f"{n.split()[0].lower()}@example.org"}
        for n in ("Gina Lorenz", "Krister Shalm", "Marcos Frenkel", "Jasper")
    ]
    st.data["templates"].append(
        {"id": str(uuid.uuid4()), "title": "Meeting summary", "text": TEMPLATE, "collectionId": coll}
    )

    stack = new_doc(st, "Software stack meeting", "", coll)
    earlier = new_doc(
        st,
        "2026-10-20 Deployment pipeline",
        "| | |\n|---|---|\n| **Date** | 2026-10-20 |\n\n## Summary\n\nWe agreed to deploy every service "
        "with doco-cd from the deployments repo, with secrets in SOPS.\n\n## Action items\n\n"
        "| Action | Owner | Due |\n|---|---|---|\n| Add the second admin's age key | TBD | TBD |\n",
        coll,
        stack["id"],
    )
    stack["text"] = (
        "Weekly meeting on ASPEN-NET's software: services, data paths, deployment.\n\n"
        "| Date | Summary | Topics |\n|---|---|---|\n"
        f"| 2026-10-20 | [2026-10-20 Deployment pipeline]({earlier['url']}) | doco-cd, SOPS secrets |\n"
    )
    detector = new_doc(st, "Detector working group", "Monthly check-in on detector hardware.", coll)

    ready = new_doc(
        st, "New recording", RECORDING.format(url=url, passcode="Fx7#k2", mark="x"), coll, stack["id"]
    )
    unticked = new_doc(
        st,
        "Not yet",
        RECORDING.format(url=url.replace("fixture", "later"), passcode="", mark=" "),
        coll,
        detector["id"],
    )
    orphan = new_doc(
        st, "Ticked but not under a series", RECORDING.format(url=url, passcode="", mark="x"), coll
    )
    st.save()
    print(
        json.dumps(
            {
                "collection": coll,
                "series": stack["id"],
                "ready": ready["id"],
                "unticked": unticked["id"],
                "orphan": orphan["id"],
            }
        )
    )


if __name__ == "__main__":
    main()
