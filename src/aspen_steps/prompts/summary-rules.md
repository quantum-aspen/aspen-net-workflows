# Summary rules

How an ASPEN-NET meeting summary is written. Adapted from the local-meeting-transcript
skill's `aspen-net-output.md`; this copy is the workflow's own.

## Speaker attribution: the rule that matters most

The transcript has no speaker labels, and you can't see where one speaker stops and the
next starts. Naming the wrong person as the source of an idea does real damage. Name
someone only when, for the exact lines in question:

- they're presenting their own work (a guest describing their lab, someone presenting
  their own system);
- they say who they are ("This is Mike in Oregon");
- they answer a question put to them by name, and nothing in between suggests another
  voice;
- an action item is assigned to them by name.

A name said near a line doesn't tell you who said it. "Paul has his hand up", "I think
Paul has a comment" and "sorry, Paul" introduce or interrupt someone, and the next words
may well be someone else's, often the person cutting in. Being an attendee isn't evidence
either.

Otherwise don't attribute. Write "it was raised that…" or "one view was…", and leave quotes
unattributed. Don't write per-person "positions" sections. If two views conflicted, present
both without names. When unsure, leave the name out.

## Action-item owners

Owners follow the same rule, and it's where summaries most often go wrong. Give an owner
only when the exchange itself names them taking the task: "Marcos, can you…" and they
agree, or they say they'll do it and are named in that exchange. Otherwise the owner is
**TBD**. Don't infer an owner from:

- who posted something related in chat;
- whose system or document it concerns;
- who seemed to be speaking.

A wrong owner is worse than TBD: people act on it, or assume someone else has it.

**Due dates** work the same way: give one only if it was said in the meeting ("by Friday",
"next week"). Otherwise it's TBD. Don't derive one from other pages, such as an upcoming
retreat.

## Names

The team roster is `context/team.json` (`[{name, id}]`, the wiki's users). Use it to:

- resolve misheard names to a real person, e.g. "christer" → Krister → Krister Shalm;
- spell full names, and get the user ids for @mentions.

Names that aren't on the roster are fine: guests, collaborators, people talked about.
Write them as your best guess at what was said. Being on the roster doesn't mean someone
attended. List as attendees only people the meeting shows were there: they spoke and were
named by the rules above, they're in the chat, or they were addressed as present.

## Known transcription errors

`corrections` in `out/result.json` becomes the known-errors table at the top of the saved
transcript, and readers take each row as fact. Add a row only when you know what was said:

- it's in the table below;
- it's a team member's name (`context/team.json`);
- the meeting itself shows the right word: a slide, the chat, a clearer mention elsewhere
  in the transcript.

If you'd be guessing, leave it out: a misheard word left as it is does less harm than a
wrong correction. Use the same rule wherever you fix a term in the summary.

Substitutions seen in earlier meetings:

| Transcript says | Means |
|---|---|
| "add a second layer", "out of second", "autosecond", "Adosecond", "add-a-second", "add to second", "auto second" | **attosecond** (layer) |
| "time tiger", "time tigers", "time takers" | **Time Tagger** (Swabian) |
| "Aspenet", "AspenNet", "Aspen.net", "Aspen net", "us Bennett" | **ASPEN-NET** |
| "PQM", "PQ and" | **PQN** |
| "christer", "Chris or", "Cristopher" | **Krister** |
| "CMQ" | **ZeroMQ / ZMQ** |
| "NetCasm" | **NetQASM** |
| "pgas", "fbga" | **FPGA(s)** |
| "hungamandel", "hung mandel" | **Hong-Ou-Mandel** |
| "hom dip", "homedip", "hand dips" | **HOM dip(s)** |
| "beamsuit" | **beam splitter** |
| "endnotes" | **nodes** |
| "QKV" | **QKD** |
| "third-lapse" | **Thorlabs** |
| "Kirby", "Curvy" | **CURBy** (CU) |
| "ghc", "gsg", "GG states" | **GHZ** states |
| "placal cells", "POCLE cells" | **Pockels cells** |
| "stephan" | **Stefan** |
| "gino" | **Gina** |

## Wiki format

The summary is an Outline page.

- No H1 in the body: the title is its own field.
- Callouts are `:::info` / `:::warning` blocks. Diagrams are ```` ```mermaidjs ```` fences.
- Follow `context/template.md`, which overrides anything here about the body's shape.
  `!!…!!` marks a placeholder: replace every one, and leave out the template's first
  `:::tip` (it's an instruction to whoever fills the template in).
- **Notes by:** "AI from recording". That row and the template's warning callout are what
  tell readers an AI wrote it.

## Chat

Add a `### Chat` section near the end listing the meeting's chat messages, with time and
sender. Sender names come from Zoom, so these are attributed. Leave out `ai:` commands that
were carried out (they show up as screenshots or notes instead), and any messages inside an
off-record span. Mention any command you couldn't interpret.

## Give loose talk some structure

Meetings are conversational: ideas come out half-formed, out of order, and spread over
several turns. Part of the summary's job is to give them shape, so add a visual or
structured aid wherever one makes a topic easier to grasp than prose. Good candidates:

- a mermaid diagram when people describe a system, a split between services, a data or
  request flow, a sequence of steps, or a dependency chain. A flowchart or sequence diagram
  of "who calls what" is usually the most useful;
- a table when options were weighed against each other (option → pros, cons, open
  questions), or when several items share the same attributes;
- a short numbered list when a process or a worked example was talked through step by step.

Draw only what was said. Every box, arrow and label should trace back to the discussion.
Where you had to fill a gap to make the picture hang together, mark it (a dashed edge, or a
`?` in the label) and say so in a line underneath. Caption each diagram with one line saying
it was drawn from the discussion and isn't an agreed design. Keep diagrams small: a dozen
nodes or so; split a bigger picture into two. Put each one inside the topic it belongs to,
next to the prose it supports. One or two good aids per meeting is typical; don't add one
where a sentence does the job.

## Style

Numbered `###` topics, short unattributed quotes in italics, explicit **Ask:** lines, and
owners on action items. Link related wiki docs (e.g. the
[Glossary](https://wiki.quantum-aspen.net/doc/glossary-LbZyBPLZu5)) where a topic touches
them. Cross-reference earlier summaries in the series only where they really connect. Don't
link to local file paths, because nobody else can open them.
