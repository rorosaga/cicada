"""What Cicada's own agent may read of the person's files, and what may be stored of what it read (ruling 84; G209).

Three layers, none of them a prompt:

1. **Which folders** (:func:`grant_for_home`). A top-level folder of the home is granted only when it is a place a person keeps
   documents. It is never granted when its name says secrets (``secrets``, ``keys``, ``credentials``, ``tokens``, ``vault``...,
   any case, singular or plural), when it exists for programs rather than for documents (a ``.git`` anywhere in it, a
   dependency or environment folder, a build manifest, a name that is a known tool folder, or more code and configuration
   than documents), when it is Cicada's own working or evidence folder (a bank, a scratch or benchmark folder, anything named
   for Cicada), when it is or lies inside a refused path, or when it cannot be vouched for (too large to walk completely).
2. **Which files** (:data:`DOCUMENT_KINDS`). Inside a granted folder the session may read only the document kinds a person
   keeps things in. **The harness cannot express that as an allow list for its search tools**: ``Glob`` and ``Grep`` follow the
   ``Read`` rules only (proved live: a rule named for ``Glob`` or ``Grep`` is not consulted), and to let them search a folder
   the ``Read`` rule has to cover the whole folder, which lets ``Read`` open any file in it that no deny rule names. So the allow
   list is enforced as its **exact complement over a complete walk**: :func:`census` walks each granted folder (bounded; a
   folder too large to walk completely is not granted), and every extension present that is not a document kind, and every
   extension-less file name, becomes a deny rule that is root independent (``Read(//**/*.json)``). A deny on ``Read`` also
   filters what ``Glob`` and ``Grep`` print (proved live), so a search over a folder never returns a line from a file that
   ``Read`` would refuse. Dot-files and dot-folders are denied wholesale (per granted folder), and the name rules (secret-shaped
   files and folders) are a second layer on top, written per granted folder too (a name rule that holds wherever a file sits
   matches the granted folder's own name, so a folder the person turned on that is called ``secrets`` could not be read at all). The walk is a snapshot: a file made in a granted folder after it, with an extension the walk did
   not see, would be readable; nothing in a read-only session can make one.
3. **What is stored** (:func:`allowed_path`, :func:`looks_like_key`). A quote from a file is kept only when the file is of an
   allowed kind under a granted folder (or is one of the question's conversation copies), and nothing that looks like key
   material is ever kept: the item is dropped and counted. Every path of the audit trail is checked the same way before it is written.

The session's scratch folder (conversation copies) is a private temp folder made for that session, owner-only, outside Cicada's
home and outside every granted folder (:func:`make_scratch`).
"""
from __future__ import annotations

import fnmatch
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

#: The document kinds a person keeps things in: the only files a session may read inside a granted folder. A file with no
#: extension is not one (a ``Makefile``, a ``kubeconfig`` and an ``id_rsa`` have none): a plain note with no extension is left.
DOCUMENT_KINDS = frozenset({"md", "markdown", "txt", "text", "rtf", "pdf", "docx", "doc", "pages", "odt", "csv", "tsv", "html",
                            "htm", "org", "tex"})

#: Words that make a folder a secrets folder, matched as whole words of its name (split at case changes, digits and
#: punctuation), singular or plural, any case.
SECRET_WORDS = frozenset({"secret", "secrets", "key", "keys", "apikey", "apikeys", "credential", "credentials", "cred", "creds",
                          "password", "passwords", "passwd", "private", "token", "tokens", "cert", "certs", "certificate",
                          "certificates", "wallet", "wallets", "vault", "vaults", "keychain", "keystore", "ssh", "gnupg", "gpg",
                          "pgp", "oauth", "pem"})
#: Fragments that make a name secret-shaped wherever they sit in it ("my_passwords", "prod-secrets-backup").
SECRET_FRAGMENTS = ("secret", "credential", "password", "passwd", "privatekey", "apikey")

#: Names of folders that exist for programs: known tool data and developer folders. The walk finds the rest (a ``.git``, a
#: dependency folder, a manifest, more code than documents).
TOOL_FOLDERS = frozenset({"go", "bin", "sbin", "opt", "homebrew", "brew", "miniconda", "miniconda3", "anaconda", "anaconda3",
                          "miniforge3", "mambaforge", "micromamba", "conda", "venv", "venvs", "virtualenvs", "node_modules",
                          "gradle", "android", "androidstudioprojects", "flutter", "xcode", "developer", "dotfiles", "sdk",
                          "sdks", "toolchains", "code", "dev", "src", "repos", "repositories", "git", "github", "gitlab",
                          "workspace", "workspaces", "sandbox", "build", "dist", "vendor", "lib", "docker", "vagrant",
                          "terraform", "ansible", "kubernetes", "k8s"})
