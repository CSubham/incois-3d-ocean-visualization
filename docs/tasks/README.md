# Tasks

Current work packets, implementation tasks, and acceptance criteria.

One file per work packet. Move a packet to `../history/` once it is complete and
the context is still worth keeping.

The active multi-agent handoff for the one-day prototype is
`ONE_DAY_WATER_TEMP_PROTOTYPE_MODERATOR_PROMPT.md`. It defines the moderator,
worker-goal, branch, merge, implementation-note, Graft, IMAP, and review rules
for that run. GhostGPT owns session lifecycle and wakeups.

That prompt is procedural only. Functional requirements come from the locked
SRS, their stage ownership comes from the locked HLSA, and the existing IMAP
configuration selects and decomposes the S3 to S7 work for the run.
