# aspen-net-workflows

ASPEN-NET's [Dagu](https://dagu.sh) workflows, and the `aspen-steps` commands their steps
run. **Prototype.** Its first workflow is a redesign of
[aspen-net-transcriber](https://github.com/quantum-aspen/aspen-net-transcriber): Zoom
recording in, meeting summary on the [wiki](https://wiki.quantum-aspen.net) out.

## How people use it

Recordings no longer go in one shared inbox doc. Each meeting gets its own page, under its
series:

1. In the Meetings collection, open the series (e.g. *Software stack meeting*) and add a
   child page from the **Meeting recording** template.
2. Paste the Zoom share link. If the recording has a passcode, add a line
   `passcode: <code>`. Zoom's own share text (`Link: <title> <url>` then
   `Passcode: <code>`) works as pasted.
3. Tick **Ready to transcribe**.

Within 5 minutes the box turns into a status callout: `queued`, then `working: …`. When
the summary is ready **it replaces the page**: the page you made becomes the meeting's
summary, titled `YYYY-MM-DD <Meeting title>`, and gets a row in the series page's table.
A series page without a table gets one (`## Meetings`: Date, Meeting, Key outcomes).

If something goes wrong, the callout says why and an unticked box comes back. Fix what it
says (a missing passcode, say) and tick it again. The run resumes from the last finished
step.

The series is wherever you put the page, so there's no guessing a series from the meeting
content. A ticked page that isn't directly under a series page is ignored.

The Meeting recording template is `templates/meeting-recording.md`. It has to be added to
the wiki by hand.

## Workflows

| DAG | What |
|---|---|
| `meeting-poll` | Every 5 min: claims ticked recording pages and queues a `meeting` run for each |
| `meeting` | One recording page to a published summary. By hand: `aspen-steps claim <page id>`, then start it with `DOC_ID=<page id>`. `DRY_RUN=1` records its wiki writes instead of making them |

```
meeting-poll ──enqueue──▶ meeting(DOC_ID)

window ─▶ fetch ─▶ transcribe ─▶ review ─▶ frames ─┐
             └──▶ context ───────────┘                ├─▶ summarise ─▶ publish
                             └────────────────────────┘
on failure: fail (reason + retry box on the page)    on exit: clean (delete media)
```

Meeting runs go one at a time (Dagu's per-DAG queue), so whisper never runs twice at once.
`window` holds the run until `RUN_HOURS`.

**Logs:** each step's output is in Dagu's run logs, and also in the container's log
(so Grafana), every line prefixed with the step and the page: `[transcribe 9ab305e4] …`.
`bin/start-workflows` makes the FIFO that carries them there (`console.py`).

**Exit codes** decide retries: 0 done, 1 retry with backoff, 2 a person has to fix
something (wrong passcode, no template, the agent says it can't summarise). Steps skip work
whose output already exists, so retries and re-ticks are cheap.

**Only `summarise` has a model in it.** The agent works on files: `context` writes what it
would otherwise read from the wiki (the series page, the latest summaries in the series, the
template, the roster) into the work dir. The agent writes `out/summary.md` and
`out/result.json`. It has no wiki tools, and `OUTLINE_API_KEY` is removed from the
environment it's started with, but that doesn't yet keep the key from it (see *Not done
yet*). `summarise` checks what it wrote (`check.py`):

- the recording date
- no H1 and no template placeholders
- @mentions only of people on the roster
- screenshots that exist
- series-table columns that exist

Any problems go back to the agent once. Only then does `publish`, which is plain code,
upload the frames, rewrite the page, add the series row, and save the local transcript
folder.

`AGENT` picks the harness: `hermes` (production, on Lumen), or `claude` (Claude Code on the
machine's logged-in account, for development).

## Layout

```
dags/            the workflows
dagu.yaml        Dagu server config (env passthrough, timezone)
base.yaml        defaults every DAG inherits (none yet)
src/aspen_steps/ one command per step: aspen-steps <step> [doc id]
  page.py        the recording-page protocol: link, passcode, tick box, status callout
  meeting.py     poll, claim, context, summarise, publish, status
  media.py       fetch, transcribe, frames: runs scripts/
  asr.py         transcription on Lumen's speech model, in timed chunks
  review.py      re-checks a Lumen transcript's misheard-looking chunks with whisper
  agent.py       unattended agent runs, hermes or claude
  check.py       the agent's output shape and the checks it must pass
  outline.py     the wiki API, and the dry run: writes recorded, not made
  prompts/       the summary prompt, its rules (summary-rules.md, chat-commands.md) and
                 whisper's glossary
  scripts/       download (fetch.sh), whisper, chat, frames: from the
                 local-meeting-transcript skill once, now this repo's own
templates/       the Meeting recording template, to add to the wiki by hand
tests/           pytest on the steps' own logic, with a checked-in work dir
```

## Development

There's no stand-in wiki. The steps run against the real one in a **dry run**: they read
it as usual, but each write (a page update, an upload) is recorded in the job's
`would-write/<page id>/` in the data dir instead, as the new page text and a diff against what's there now. Any
recording page with a Zoom link works, even one that's already been summarised, and
nothing on the wiki changes. Your own Outline API key (the one the Outline MCP uses) is
fine for this.

```sh
just test                # pytest, ruff

cp .env.example .env     # your Outline key, the Meetings collection id, Lumen
just up                  # build and start the image; Dagu UI on http://127.0.0.1:18080
just try <page id>       # claim the page and run the meeting workflow on it
ls .data/would-write/<page id>/
```

`just up` runs only Dagu's UI server, not its scheduler, so `meeting-poll` doesn't fire.
`dags/` and `src/` are mounted, so edits apply without a rebuild. Set `DRY_RUN=0` in
`.env` only when you mean to write to the wiki.

## Configuration

| Var | Default | |
|---|---|---|
| `OUTLINE_URL`, `OUTLINE_API_KEY` | wiki.quantum-aspen.net | the bot's key; steps only |
| `MEETINGS_COLLECTION_ID` | | |
| `DATA_DIR` | `/opt/data` | `work/<doc id>/`, `meetings/`, `hf/` |
| `TRANSCRIBER` | `whisper` | `whisper`: `scripts/transcribe.py`, locally. `lumen`: Lumen's speech model, in timed chunks (`asr.py`) |
| `WHISPER_MODEL` | `large-v3-turbo` | `TRANSCRIBE_*` as in `scripts/transcribe.py` |
| `LUMEN_BASE_URL`, `LUMEN_API_KEY` | lumen.ncsa.illinois.edu/v1 | for Hermes, and for `TRANSCRIBER=lumen` |
| `LUMEN_ASR_MODEL` | | e.g. `granite-speech-4.1-2b-plus` |
| `LUMEN_VISION_MODEL` | | e.g. `gemma-4-31b-it`; without it the agent has no vision tool |
| `ASR_CHUNK_SECONDS`, `ASR_CONCURRENCY` | 30, 4 | chunk length (cut in pauses) and requests at once |
| `REVIEW` | `auto` | with `TRANSCRIBER=lumen`, re-check misheard-looking chunks with whisper (`review.py`); `0` turns it off |
| `REVIEW_MODEL` | hermes' `AGENT_MODEL` | the Lumen model that reads the transcript for misheard lines |
| `REVIEW_MAX_SHARE` | 0.5 | most of the meeting the re-check may cover |
| `TRANSCRIBE_PROMPT` | from `prompts/glossary.txt` | whisper's vocabulary; edit the glossary to add terms |
| `RUN_HOURS` | any time | e.g. `20-6`, container clock (`TZ`) |
| `AGENT`, `AGENT_MODEL` | `hermes` | for hermes, the Lumen model id (e.g. `deepseek-v4.1-flash`); `claude` for dev |
| `AGENT_MAX_TURNS`, `AGENT_BUDGET_SECONDS` | 90, 2700 | |
| `MENTIONS` | on | @mention attendees and owners |
| `DRY_RUN` | off | read the wiki, record writes in `would-write/` |

## Not done yet

- **The agent can still reach the Outline key.** It runs as the same `hermes` user as Dagu
  and the steps, so its terminal tool can read the key from Dagu's `/proc/<pid>/environ`
  or from `/run/s6/container_environment/OUTLINE_API_KEY` (world-readable). Hermes 0.22 also
  runs every `hermes chat` turn in its gateway, which s6 starts with the whole container
  env, and Hermes' terminal tool doesn't strip non-provider keys. The fix: Dagu and the
  steps on their own user, the key in a file only that user reads, and the agent started
  as `hermes` through a narrow sudo rule.

- **Hermes on Lumen is untested.** `summarise` writes Hermes' config (Lumen for the model
  and vision, no MCP servers) and Hermes reads it, but no run has gone through Lumen yet.
- **Lumen transcription mishears terms and numbers.** On a 38-minute talk granite-speech
  wrote "45-femtosecond lock" for 40 and "10 seconds" for femtoseconds, and Lumen ignores
  a vocabulary prompt. `review` re-checks the suspect chunks with whisper: flagged by a
  model's read-through, near misses of glossary terms, and numbers that differ from
  Zoom's own transcript when there is one. Of the model's flags only numbers and units
  are re-checked. On the test meeting that's 24% of it, and it fixed all of them in about
  3 min, against 7.3 min for whisper on everything (4 CPU cores). Timestamps are per chunk.
- **The real wiki is untested.** The prototype checked its Outline calls against a mock.
  A dry run covers the reads (`templates.list` and `collections.documents` are the ones to
  watch); attachment upload only runs for real.
- **Polling is slow and only sees recent edits.** It looks at the 100 most recently updated
  docs in the collection. An Outline webhook calling a Dagu webhook would make it instant.
- **The Dagu UI needs protecting** before it's exposed: Cloudflare Access, as for Grafana.
