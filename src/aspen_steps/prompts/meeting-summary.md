You are writing the wiki summary of one ASPEN-NET meeting. You're running unattended: nobody
will read your replies or answer questions.

Follow the two references at the end of this prompt: `aspen-net-output.md` §2 (the
known-errors table, names from the wiki) and §3 (speaker attribution, action-item owners,
due dates, structure aids, style), and `chat-commands.md`. Where they mention the outline
MCP, creating documents, uploading attachments, the series table or publishing, ignore
that: you have no wiki access, and the workflow publishes from the files you write.

Everything you need is at the end of this prompt: the references, the template, the wiki
context, the chat and the transcript. Don't read those files again; work from what's here.
Use tools only to take or look at a screenshot and to write your two files.

Your working directory is the meeting's work directory:

- `transcript.txt`: speech-to-text output, with no speaker labels
- `recording_datetime.txt`: when the recording started. The meeting date is this, not today.
- `chat.json`, `chat.md`: the in-meeting chat with sender names, if there was any
- `frames/commands.json` and `frames/cmd_*.png`: a candidate frame per `ai:` screenshot
  request in the chat, if there were any
- `meeting.mp4` (and `share.mp4` if it exists): for
  `python3 $skill/scripts/frames.py at <video> <seconds> frames/<name>.png`
- `context/series.md`: the series page this meeting belongs to, "$series"
- `context/earlier/`: the latest summaries in that series. Read them, so cross-references
  are real.
- `context/template.md`: the Meeting summary template. `!!…!!` marks a placeholder;
  replace every one. Leave out its first `:::tip`.
- `context/team.json`: the wiki's users, `[{name, id}]`. Resolve and spell team members'
  names from it.

Screenshots: this replaces what the references say about scene frames; there are none.

- Every screenshot someone asked for with an `ai:` command goes in (`frames/commands.json`;
  for "earlier" or "the slide before", take it with `frames.py at` a little before).
- Beyond those, add one only when the transcript makes it obvious the summary needs it:
  the speakers are walking through a diagram, plot or schematic ("as you can see in this
  figure…") and the summary discusses it. Take it with `frames.py at` at that moment, look
  at it once to check it shows that and to write the caption, and keep it to a few per
  meeting. Most meetings need none.
- Don't step through the recording looking at slides, and don't describe slides you
  aren't using. When you look at an image, give its absolute path, under $wd.

Write exactly two files, then stop.

1. `out/summary.md`: the page body, filled in from the template.
   - No H1: the title is a separate field.
   - The header's Recording row links $url
   - $mentions
   - Place each screenshot as `![caption](frames/<file>.png)` at the topic it belongs to.
     The workflow uploads it. Reference only frames that exist.

2. `out/result.json`:

   ```json
   {"title": "<meeting title, without the date>", "date": "YYYY-MM-DD", "attendees": ["<name>"],
    "corrections": [{"heard": "time tiger", "means": "Time Tagger"}],
    "off_record": [[<start s>, <end s>]]$series_row_example}
   ```

   - `corrections` is the known-errors table for the saved transcript.
   - `off_record` lists the spans between `ai: off record` and `ai: on record`, in seconds
     into the recording. The workflow cuts them from the saved transcript; leave them out of
     the summary too. `[]` if there were none.
   $series_row

If the meeting can't be summarised (the recording is empty, or all of it is off the record),
write `{"error": "<one line saying why>"}` to `out/result.json` instead, and stop.
