# Documentation layout

- `architecture/` contains architecture and protocol specifications.
- `superpowers/plans/` contains implementation plans; execution ledgers live in
  the generated `.superpowers/sdd/` directory.
- `verification/` contains generated verification reports.
- `development.md` documents source installation, editable builds, and tests.
- `runtime-deployment.md` documents the installed Package runtime boundary,
  public `Robot.from_instance()` entrypoint, and external Driver requirements.
- `../outputs/` is reserved for generated artifacts and exported reports; source design and planning documents do not live there.
- Hardware package code and vendor assets live in their own Hardware Package repository; project instances and tasks live in a user project repository.
- `../schemas/` contains schemas grouped by the v0.3 contract they describe.
