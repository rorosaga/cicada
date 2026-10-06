# Audit A04 — symlink-safe bank duplication

Source: `docs/goals/audit-2026-10-02/README.md` A04, revalidated on `dev` `efd5386e` (2026-10-05):
`repros/storage.py` still prints `external_file_copied: true`. Branch `fix/audit-bank-duplicate-symlinks`.

**Ruling.** One link policy for a bank's boundary, export's: a symlink is skipped at any depth, whatever it
points at — no "allowed if confined to the bank" special case. A link to a page inside the bank is redundant (the
page copies in its own right), and resolving confinement correctly across `..`, nested links and races is more
surface than the case is worth. `duplicate_bank` skips a top-level link and passes `copytree` an ignore function that
adds every link name to the existing name patterns.

**Tests first** (`api/tests/test_bank_duplicate_symlinks.py`, all five failing on `efd5386e`): a directory link
outside the bank, a file link, nested directory and file links, dangling links, and a link to a page inside the same
bank. **Verify:** the new file plus `test_banks.py` and `test_bank_trash_export.py`, then the full API suite.
