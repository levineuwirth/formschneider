# formschneider — rules that bind

Read `README.md` first. The plan of record is
`~/apocrypha/Passus/AI initials, two routes (2026-10-30).md`.

- **Never create, edit, move, or delete anything in `~/universum`.** Notes
  go to `~/apocrypha`, under its `AGENTS.md`.
- **Provenance from the first picture.** A generated picture is stored with
  its model, version, date, prompt, seed, mask, cost and terms, and a
  keep-or-reject call once the author makes one. The write-up is public and
  cannot be reconstructed after the fact.
- **Requests cost money and are the author's to start.** `bin/generate`
  plans by default; never pass `--go`, or send any other paid request,
  without the author's go-ahead in the session.
- **Keys stay in `.env`**, which git ignores. No key, request header or
  account identifier goes into a committed file or a result.
- **The site's format is a contract.** `lib/initial.py` writes what
  levineuwirth.org's `MARKS.md` §2.6 describes; `tests/test_cut.py` holds it
  to the site's EB Garamond set byte for byte. Change both together.
- Site and repository copy is American English.
