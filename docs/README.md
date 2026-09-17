# Commit Mono developer documentation

These pages cover the font side of the repository: what is where, what the shipped
binaries contain, and how to rebuild, verify and proof them with the tooling in `tools/`.
The website's own documentation is in the website itself (`index.html`, section 03 Docs).

- [Repository layout](repository.md): what each directory holds and which files are the
  source of truth.
- [Inside the font binaries](font-internals.md): tables, glyph naming, the variable font's
  master structure, and known quirks.
- [OpenType feature reference](features.md): every GSUB feature with its rules, generated
  from the binary by `cmfont features --write`.
- [Building, verifying and proofing](building.md): the `cmfont` tool, what the round trip
  preserves, and how to make and test changes.
