# `ai:` chat commands

Adapted from the local-meeting-transcript skill's `chat-commands.md`; this copy is the
workflow's own.

Nobody's agent is live in the meeting. Attendees type chat messages that start with `ai:`,
and you read them from the recording afterwards, so each one works as a bookmark at the
moment it was sent.

## Reading a command

A message is a command only if it starts with `ai:` (any case, leading spaces ignored).
Read everything after the prefix for **intent, not exact syntax**. People won't remember a
vocabulary, so `ai: screenshot`, `ai: screengrab`, `ai: snap`, `ai: grab this slide`,
`ai: capture` and `ai: pic of the diagram pls` all mean the same thing. If a command really
is unclear, say so in the summary's Chat section rather than guessing.

| Intent | Examples | What to do |
|---|---|---|
| Screenshot now | `ai: screenshot`, `ai: snap`, `ai: capture this` | Use its candidate frame from `frames/commands.json` |
| Screenshot earlier | `ai: screenshot 2 min ago`, `ai: grab the slide from before` | `frames.py at <video> <t − offset> frames/<name>.png`. For "the slide before", find in the transcript when the speaker moved on, and take the frame just before that |
| Note for the summary | `ai: note we're going with SOPS`, `ai: action item Marcos gets SSH access` | Put it in the summary as written: a decision, an action item, or a note. Name only the people the text names |
| Off the record | `ai: off record` … `ai: on record` | Leave everything between the two out of the summary, and list the span in `off_record`. An unclosed span runs to the end of the recording |

Any text after the intent is the caption: `ai: screenshot the topology figure`. Ignore the
candidate frame for any command that isn't a screenshot request.

## Timing

`t` in `chat.json` is seconds into the recording. The candidate frame is from just before the
message: people type after they've seen something, so if the screen changed in the last 2 s
it's the frame from before the change. `frames.py at` does the same.

## In the summary

Place each kept frame at the matching point in the discussion, captioned with the request
and the sender's name: *"Topology figure — screenshot requested by Marcos Frenkel (42:10)"*.
Zoom records sender names with each message, so naming the requester is reliable, unlike
guessing speakers from audio.