#: Folders inside a granted folder that mean programs live there.
TOOL_SUBFOLDERS = frozenset({"node_modules", "site-packages", "__pycache__", "venv", "virtualenv", ".venv", ".tox", ".gradle",
                             ".git", ".hg", ".svn", "vendor", "dist-packages", "pods", "deriveddata"})
MANIFESTS = frozenset({"package.json", "pyproject.toml", "setup.py", "cargo.toml", "go.mod", "makefile", "dockerfile",
                       "pom.xml", "build.gradle", "package.swift", "requirements.txt", "gemfile", "composer.json",
                       "cmakelists.txt", "podfile", "pubspec.yaml"})
CODE_AND_CONFIG = frozenset({"py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "java", "kt", "swift", "c", "h", "cpp", "hpp", "cc",
                             "cs", "go", "rs", "rb", "php", "sh", "zsh", "bash", "fish", "pl", "lua", "r", "scala", "sql", "json",
                             "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "lock", "xml", "plist", "gradle", "m", "mm",
                             "dart", "ex", "exs", "hs", "ipynb", "tf", "tfvars", "proto", "css", "scss", "vue", "svelte"})

#: Secret-shaped file names (``*`` for any run): a second layer on top of the kinds, refused wherever they sit.
SECRET_FILES = (".env*", "*.env", "secret*", "credential*", "password*", "passwd*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
                "*.kdbx", ".netrc", ".pgpass", "id_*", ".npmrc", ".pypirc", ".git-credentials", ".dockercfg", "*.keychain",
                "*.keychain-db", "*.1pux", "*.1pif", "*.opvault", "*.agilekeychain", "*.gpg", "*.tfvars", "*.ovpn",
                "*.asc", "*.crt", "*.cer", "*.der", "*.p8", "*.token")
#: Whole-name folder words, refused wherever they sit inside a granted folder (and their contents).
SECRET_FOLDERS = ("secrets", "secret", "keys", "key", "credentials", "creds", "passwords", "private", "tokens", "certs", "certificates",
                  "wallet", "wallets", "vault", "keychain", "ssh", "gnupg")

#: The kinds a notes folder is made of (the vault rule, :func:`notes_vault`).
NOTE_KINDS = frozenset({"md", "markdown", "txt", "text", "org"})
#: Hidden folders that hold keys or sign-ins; one in a folder named for a vault says it is no notes folder.
KEY_DOTDIRS = frozenset({".ssh", ".aws", ".gnupg", ".gpg", ".kube", ".docker", ".azure", ".config", ".password-store"})

MAX_ENTRIES = 40000        # per folder: past it the folder cannot be vouched for and is not granted
MAX_DEPTH = 10
MAX_DENY_EXTS = 400
MAX_DENY_NAMES = 300

# --------------------------------------------------------------------------- names


def fold(text: str) -> str:
    """A name as every comparison against a name set sees it: compatibility-normalised and case-folded, so ``LIBRARY``, ``library``, a
    decomposed ``e`` plus accent and a full-width spelling are one name. A Mac's disk is case-insensitive and keeps either normal
    form (``os.path.realpath`` fixes neither), so a spelling the person or a request supplies is never compared as typed."""
    s = unicodedata.normalize("NFKC", str(text))
    return unicodedata.normalize("NFKC", s.casefold())


def fold_id(folder_id: str) -> str:
    """A folder's id (its path below the home, ``/``-separated) folded part by part."""
    return "/".join(fold(p) for p in str(folder_id).split("/"))


SECRET_FOLDERS_F = frozenset(fold(n) for n in SECRET_FOLDERS)


def _tokens(name: str) -> set[str]:
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", unicodedata.normalize("NFKC", str(name)))
    return {p.lower() for p in parts}


def secret_named(name: str) -> bool:
    """Does a folder or file name say secrets: a whole word of the name is a secret word, or a fragment sits in it."""
    squashed = re.sub(r"[^a-z0-9]", "", fold(name))
    return bool(_tokens(name) & SECRET_WORDS) or any(f in squashed for f in SECRET_FRAGMENTS)


def cicada_named(name: str) -> bool:
    low = fold(name)
    return "cicada" in low or low.startswith(("engine-scratch", "harness-"))


def secret_file(name: str) -> bool:
    low = fold(name)
    return any(fnmatch.fnmatchcase(low, pat.lower()) for pat in SECRET_FILES)


def secret_part(name: str) -> bool:
    """Would the file rules refuse a file or folder of this name inside a granted folder (hidden, a secret-shaped file name, a name that
    says secrets, a secret folder word)? Whatever its casing."""
    return name.startswith(".") or secret_file(name) or secret_named(name) or fold(name) in SECRET_FOLDERS_F


