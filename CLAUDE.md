# machinechecked.org — project instructions

The website of MachineChecked. `PLAN.md` of the MachineChecked repository is the plan of record
for both; read its "The site" section before changing what the site lists or shows.

## Rules

- **This repository is public. Nothing of a private project goes into it** unless its owner
  has decided to publish that audit; no private names, statements, Lean or LaTeX otherwise.
- **The site runs nothing.** No Lean, no TeX, no code from an audit or a listed repository; its
  workflows only build static files, check metadata and deploy. Audits are read as data, from
  their authors' hosts, by the reader at `/read/`.
- **Attribute evidence.** Listings name their source; audits name their author and pinned revision.
  Display the engine’s status codes and independent evidence dimensions faithfully.

## Tracking work

As things are suggested and agreed (by the owner, or in a review the owner accepts), log each item
as a GitHub issue in the repository it affects (`cgarryZA/MachineChecked`,
`cgarryZA/machinechecked.org`, or a downstream project's own repository): one issue per item, saying
what, why, and when it is done, with a label for its kind (`bug`, `enhancement`, `cleanup`,
`docs`). Each repository has its own GitHub Projects board as its kanban, whose auto-add
workflow picks up the repository's new issues (sessions cannot use the Projects API). Log first; do not start an
issue's work until it is agreed to be worked on, and close it with the commit that does it
(`Fixes #n`). Issues in public repositories follow the privacy rules above: nothing of a private
project, written generically.

## Style

Plain English for mathematicians; comments say what the code does or why, not its history.

Public prose is concise and affirmative: say what exists, what a check establishes, or what the
reader can do next. Keep attribution compact and provenance in Details. Preserve quoted research
titles and mathematical statements. Follow MachineChecked #85 for public copy.