def _pattern(text: str) -> str:
    """A name as a deny pattern: anything the pattern language treats specially becomes ``?`` (a wider pattern: it only denies more)."""
    return "".join(c if c.isalnum() or c in "._-+@=,()~" else "?" for c in text)


def root_deny(roots: tuple[str, ...]) -> tuple[str, ...]:
    """Rules written per granted folder, for what is only meant inside it: any dot-file or dot-folder (config, keys, tokens, ``.git``),
    the secret-shaped file names (``.env*``, ``secret*``, ``*.pem``, ``id_*``...) and the secret-shaped folder names with everything under
    them. Never root independent: ``private`` is also the name of a Mac's own ``/private``, and a rule on it would refuse every path
    that lives there; and a name rule matches the folder's own name too, so ``Read(//**/secret*)`` refused every file of a folder the
    person turned on that is called ``secrets`` (proved live, 2026-11-26: a granted folder whose own name or whose parent's says
    secrets read nothing). Scoped to the root, the rule judges only what is below it."""
    out: list[str] = []
    for root in roots:
        r = root.rstrip("/")
        out.append(f"Read(/{r}/**/.*)")
        out += [f"Read(/{r}/**/{pat})" for pat in SECRET_FILES]
        for name in SECRET_FOLDERS:
            out += [f"Read(/{r}/**/{name})", f"Read(/{r}/**/{name}/**)"]
    return tuple(out)


# --------------------------------------------------------------------------- the census


@dataclass
class Census:
    entries: int = 0
    docs: int = 0
    programs: int = 0
    files: int = 0                                      # visible files seen
    notes: int = 0                                      # of them, markdown or plain-text notes
    keylike: int = 0                                    # files or folders (hidden ones too) whose name or kind says keys, settings or secrets
    exts: set[str] = field(default_factory=set)         # extensions present that are not document kinds, as spelled (``KEY.PEM`` adds ``PEM``)
    names: set[str] = field(default_factory=set)        # extension-less files present
    secret_names: set[tuple[str, bool]] = field(default_factory=set)   # (name, is a folder): spelled as found, whose name the file rules refuse
    links_out: int = 0                                  # links (hidden ones too) that lead out of the folder
    flags: set[str] = field(default_factory=set)        # git | tool_dir | manifest | bank | secret_dir
    truncated: bool = False


def census(root: str, *, max_entries: int | None = None, max_depth: int | None = None) -> Census:
    """Walk ``root`` completely (or say it could not: ``truncated``): no link is followed, no file is opened. Counts documents and
    programs, collects every extension and extension-less name that is not a document kind, and notes what says tooling."""
    max_entries, max_depth = max_entries or MAX_ENTRIES, max_depth or MAX_DEPTH
    c = Census()
    real_root = os.path.realpath(root)
    stack: list[tuple[str, int]] = [(root, 0)]
    while stack:
        here, depth = stack.pop()
        try:
            entries = list(os.scandir(here))
        except OSError:
            c.flags.add("unreadable")
            continue
        dirs = {fold(e.name) for e in entries if e.is_dir(follow_symlinks=False)}
        if {"entities", "episodes"} <= dirs or any(fold(e.name) == "_bank.yaml" for e in entries):
            c.flags.add("bank")
        for e in entries:
            c.entries += 1
            if c.entries > max_entries:
                c.truncated = True
                return c
            name, low = e.name, fold(e.name)
            try:
                if e.is_symlink() and not _within(os.path.realpath(e.path), real_root):
                    # a link that leaves the folder: never a note, never followed; its own name is denied (a file or a folder)
                    c.links_out += 1
                    c.secret_names.add((name, os.path.isdir(e.path)))
                    continue
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                if low in TOOL_SUBFOLDERS or low.endswith((".xcodeproj", ".xcworkspace")):
                    c.flags.add("git" if low == ".git" else "tool_dir")
                    continue
                if name.startswith("."):
                    c.keylike += low in KEY_DOTDIRS or secret_named(name)
                    continue                         # denied wholesale; never walked
                if secret_named(name) or low in SECRET_FOLDERS_F:
                    c.flags.add("secret_dir")
                    c.secret_names.add((name, True))
                    continue                         # denied by its own spelling; never walked
                if depth + 1 > max_depth:
                    c.truncated = True
                    return c
                stack.append((e.path, depth + 1))
                continue
            if name.startswith("."):
                c.keylike += secret_file(name) or secret_named(name)
                continue                             # denied wholesale
            c.files += 1
            if secret_file(name) or secret_named(name):
                c.keylike += 1
                c.secret_names.add((name, False))
            if low in MANIFESTS and depth <= 1:
                c.flags.add("manifest")
            ext = low.rsplit(".", 1)[1] if "." in low.strip(".") else ""
            if ext in DOCUMENT_KINDS:
                c.docs += 1
                c.notes += ext in NOTE_KINDS
            elif ext:
                c.exts |= {ext, name.rsplit(".", 1)[-1]}     # a deny pattern is case-sensitive: the spelling found is denied too
                c.programs += ext in CODE_AND_CONFIG
            else:
                c.names.add(name)
    return c


def _within(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def vault_named(name: str) -> bool:
    """Is a vault (or vaults) the only thing in the folder's name that says secrets? ``Notes Vault`` is; ``vault-keys`` and
    ``passwords`` are not. Such a name is the one a notes app gives its folder, so it is judged by what the folder holds."""
    squashed = re.sub(r"[^a-z0-9]", "", fold(name))
    return (secret_named(name) and not ((_tokens(name) & SECRET_WORDS) - {"vault", "vaults"})
            and not any(f in squashed for f in SECRET_FRAGMENTS))


def _notes_only(name: str, cen: Census) -> bool:
    return (vault_named(name) and not cen.truncated and cen.notes >= 1 and cen.notes * 2 >= cen.files and cen.keylike == 0
            and cen.programs == 0 and "secret_dir" not in cen.flags)


def notes_vault(name: str, cen: Census) -> bool:
    """A folder named for a vault that holds notes: mostly Markdown or text, nothing key-shaped by the existing kinds (no secret-shaped
    file or folder name, hidden ones included, no code or configuration file), no link that leads out of it (a link may point at a key
    folder, and is not a note), and walked completely."""
    return _notes_only(name, cen) and cen.links_out == 0


def hard_refusal(name: str, cen: Census) -> str:
    """What no choice of the person's can open: Cicada's own folder, or one too large to walk completely (it could not be vouched for)."""
    if cicada_named(name) or "bank" in cen.flags:
        return "cicada"
    return "too_large" if cen.truncated else ""


def refusal_for(name: str, cen: Census) -> str:
    """Why a folder is not granted by default, from its name and what the walk found: ``""`` when it is, ``"notes_vault"`` when it
    is a folder named for a vault that holds notes (granted, and said so)."""
    if secret_named(name) and not notes_vault(name, cen):
        return "vault_link" if cen.links_out and _notes_only(name, cen) else "secrets"
    if cicada_named(name) or "bank" in cen.flags:
        return "cicada"
    if (fold(name) in TOOL_FOLDERS or cen.flags & {"git", "tool_dir", "manifest"} or cen.programs > cen.docs):
        return "tooling"
    if cen.truncated:
        return "too_large"
    return "notes_vault" if secret_named(name) else ""


# --------------------------------------------------------------------------- the grant


#: A folder's state in the person's list. ``default``: granted by the rule; ``on`` / ``off``: the person's choice stands;
#: ``refused``: the rule refuses it and the person has not chosen; ``protected``: macOS keeps it closed to a session the backend starts.
STATES = ("default", "on", "off", "refused", "protected")
#: The words beside each state and reason, one place for the app, the CLI and the dry run.
REASONS = {
    "default": "Notes and documents. Keys, settings and code are never read.",
    "notes_vault": "Named for a vault, but it holds only notes, so it is on. Keys and settings are never read.",
    "vault_link": "Named for a vault, but it holds a link that leads out of the folder, so it is off. Turned on, only its documents are read, "
                  "never what a link leads to.",
    "on": "Turned on by you. Only documents are read, never keys, settings or code.",
    "off": "Turned off by you.",
    "secrets": "Its name says secrets, so it is off. Turned on, only its documents are read, never key or settings files.",
    "tooling": "It looks like code or tools, so it is off. Turned on, only its documents are read.",
    "cicada": "Cicada's own files. Never read.",
    "too_large": "Too large to check completely, so it stays closed.",
    "too_varied": "Holds too many kinds of files to check, so it stays closed.",
    "shadowed": "Inside a folder that is on, under a name that says secrets, so it stays closed. Turn that folder off to read this one on its own.",
    "mount": "On another disk, so it stays closed.",
    "protected": "macOS keeps this folder closed to a read Cicada starts by itself.",
    "system": "The Mac's own folder, never read.",
}


@dataclass(frozen=True)
class Folder:
    """One row of the person's list: a folder of their home, its state, and ``why``, the rule's own verdict whatever the state."""
    id: str                # the path below the home, "/"-separated: the row's identity everywhere
    name: str
    path: str
    state: str
    why: str = ""
    added: bool = False    # the person added it by hand
    locked: bool = False   # no choice can open it

    @property
    def granted(self) -> bool:
        return self.state in ("default", "on")

    @property
    def default_on(self) -> bool:
        """Would the rule grant it with no choice made?"""
        return self.why in ("", "notes_vault") and not self.locked

    @property
    def reason(self) -> str:
        if self.state in ("on", "off"):
            return REASONS[self.state]
        return REASONS.get(self.why or "default", "")


@dataclass(frozen=True)
class Grant:
    roots: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()          # paths inside or beside a root the session may not read (the bank, Cicada's home)
    deny: tuple[str, ...] = ()             # deny rules over the walk: the complement of the document kinds (root independent) and the names found
                                           # that the file rules refuse (per granted folder, spelled as found)
    skipped: tuple[tuple[str, str], ...] = ()   # (folder name, why) for every candidate left out
    walked: int = 0
    folders: tuple[Folder, ...] = ()       # the whole list with each folder's state (what Settings shows)

    def why_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for _name, why in self.skipped:
            out[why] = out.get(why, 0) + 1
        return out


def _choices_by_id(choices: dict, ids: list[str]) -> dict:
    """The stored decisions keyed by the listed folder each names: the exact id, else the one listed id that folds the same (a decision
    written in another casing or normal form). Where a disk keeps two folders that differ only in case, each keeps its own."""
    by_fold: dict[str, list[str]] = {}
    for i in ids:
        by_fold.setdefault(fold_id(i), []).append(i)
    out = {k: v for k, v in choices.items() if k in ids}
    for k, v in choices.items():
        if k not in ids:
            same = by_fold.get(fold_id(k), [])
            out.setdefault(same[0] if len(same) == 1 else k, v)
    return out


def _root_rules(root: str, names: set[tuple[str, bool]]) -> list[str]:
    """Deny rules for the names the walk found that the file rules refuse, spelled as found, written for one granted folder (a deny
    pattern is case-sensitive: ``secret*`` does not match ``Secrets.md`` nor ``my-passwords``, and ``secrets`` does not match ``Secrets``)."""
    r = root.rstrip("/")
    out: list[str] = []
    for name, is_dir in sorted(names):
        out.append(f"Read(/{r}/**/{_pattern(name)})")
        if is_dir:
            out.append(f"Read(/{r}/**/{_pattern(name)}/**)")
    return out


def _plan(cands: list[tuple[str, str, str, bool]], refused: tuple[str, ...], choices: dict | None = None) -> tuple[list[Folder], Grant]:
    """Judge each candidate ``(id, name, path, added)`` and build the grant. A folder is walked unless its name already says secrets (a
    verdict that needs no walk) and the person has not turned it on; a folder the person added or turned on is always walked, so
    Cicada's own and a folder too large to walk stay closed whatever was chosen. A folder the person turned on that sits inside another
    granted folder under a name the file rules refuse stays closed and says so (the harness's deny always wins over an allow, so the
    parent's rule for that name would refuse every file of it)."""
    choices = _choices_by_id(choices or {}, [c[0] for c in cands])
    verdicts: list[dict] = []
    walked = 0
    seen_exts: set[str] = set()
    seen_names: set[str] = set()
    for fid, name, path, added in cands:
        choice = choices.get(fid) if isinstance(choices.get(fid), dict) else {}
        pick, added = choice.get("state"), added or bool(choice.get("added"))
        base = Path(path).name          # the rules judge the folder's own name; the row shows its place below the home
        v = {"fid": fid, "name": name, "path": path, "added": added, "pick": pick, "cen": None, "hard": "", "why": "secrets", "on": False}
        verdicts.append(v)
        if any(under(path, r) for r in refused):
            v["hard"] = "cicada"
            continue
        cen = None
        if added or pick == "on" or not (secret_named(base) and not vault_named(base)):
            cen = census(path)
            walked += cen.entries
        why = "secrets" if cen is None else refusal_for(base, cen)
        hard = hard_refusal(base, cen) if cen is not None else ""
        on = pick == "on" or (pick != "off" and (added or why in ("", "notes_vault")))
        if not hard and on and cen is not None and (len(seen_exts | cen.exts) > MAX_DENY_EXTS or len(seen_names | cen.names) > MAX_DENY_NAMES
                                                    or len(cen.secret_names) > MAX_DENY_NAMES):
            hard = "too_varied"
        if not hard and on and cen is not None:
            seen_exts |= cen.exts
            seen_names |= cen.names
        v.update(cen=cen, why=why, hard=hard, on=on)
    # Inside another granted folder under a refused name: closed, said so (shallowest first, so a closed one shadows nothing).
    kept: list[str] = []
    for v in sorted((v for v in verdicts if v["on"] and not v["hard"]), key=lambda v: len(v["path"])):
        parent = next((r for r in kept if v["path"] != r and under(v["path"], r)
                       and any(secret_part(part) for part in _below(v["path"], r))), None)
        if parent is None:
            kept.append(v["path"])
        else:
            v.update(hard="shadowed", on=False)
    rows: list[Folder] = []
    roots: list[str] = []
    skipped: list[tuple[str, str]] = []
    exts: set[str] = set()
    names: set[str] = set()
    rules: list[str] = []
    for v in verdicts:
        fid, name, path, added, pick, cen, why = v["fid"], v["name"], v["path"], v["added"], v["pick"], v["cen"], v["why"]
        if v["hard"]:
            rows.append(Folder(fid, name, path, "refused", v["hard"], added, True))
            skipped.append((name, v["hard"]))
        elif v["on"]:
            rows.append(Folder(fid, name, path, "on" if (pick == "on" or added) else "default", why, added))
            roots.append(path)
            exts |= cen.exts
            names |= cen.names
            rules += _root_rules(path, cen.secret_names)
        else:
            rows.append(Folder(fid, name, path, "off" if pick == "off" else "refused", why, added))
            skipped.append((name, "off" if pick == "off" else why))
    deny = [*(f"Read(//**/*.{_pattern(e)})" for e in sorted(exts)),
            *(f"Read(//**/{_pattern(n)})" for n in sorted(names)), *rules]
    return rows, Grant(tuple(roots), tuple(refused), tuple(deny), tuple(skipped), walked, tuple(rows))


def _below(path: str, parent: str) -> list[str]:
    """The parts of ``path`` below ``parent`` (both spelled as the list spells them: from one listing of the home)."""
    mine, theirs = _parts(os.path.realpath(path)), _parts(os.path.realpath(parent))
    return mine[len(theirs):]


def _vet(candidates: list[tuple[str, str]], refused: tuple[str, ...]) -> Grant:
    return _plan([(name, name, path, False) for name, path in candidates], refused)[1]


#: Folders a child of the backend cannot list (measured: a launchd child, no prior grant, lists the home and ordinary
#: folders but not these) and whose first access would raise a prompt nobody is there to answer.
PROTECTED = frozenset({"Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Library", "Public", "Applications"})
#: Of those, the Mac's own: never the person's folders, never read even from their own shell, and not named to them as protected.
SYSTEM_FOLDERS = frozenset({"Library", "Applications"})
#: The same names as every comparison sees them (:func:`fold`): ``library`` and ``LIBRARY`` are ``Library`` to a case-insensitive disk,
#: and are treated so on a case-sensitive one too (a folder called ``library`` beside ``Library`` there is refused as protected: the
#: safe side of a doubt, and a Linux home has none of these anyway).
PROTECTED_F = frozenset(fold(n) for n in PROTECTED)
SYSTEM_F = frozenset(fold(n) for n in SYSTEM_FOLDERS)


def _parts(path: str) -> list[str]:
    return [p for p in path.split("/") if p]


def _same_device(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def true_name(parent: str, typed: str) -> str | None:
    """The name ``typed`` has on disk inside ``parent`` (``None`` when there is none, or two could be it). An exact name wins (on a
    case-sensitive disk ``library`` beside ``Library`` are two folders); else the one entry that folds the same (casing, normal form);
    else the entry that is the same file (a disk may equate spellings :func:`fold` does not)."""
    try:
        names = [e.name for e in os.scandir(parent)]
    except OSError:
        return None
    if typed in names:
        return typed
    key = fold(typed)
    same = [n for n in names if fold(n) == key]
    if not same:
        try:
            wanted = os.lstat(os.path.join(parent, typed))
            same = [n for n in names if _is_file(os.path.join(parent, n), wanted)]
        except OSError:
            return None
    return same[0] if len(same) == 1 else None


def _is_file(path: str, st: os.stat_result) -> bool:
    try:
        other = os.lstat(path)
    except OSError:
        return False
    return (other.st_dev, other.st_ino) == (st.st_dev, st.st_ino)


def true_path(path: str) -> str:
    """``realpath`` with every component that exists spelled as the disk spells it (``realpath`` fixes neither case nor normal form on a
    Mac); the part that does not exist is kept as given."""
    out = "/"
    for comp in _parts(os.path.realpath(path)):
        out = os.path.join(out, true_name(out, comp) or comp)
    return out


def resolve_location(home: Path, path: str) -> tuple[str, str]:
    """``(problem, canonical path)``: why ``path`` can never be a folder of the list, in a code (``""`` when the place is fine), and the
    path with every part below the home spelled as the disk spells it (the id a folder is kept under: ``library`` is ``Library`` and is then
    refused). Not below the home, a hidden part, ``Library`` or a protected folder (any casing), a link anywhere in it, not a folder, or
    on another disk. The home itself is no folder. Nothing outside the home is listed or opened."""
    lexical, base = os.path.normpath(path), os.path.normpath(str(home))
    mine, root = _parts(lexical), _parts(base)
    if len(mine) <= len(root) or any(a != b and fold(a) != fold(b) for a, b in zip(mine, root)) or not lexical.startswith(os.sep):
        return "outside", lexical
    rel = mine[len(root):]
    if any(p.startswith(".") for p in rel):
        return "hidden", lexical
    if fold(rel[0]) in PROTECTED_F:
        return "protected", lexical
    here = base
    for i, typed in enumerate(rel):
        name = true_name(here, typed)
        if name is None:
            return "missing", lexical
        here = os.path.join(here, name)
        if name.startswith(".") or (i == 0 and fold(name) in PROTECTED_F):
            return ("hidden" if name.startswith(".") else "protected"), here
        if os.path.islink(here):
            return "link", here
        if i < len(rel) - 1 and not os.path.isdir(here):
            return "missing", here
    if os.path.realpath(here) != os.path.join(os.path.realpath(base), *_parts(here)[len(root):]):
        return "link", here
    if not os.path.isdir(here):
        return "missing", here
    return ("mount" if not _same_device(here, base) else ""), here


def location_problem(home: Path, path: str) -> str:
    """:func:`resolve_location`'s code alone."""
    return resolve_location(home, path)[0]


def folder_list(home: Path, *, attended: bool = False, refused: tuple[str, ...] = (), choices: dict | None = None) -> Grant:
    """The person's own folders a private session may read, and every folder the list shows (see the module's first layer). The
    candidates are the top-level folders of the home and the folders the person added by hand (``choices``). Never a hidden folder, a
    link (it may leave the home), a folder on another volume (a mount), ``Library`` or ``Applications``; unless the person started this
    from their own shell (``attended``) never a protected one (a prompt nobody answers). The person's choice (``choices``: id to
    ``{"state": "on"|"off", "added": bool}``) overrules the rule's soft refusals (a name that says secrets, a tooling folder) and never
    the hard ones (Cicada's own, too large to walk, another disk, protected). The file rules never move. Every name is compared
    whatever its casing or normal form, and a stored id is read as the folder's true name on disk."""
    choices = choices or {}
    cands: list[tuple[str, str, str, bool]] = []
    pre: list[Folder] = []
    try:
        entries = sorted(os.scandir(home), key=lambda e: e.name)
    except OSError:
        return Grant(refused=tuple(refused))
    for e in entries:
        if e.name.startswith(".") or not e.is_dir(follow_symlinks=False):
            continue
        key = fold(e.name)
        if key in PROTECTED_F and not (attended and key not in SYSTEM_F):
            pre.append(Folder(e.name, e.name, e.path, "protected", "system" if key in SYSTEM_F else "protected", False, True))
        elif not _same_device(e.path, str(home)):
            pre.append(Folder(e.name, e.name, e.path, "refused", "mount", False, True))
        else:
            cands.append((e.name, e.name, e.path, False))
    tops = {c[0] for c in cands} | {f.id for f in pre}
    for fid, choice in sorted(choices.items()):
        if not isinstance(choice, dict) or not choice.get("added"):
            continue
        problem, canon = resolve_location(home, os.path.join(str(home), *fid.split("/")))
        if problem:
            continue
        cid = os.path.relpath(canon, os.path.normpath(str(home))).replace(os.sep, "/")
        if cid in tops:
            continue
        tops.add(cid)
        cands.append((cid, cid, canon, True))
    rows, g = _plan(cands, tuple(refused), choices)
    allrows = sorted([*pre, *rows], key=lambda f: (f.added, f.id.lower()))
    return Grant(g.roots, g.refused, g.deny, (*((f.name, f.why) for f in pre), *g.skipped), g.walked, tuple(allrows))


def grant_for_home(home: Path, *, attended: bool, refused: tuple[str, ...] = (), choices: dict | None = None) -> Grant:
    """The folders a private session may read: :func:`folder_list`'s grant."""
    return folder_list(home, attended=attended, refused=refused, choices=choices)


def grant_for_roots(roots: tuple[str, ...], refused: tuple[str, ...] = ()) -> Grant:
    """The same vetting for folders named by the caller (a test, a battery): each is walked and may still be refused."""
    return _vet([(Path(r).name, str(r)) for r in roots], tuple(refused))


# --------------------------------------------------------------------------- what may be stored


def _spelled(path: str) -> list[str]:
    real = os.path.realpath(path)
    out = [path, real]
    for pre in ("/private/var/", "/private/tmp/", "/private/etc/"):
        if real.startswith(pre):
            out.append(real[len("/private"):])
    return list(dict.fromkeys(out))


def _folded(path: str) -> list[str]:
    return [fold(p) for p in _parts(path)]


def under(path: str, folder: str) -> bool:
    """Is ``path`` inside ``folder``, spelled either way a Mac spells ``/var``, and in whatever casing or normal form? (The answer is
    meant for refusing: a path that may be inside is inside. What may be stored goes through :func:`allowed_path`, which asks the disk.)"""
    real = _folded(os.path.realpath(path))
    for f in _spelled(folder) + [os.path.realpath(folder)]:
        want = _folded(f)
        if real[:len(want)] == want:
            return True
    return False


def allowed_path(path: str, roots: tuple[str, ...], *, copies_dir: str = "", refused: tuple[str, ...] = ()) -> bool:
    """May something read at ``path`` be stored: an absolute path of an allowed kind (a document kind) under a granted folder (or a
    ``.md`` copy in the question's own copies folder), with no hidden or secret-shaped part below its folder, never under a refused path
    (whatever the casing). The folder it sits in is judged by the disk's own spelling of both, so a folder that differs only in case from
    a granted one is not that folder where the disk keeps both."""
    if not path or not os.path.isabs(path):
        return False
    real = os.path.realpath(path)
    if any(under(real, r) for r in refused):
        return False
    base = os.path.basename(real)
    ext = fold(base).rsplit(".", 1)[1] if "." in base.strip(".") else ""
    if copies_dir and under(real, copies_dir):
        return ext == "md" and not base.startswith(".")
    named = next((r for r in roots if under(real, r)), None)
    if named is None or ext not in DOCUMENT_KINDS:
        return False
    true, root = _parts(true_path(real)), _parts(true_path(named))
    if true[:len(root)] != root:
        return False
    rel = true[len(root):]
    return not (any(p.startswith(".") for p in rel) or secret_file(base) or secret_named(base)
                or any(secret_named(p) or fold(p) in SECRET_FOLDERS_F for p in rel[:-1]))


# --- key material ----------------------------------------------------------------------------------------------------

_KEY_PATTERNS = [re.compile(p, re.I) for p in (
    r"-----BEGIN", r"PRIVATE KEY", r"\bsk-[A-Za-z0-9_-]{16,}", r"\bghp_[A-Za-z0-9]{20,}", r"\bgh[osur]_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}", r"\bxox[abprs]-[A-Za-z0-9-]{10,}", r"\bAKIA[0-9A-Z]{16}\b", r"\bAIza[0-9A-Za-z_-]{30,}",
    r"\bya29\.[A-Za-z0-9_-]{20,}", r"\bglpat-[A-Za-z0-9_-]{16,}", r"\bnpm_[A-Za-z0-9]{30,}", r"\bpypi-[A-Za-z0-9_-]{30,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}",
    r"\b(?:api[_-]?key|secret|token|passw(?:or)?d|private[_-]?key|client[_-]?secret)\b\s*[:=]\s*[\"']?\S{8,}",
)]
_HEX_RUN = re.compile(r"\b[0-9a-f]{32,}\b", re.I)
_B64_RUN = re.compile(r"[A-Za-z0-9+_=-]{32,}")
#: A canary in a test or a battery is the way to say "this is a secret": its marker is key material too.
_PLANTED = re.compile(r"CANARY_[A-Z0-9_]{3,}")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def looks_like_key(text: str) -> bool:
    """Does ``text`` look like key material (a PEM block, a known token prefix, a ``secret = ...`` line, a long hex or base64 run)?
    Such text is never stored; a false alarm only drops one item."""
    text = str(text or "")
    if any(p.search(text) for p in _KEY_PATTERNS) or _HEX_RUN.search(text) or _PLANTED.search(text):
        return True
    for m in _B64_RUN.finditer(text):
        run = m.group(0)
        classes = sum(bool(re.search(r, run)) for r in (r"[a-z]", r"[A-Z]", r"\d"))
        if classes >= 2 and _entropy(run) >= 3.8:
            return True
    return False


# --------------------------------------------------------------------------- the session's scratch folder


def scratch_parent(avoid: tuple[str, ...]) -> str | None:
    """A folder to make a session's scratch folder in: the system's temp folder (or ``/tmp``), outside every path in ``avoid`` (Cicada's
    home, the bank, every granted folder) and with no hidden part to its name (the dot-file rule would refuse the copies)."""
    for parent in dict.fromkeys([tempfile.gettempdir(), "/tmp", "/var/tmp"]):
        real = os.path.realpath(parent)
        if not os.path.isdir(real) or any(p.startswith(".") for p in real.split("/") if p):
            continue
        if any(under(real, a) for a in avoid):
            continue
        return parent
    return None


def make_scratch(avoid: tuple[str, ...]) -> Path | None:
    """A private folder for one session: made by ``mkdtemp`` (owner-only), outside ``avoid``. ``None`` when no safe place exists."""
    parent = scratch_parent(avoid)
    if parent is None:
        return None
    base = Path(tempfile.mkdtemp(prefix="cicada-harness-", dir=parent))
    os.chmod(base, 0o700)
    return base
