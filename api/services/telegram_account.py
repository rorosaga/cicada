"""The person's own Telegram session, kept by Cicada for ingestion only (ruling 47a, G179, owner 2026-10-28).

**Ruling 47a** (owner 2026-10-28, recorded with ruling 47 in ``docs/goals/TODO.md``): Telegram's chats are read on
the person's own account through Telegram's official client API — the one dated case where Cicada keeps a signed-in
session of someone's account, and only to read what they ticked. Its rails, each enforced here:

* **Off until the person connects.** Nothing imports the client, opens a socket or reads a file until the person
  clicks Connect in the app; with no session file, :func:`resume` does nothing.
* **Connecting is "link a device" (owner 2026-10-29):** the default is a QR (``auth.exportLoginToken``) the person
  scans in Telegram on their phone (Settings → Devices → Link Desktop Device) — nothing typed but a two-step password,
  if the account has one. The QR is refreshed as Telegram expires it, for :data:`QR_ROUNDS` rounds, then stops and
  says so. Number → code → password stays as the fallback.
* **The connect step says it in plain words** (:data:`CONSENT`): Cicada keeps a signed-in session; it ends from
  Telegram's Active sessions or with one click here. Disconnect logs the session OUT at Telegram (it disappears from
  Active sessions), then deletes the file — a failed log-out still deletes it and says so.
* **The secret lives outside every bank, log and git:** ``$CICADA_HOME/telegram/session``, 0600 in a 0700 folder,
  beside ``secrets.env`` — not inside it, because ``secrets.env`` is projected into the environment and every
  ``claude -p`` / hook Cicada spawns would inherit the session. A session file anyone else can read, or another user
  owns, is refused and never used. The phone number is passed to Telegram once and never stored; a code or password
  is never stored or logged.
* **Ticked one-to-one chats only, each with the other person's consent, live + history on ask** — the rails of
  :mod:`chat_live`, applied to every event before anything is staged: an event in an unticked chat, a group or a chat
  with no kept consent is dropped in memory, never written. **Amended (owner 2026-10-28)** after Telegram's AI terms
  (API Terms §1.5; telegram.org/tos/content-licensing): groups and channels are never offered, and ticking a
  one-to-one chat needs the person's confirmation, in plain words (:data:`CONSENT_ASK`), that the other person agreed —
  kept with its date in ``$CICADA_HOME/telegram/consents.json`` (0600, outside every bank: a chat id and a time,
  nothing else) and withdrawn by unticking. Cicada cannot verify it; the person is responsible for it.
* **Private names are never sent anywhere else.** The only network peer is Telegram itself.

**Cicada's own api_id.** Telegram identifies a client app by an ``api_id``/``api_hash`` pair from my.telegram.org.
The repo is public, so none is in it: a release build carries the owner's pair in ``api/data/telegram_app.json``
(written by ``bundle.sh`` from CI's ``CICADA_TELEGRAM_API_ID`` variable and ``CICADA_TELEGRAM_API_HASH`` secret,
``docs/RELEASING.md``; ``api/data/*`` is git-ignored); a person running from source or a server sets their own as
``CICADA_TELEGRAM_API_ID`` / ``CICADA_TELEGRAM_API_HASH`` in ``secrets.env``, which wins.

**Live.** One client per install, listening while connected. Events wait in memory for :data:`FLUSH_S` and are then
staged per chat in the active bank (never the demo bank), under the bank's write admission, one ``capture`` commit per
flush. A per-chat cursor (the newest message id read — an id, nothing else) lives beside the session, so a restart
catches up what arrived while the backend was down.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import chat_live, runtime_layout, telegram_source
from api.services.telegram_port import (CodeInvalid, NotAuthorized, PasswordInvalid, PasswordNeeded, PortFactory,
                                        TelegramError, TelegramPort, TgDialog, TgEvent, TgMessage, TgQr, TgSentCode)

CONSENT = ("Cicada keeps a signed-in session of your Telegram; you can end it any time from Telegram's Active "
           "sessions or with one click here.")
#: What the person confirms per chat before it is read — Telegram's exception in plain words (ruling 47a amendment).
CONSENT_ASK = ("Telegram allows an AI to read a chat only when everyone in it agreed — explicitly, knowing what it "
               "means, for this chat only. Confirm that {name} agreed that Cicada's AI reads your chat with them. "
               "You're responsible for that consent; Cicada can't check it. Unticking withdraws it.")
CONSENTS_FILE = "consents.json"
SESSION_DIR = "telegram"
SESSION_FILE = "session"
CURSOR_FILE = "cursors.json"
APP_FILE = Path(__file__).resolve().parent.parent / "data" / "telegram_app.json"
ID_ENV, HASH_ENV = "CICADA_TELEGRAM_API_ID", "CICADA_TELEGRAM_API_HASH"
FLUSH_S = 1.0
#: How many QR tokens one Connect shows before it stops (Telegram expires each after ~30 s): about five minutes.
QR_ROUNDS = 10
#: A QR is replaced this long before Telegram's own expiry, and never waited on for less than the floor — so a Mac
#: whose clock is off (or a token Telegram issues short) can't burn the rounds in a few seconds.
QR_MARGIN_S, QR_FLOOR_S = 2.0, 10.0
#: The status long-poll (`Account.wait_change`): at most this long per ask, re-read in process this often.
STATUS_WAIT_MAX_S, STATUS_STEP_S = 25.0, 0.05
UNREACHABLE = "Couldn't reach Telegram — try again."
DIALOG_LIMIT = 200
#: chats-ux-v2 — profile photos kept beside the session (ids only), re-asked after a week; Telegram's small photo is
#: ~160 px, a few KB.
PHOTO_DIR = "photos"
PHOTO_TTL_S = 7 * 24 * 3600
PHOTO_MAX_BYTES = 256 * 1024
HISTORY_CAP = 20_000
HISTORY_BATCH = 500


class SessionRefused(RuntimeError):
    """The session file exists but is not safe to use (readable by others, another owner)."""


# --- Credentials and the session file -------------------------------------------------------------------------------


def credentials(environ=os.environ) -> tuple[int, str, str] | None:
    """``(api_id, api_hash, whose)`` — the person's own pair (``own``) over the release build's (``cicada``); ``None``
    when neither is set."""
    raw_id, raw_hash = (environ.get(ID_ENV) or "").strip(), (environ.get(HASH_ENV) or "").strip()
    if raw_id.isdigit() and raw_hash:
        return int(raw_id), raw_hash, "own"
    try:
        data = json.loads(APP_FILE.read_text(encoding="utf-8"))
        api_id, api_hash = int(data["api_id"]), str(data["api_hash"]).strip()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (api_id, api_hash, "cicada") if api_id > 0 and api_hash else None


def folder(environ=os.environ) -> Path:
    return runtime_layout.cicada_home(environ) / SESSION_DIR


def session_path(environ=os.environ) -> Path:
    return folder(environ) / SESSION_FILE


def _private_dir() -> Path:
    path = folder()
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def load_session() -> str | None:
    path = session_path()
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if info.st_uid != os.getuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SessionRefused("the Telegram session file is readable by someone else — it is not used")
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def save_session(secret: str) -> None:
    path = _private_dir() / SESSION_FILE
    tmp = path.with_name(".session.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret.strip() + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def consents() -> dict[str, dict]:
    """``conversation -> {at}``: the chats whose other person the person confirmed agreed. Never raises."""
    try:
        raw = json.loads((folder() / CONSENTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: {"at": str(v.get("at") or "")} for k, v in raw.items()
            if chat_live.ID_RE.match(str(k)) and isinstance(v, dict)} if isinstance(raw, dict) else {}


def set_consent(cid: str, given: bool, *, at: str | None = None) -> dict[str, dict]:
    """Keep or withdraw one chat's confirmation, with its date. Ids and times only, 0600, outside every bank."""
    from api.services import episode_ids

    if not chat_live.ID_RE.match(str(cid)):
        raise ValueError("a conversation id")
    current = consents()
    if given:
        current[cid] = {"at": at or episode_ids.utc_now_iso()}
    else:
        current.pop(cid, None)
    path = _private_dir() / CONSENTS_FILE
    tmp = path.with_name(".consents.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(current, fh)
    os.replace(tmp, path)
    return current


def forget_session() -> None:
    import shutil

    for name in (SESSION_FILE, CURSOR_FILE):
        try:
            (folder() / name).unlink()
        except FileNotFoundError:
            pass
    # The picker's profile photos go with the session (a ticked chat's page picture lives in `messages_photos`).
    shutil.rmtree(folder() / PHOTO_DIR, ignore_errors=True)


def _cursors() -> dict[str, int]:
    try:
        raw = json.loads((folder() / CURSOR_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in raw.items() if chat_live.ID_RE.match(str(k)) and str(v).isdigit()} \
        if isinstance(raw, dict) else {}


def _save_cursors(cursors: dict[str, int]) -> None:
    path = _private_dir() / CURSOR_FILE
    tmp = path.with_name(".cursors.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cursors, fh)
    os.replace(tmp, path)


# --- The account ------------------------------------------------------------------------------------------------


@dataclass
class _Pending:
    events: list[TgEvent] = field(default_factory=list)


class Account:
    """The one Telegram client of this install. Every method runs on the backend's event loop."""

    def __init__(self, factory: PortFactory | None = None):
        self._factory = factory
        self.port: TelegramPort | None = None
        self.state = "off"           # off | qr | code_sent | password | connected | ended
        self.error: str | None = None
        self._phone: str | None = None   # held only between "send code" and a signed-in session
        self._code_length: int | None = None   # the digits of the code Telegram sent, while one is waiting
        self._code_hash: str | None = None
        self._qr: TgQr | None = None     # the QR on screen while ``state == "qr"`` — never logged, never kept
        self._qr_until = 0.0             # when the QR on screen expires, on this Mac's clock (for the app only)
        self._qr_task: asyncio.Task | None = None
        self._listen: asyncio.Task | None = None
        self._flush: asyncio.Task | None = None
        self._pending: dict[int | None, list[TgEvent]] = {}
        self._dialogs: dict[str, TgDialog] = {}
        self._lock = asyncio.Lock()
        #: At most two profile photos asked of Telegram at once (a picker lists up to 200 chats).
        self._photos = asyncio.Semaphore(2)
        #: How long each flush took, file event → staged, for the area doc's number (seconds, the last 200).
        self.flush_seconds: list[float] = []

    def _make(self, session: str = "") -> TelegramPort:
        creds = credentials()
        if creds is None:
            raise TelegramError("This build has no Telegram app id. Add your own from my.telegram.org as "
                                f"{ID_ENV} and {HASH_ENV} in ~/.cicada/secrets.env, then try again.")
        factory = self._factory
        if factory is None:
            from api.services.telegram_port import telethon_factory

            factory = telethon_factory
        return factory(creds[0], creds[1], session)

    def status(self) -> dict:
        creds = credentials()
        qr = self._qr if self.state == "qr" else None
        out = {"state": self.state, "consent": CONSENT, "consent_ask": CONSENT_ASK,
               "credentials": creds[2] if creds else None,
               "error": self.error, "listening": self._listen is not None and not self._listen.done(),
               "qr_url": qr.url if qr else None,
               "code_length": self._code_length if self.state == "code_sent" else None,
               "qr_expires": _iso(self._qr_until) if qr else None}
        out["version"] = self._signature()
        return out

    def _signature(self) -> str:
        """What the app compares to know the status moved: the state, its sentence, the QR on screen, the code's
        length, whether it listens. Reads only this object."""
        import hashlib

        qr = self._qr.url if self._qr is not None and self.state == "qr" else ""
        listening = self._listen is not None and not self._listen.done()
        key = f"{self.state}|{self.error or ''}|{qr}|{self._code_length if self.state == 'code_sent' else ''}|{listening}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    async def wait_change(self, since: str, timeout: float) -> dict:
        """chats-ux-v2 (owner 2026-10-29: "it took a bit to change status to connected") — the status as soon as it
        differs from the one the app holds (``since``, its ``version``), or after ``timeout`` seconds. The app's QR
        step asks this instead of reading the status once a second, so a scan shows as Connected the moment the
        sign-in lands. In-process reads only (no Telegram call), every :data:`STATUS_STEP_S`."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, min(float(timeout), STATUS_WAIT_MAX_S))
        while self._signature() == since and loop.time() < deadline:
            await asyncio.sleep(STATUS_STEP_S)
        return self.status()

    # The sign-in steps ---------------------------------------------------------------------------------------------

    async def start_qr(self) -> dict:
        """The default connect: a QR the person scans in Telegram on their phone. Answers at once with the first QR;
        a background task waits for the scan and shows a fresh QR each time Telegram expires one."""
        async with self._lock:
            if self.state == "connected":
                return self.status()
            self._stop_qr()
            self._phone = self._code_hash = None
            if self.port is None:
                self.port = self._make()
            try:
                qr = await self.port.qr_start()
            except PasswordNeeded:
                self.state, self.error = "password", None
                return self.status()
            except TelegramError:
                await self._drop_unsigned_port()
                raise
            except Exception as exc:  # noqa: BLE001 — a network or library failure is a sentence, never a 500
                logger.warning(f"telegram: QR start failed ({type(exc).__name__})")
                await self._drop_unsigned_port()
                raise TelegramError(UNREACHABLE) from exc
            if qr.signed_in:
                await self._signed_in()
                return self.status()
            self._show(qr)
            self.state, self.error = "qr", None
            self._qr_task = asyncio.get_running_loop().create_task(self._run_qr())
        return self.status()

    def _show(self, qr: TgQr) -> None:
        import time

        self._qr, self._qr_until = qr, time.time() + max(qr.ttl, 0.0)

    @staticmethod
    def _wait_for(qr: TgQr) -> float:
        return max(QR_FLOOR_S, qr.ttl - QR_MARGIN_S)

    async def _run_qr(self) -> None:
        rounds = 1
        try:
            while True:
                port, qr = self.port, self._qr
                if port is None or qr is None:
                    return
                if await port.qr_wait(self._wait_for(qr)):
                    async with self._lock:
                        self._qr_task = None
                        self._qr = None
                        await self._signed_in()
                    return
                if rounds >= QR_ROUNDS:
                    async with self._lock:
                        await self._drop_unsigned_port()
                        self.state, self.error = "off", "The QR expired unscanned — show a new one to try again."
                        self._qr_task = None
                    return
                rounds += 1
                qr = await port.qr_start()
                if qr.signed_in:           # scanned between two tokens: Telegram answered loginTokenSuccess
                    async with self._lock:
                        self._qr_task = None
                        self._qr = None
                        await self._signed_in()
                    return
                self._show(qr)
        except asyncio.CancelledError:
            raise
        except PasswordNeeded:
            self._qr, self._qr_task = None, None
            self.state, self.error = "password", None
        except Exception as exc:  # noqa: BLE001 — the row says it; Connect starts again
            logger.warning(f"telegram: QR sign-in stopped ({type(exc).__name__})")
            self._qr_task = None
            await self._drop_unsigned_port()
            self.state, self.error = "off", UNREACHABLE

    def _stop_qr(self) -> None:
        task, self._qr_task = self._qr_task, None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._qr = None

    async def _drop_unsigned_port(self) -> None:
        """Close a client that never signed in — no log-out, there is no session to end."""
        self._qr = None
        port, self.port = self.port, None
        if port is not None:
            try:
                await port.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def send_code(self, phone: str) -> dict:
        phone = "".join(c for c in str(phone or "") if c.isdigit() or c == "+")
        if len(phone.strip("+")) < 6:
            raise TelegramError("Enter the phone number of your Telegram account, with its country code.")
        async with self._lock:
            if self.state == "connected":
                return self.status()
            self._stop_qr()
            if self.port is None:
                self.port = self._make()
            try:
                sent = await self.port.send_code(phone)
            except TelegramError:
                raise
            except Exception as exc:  # noqa: BLE001 — a sentence, never a 500
                logger.warning(f"telegram: send code failed ({type(exc).__name__})")
                await self._drop_unsigned_port()
                raise TelegramError(UNREACHABLE) from exc
            if isinstance(sent, TgSentCode):
                self._code_hash, self._code_length = sent.hash, sent.length
            else:   # a port that answers the bare hash: the length is unknown, the app sizes the field itself
                self._code_hash, self._code_length = sent, None
            self._phone = phone
            self.state, self.error = "code_sent", None
        return self.status()

    async def submit_code(self, code: str) -> dict:
        async with self._lock:
            if self.port is None or self._phone is None or self._code_hash is None:
                raise TelegramError("Ask Telegram for a code first.")
            try:
                await self.port.sign_in(self._phone, "".join(str(code or "").split()), self._code_hash)
            except PasswordNeeded:
                self.state = "password"
                return self.status()
            except CodeInvalid:
                raise
            except TelegramError:
                raise
            except Exception as exc:  # noqa: BLE001 — a sentence, never a 500; the step can be tried again
                logger.warning(f"telegram: sign-in step failed ({type(exc).__name__})")
                raise TelegramError(UNREACHABLE) from exc
            await self._signed_in()
        return self.status()

    async def submit_password(self, password: str) -> dict:
        async with self._lock:
            if self.port is None or self.state != "password":
                raise TelegramError("Scan the QR or enter the code Telegram sent first.")
            try:
                await self.port.sign_in_password(str(password or ""))
            except PasswordInvalid:
                raise
            except TelegramError:
                raise
            except Exception as exc:  # noqa: BLE001 — a sentence, never a 500; the step can be tried again
                logger.warning(f"telegram: sign-in step failed ({type(exc).__name__})")
                raise TelegramError(UNREACHABLE) from exc
            await self._signed_in()
        return self.status()

    async def _signed_in(self) -> None:
        save_session(self.port.session_string())
        self._phone = self._code_hash = None
        self.state, self.error = "connected", None
        self._start_listening()

    async def disconnect(self) -> dict:
        """Log the session out at Telegram, then forget it here. A failed log-out still forgets it, and says so."""
        async with self._lock:
            self._stop_qr()
            if self.state in ("qr", "code_sent", "password") and load_session_safely() is None:
                # Stopping a sign-in half way: nothing was signed in, so nothing is logged out (and no false note).
                await self._drop_unsigned_port()
                self._phone = self._code_hash = None
                self.state, self.error = "off", None
                return self.status()
            note = None
            port = self.port
            if port is None and load_session_safely():
                try:
                    port = self._make(load_session_safely() or "")
                except TelegramError:
                    port = None
            self._stop_listening()
            if port is not None:
                try:
                    await port.log_out()
                except Exception as exc:  # noqa: BLE001 — the file goes whatever Telegram answered
                    note = ("Telegram didn't confirm the log-out; end the Cicada session from Telegram → Settings → "
                            "Devices → Active sessions.")
                    logger.warning(f"telegram: log-out failed ({type(exc).__name__})")
                try:
                    await port.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            forget_session()
            self.port, self._phone, self._code_hash = None, None, None
            self._dialogs = {}
            self.state, self.error = "off", note
        return self.status()

    async def stop(self) -> None:
        """Backend shutdown: stop listening and close the socket; the session stays kept."""
        self._stop_qr()
        self._stop_listening()
        if self.port is not None:
            try:
                await self.port.disconnect()
            except Exception:  # noqa: BLE001
                pass

    # Resuming a kept session ----------------------------------------------------------------------------------------

    async def resume(self) -> None:
        """At boot: a kept session starts listening and catches up the ticked chats; no session, nothing at all."""
        try:
            secret = load_session()
        except SessionRefused as exc:
            self.state, self.error = "ended", str(exc)
            return
        if not secret:
            return
        try:
            self.port = self._make(secret)
            if not await self.port.authorized():
                raise NotAuthorized("The Telegram session was ended — connect again to keep reading.")
        except TelegramError as exc:
            self.state, self.error = "ended", str(exc)
            return
        except Exception as exc:  # noqa: BLE001 — a network failure at boot: tried again on the next connect
            self.state, self.error = "ended", "Couldn't reach Telegram."
            logger.warning(f"telegram: resume failed ({type(exc).__name__})")
            return
        self.state = "connected"
        self._start_listening()
        asyncio.get_running_loop().create_task(self.catch_up())

    # The tick list --------------------------------------------------------------------------------------------------

    async def chats(self) -> list[dict]:
        if self.state != "connected" or self.port is None:
            raise TelegramError("Connect Telegram first.")
        dialogs = await self.port.dialogs(DIALOG_LIMIT)
        out = []
        for d in dialogs:
            row = telegram_source.listed(d)
            if row is not None:
                self._dialogs[row["id"]] = d
                out.append(row)
        return out

    async def one_to_one(self, cid: str) -> bool:
        """Whether Telegram itself lists ``cid`` as a one-to-one chat with a user (the listed dialogs hold only those,
        `telegram_source.listed`) — what the tick route checks, never the client's flag (#504 review B4)."""
        if self.state != "connected" or self.port is None:
            return False
        dialog = await self._dialog(cid)
        return dialog is not None and telegram_source.is_user_peer(dialog.chat) and not dialog.group

    async def photo(self, cid: str) -> bytes | None:
        """chats-ux-v2 (owner 2026-10-29: "why the pfp are not there") — a listed one-to-one chat's small profile
        photo, asked of Telegram once and kept outside every bank (``$CICADA_HOME/telegram/photos/<id>.jpg``, ids
        only; "none" remembered too) for :data:`PHOTO_TTL_S`. Picker display for any listed chat; a ticked chat's
        is also its page's picture (`messages_photos`, the route). Never raises past a sentence; None = no photo."""
        import time

        if not chat_live.ID_RE.match(str(cid)):
            return None
        folder_path = _private_dir() / PHOTO_DIR
        folder_path.mkdir(exist_ok=True)
        os.chmod(folder_path, 0o700)
        jpg, none = folder_path / f"{cid}.jpg", folder_path / f"{cid}.none"
        for path in (jpg, none):
            try:
                if time.time() - path.stat().st_mtime < PHOTO_TTL_S:
                    return path.read_bytes() if path is jpg else None
            except OSError:
                pass
        if self.state != "connected" or self.port is None:
            return jpg.read_bytes() if jpg.exists() else None
        dialog = await self._dialog(cid)
        if dialog is None:
            return None
        async with self._photos:
            try:
                data = await self.port.profile_photo(dialog.chat)
            except Exception as exc:  # noqa: BLE001 — a face without a photo draws its monogram
                logger.warning(f"telegram: profile photo failed ({type(exc).__name__})")
                return jpg.read_bytes() if jpg.exists() else None
        if not data or len(data) > PHOTO_MAX_BYTES:
            jpg.unlink(missing_ok=True)
            none.write_bytes(b"")
            return None
        tmp = jpg.with_name(f".{jpg.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, jpg)
        none.unlink(missing_ok=True)
        return data

    async def _dialog(self, cid: str) -> TgDialog | None:
        if cid not in self._dialogs and self.port is not None:
            await self.chats()
        return self._dialogs.get(cid)

    # Live -----------------------------------------------------------------------------------------------------------

    def _start_listening(self) -> None:
        if self._listen is None or self._listen.done():
            self._listen = asyncio.get_running_loop().create_task(self._run_listen())

    def _stop_listening(self) -> None:
        for task in (self._listen, self._flush):
            if task is not None and not task.done():
                task.cancel()
        self._listen = self._flush = None
        self._pending = {}

    async def _run_listen(self) -> None:
        try:
            await self.port.listen(self.on_event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the row says it; the next connect starts again
            self.error = "Telegram stopped sending updates."
            logger.warning(f"telegram: listening stopped ({type(exc).__name__})")

    async def on_event(self, event: TgEvent) -> None:
        """An update from Telegram: kept in memory until the next flush (an unticked chat's is dropped there)."""
        self._pending.setdefault(event.chat, []).append(event)
        if self._flush is None or self._flush.done():
            self._flush = asyncio.get_running_loop().create_task(self._flush_soon())

    async def _flush_soon(self) -> None:
        await asyncio.sleep(FLUSH_S)
        pending, self._pending = self._pending, {}
        await self.flush(pending)

    async def flush(self, pending: dict[int | None, list[TgEvent]], *, memory_root: Path | None = None) -> dict:
        """Stage pending events in the active bank: per ticked chat, its new and edited messages, deletes and reaction
        changes. ``{conversation: result}``; an unticked chat's events are dropped, never written."""
        import time

        from api.config import get_settings
        from api.services import bank_registry, demo_guard

        started = time.perf_counter()
        settings = get_settings()
        bank_registry.pin_request_bank(memory_root or settings.memory_root)
        memory_path = get_settings().memory_path
        if demo_guard.is_demo(memory_path):
            return {}
        # Ticked AND consented: a chat whose consent was withdrawn is not read, whatever the bank's tick says.
        ticked = chat_live.ticked_ids(memory_path, telegram_source.SPEC) & set(consents())
        by_cid: dict[str, dict] = {}
        orphans: list[int] = []
        for chat, events in pending.items():
            if chat is None:
                orphans += [i for e in events for i in e.ids]
                continue
            if not telegram_source.is_user_peer(chat):
                continue          # a group's or a channel's update: never read, whatever any file says (B4)
            cid = telegram_source.conversation_id(chat)
            if cid not in ticked:
                continue
            slot = by_cid.setdefault(cid, {"chat": chat, "messages": {}, "deleted": [], "reacted": {}})
            for e in events:
                if e.kind in ("new", "edit") and e.message is not None:
                    slot["messages"][e.message.id] = e.message
                elif e.kind == "delete":
                    slot["deleted"] += e.ids
                elif e.kind == "reactions":
                    for i in e.ids:
                        slot["reacted"][i] = e.reactions or []
        if orphans:
            # A private chat's delete names only message ids: find which ticked chat holds them.
            for cid in ticked:
                keys = {telegram_source.message_key(cid, i): i for i in orphans}
                hit = chat_live.holding(memory_path, telegram_source.SPEC, set(keys)).get(cid)
                if hit:
                    dialog = await self._dialog(cid)
                    if dialog is not None:
                        slot = by_cid.setdefault(cid, {"chat": dialog.chat, "messages": {}, "deleted": [],
                                                       "reacted": {}})
                        slot["deleted"] += [keys[k] for k in hit]
        results = {}
        for cid, slot in by_cid.items():
            out = await self._stage(memory_path, cid, slot["chat"], list(slot["messages"].values()),
                                    deleted=slot["deleted"], reacted=slot["reacted"])
            if "refused" not in out:     # a group or a withdrawn consent: refused by the ingest, nothing written
                results[cid] = out
        if results:
            self.flush_seconds = (self.flush_seconds + [time.perf_counter() - started])[-200:]
        return results

    async def _stage(self, memory_path: Path, cid: str, chat: int, messages: list[TgMessage], *,
                     deleted: list[int] = (), reacted: dict | None = None) -> dict:
        from starlette.concurrency import run_in_threadpool

        from api.services import folder_source, sync_state, write_admission

        dialog = await self._dialog(cid) if self.port is not None else None
        entry = {"id": cid, "chat": chat, "name": dialog.name if dialog else "",
                 "group": dialog.group if dialog else bool(
                     chat_live.load_settings(memory_path, telegram_source.SPEC)["conversations"].get(cid, {})
                     .get("group")),
                 "bot": dialog.bot if dialog else None}

        async def body():
            out = await run_in_threadpool(telegram_source.ingest, memory_path, entry, messages, deleted=list(deleted),
                                          reacted=reacted, bank=memory_path.name)
            sync_state.record_sync(memory_path, telegram_source.SPEC.channel,
                                   count=chat_live.live_count(memory_path, telegram_source.SPEC))
            await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Telegram sync",
                                                 trigger="capture/telegram-chats",
                                                 channel=telegram_source.SPEC.channel)
            return out

        try:
            out = await write_admission.run_admitted(memory_path, body)
        except (chat_live.NotSelected, telegram_source.NotOneToOne, telegram_source.NoConsent) as exc:
            return {"refused": type(exc).__name__}
        if messages:
            cursors = _cursors()
            cursors[cid] = max([cursors.get(cid, 0)] + [m.id for m in messages])
            _save_cursors(cursors)
        return out

    async def catch_up(self) -> None:
        """What arrived in each ticked chat while the backend was down — past each chat's cursor."""
        from api.config import get_settings

        memory_path = get_settings().memory_path
        cursors = _cursors()
        for cid in chat_live.ticked_ids(memory_path, telegram_source.SPEC) & set(consents()):
            if cid in cursors:
                try:
                    await self.read(cid, min_id=cursors[cid])
                except Exception as exc:  # noqa: BLE001 — one chat's failure never stops the others
                    logger.warning(f"telegram: catch-up failed ({type(exc).__name__})")

    async def read(self, cid: str, *, min_id: int = 0, cap: int = HISTORY_CAP) -> dict:
        """One ticked chat read from Telegram past ``min_id`` (0 = everything Telegram holds — the person's history
        ask), oldest first, staged in batches. Live messages keep arriving through :meth:`on_event` meanwhile."""
        from api.config import get_settings
        from api.services import bank_registry

        if self.state != "connected" or self.port is None:
            raise TelegramError("Connect Telegram first.")
        if bank_registry.pinned_bank() is None:   # a background read: pinned to the bank active now (G183(d))
            bank_registry.pin_request_bank(get_settings().memory_root)
        dialog = await self._dialog(cid)
        if dialog is None:
            raise TelegramError("Telegram no longer lists this one-to-one chat.")
        memory_path = get_settings().memory_path
        totals = {"read": 0, "created": 0, "updated": 0}
        batch: list[TgMessage] = []
        async for m in self.port.history(dialog.chat, min_id=min_id, limit=cap):
            batch.append(m)
            if len(batch) >= HISTORY_BATCH:
                out = await self._stage(memory_path, cid, dialog.chat, batch)
                totals = _add(totals, out, len(batch))
                batch = []
        if batch:
            out = await self._stage(memory_path, cid, dialog.chat, batch)
            totals = _add(totals, out, len(batch))
        return totals


def _iso(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _add(totals: dict, out: dict, n: int) -> dict:
    return {"read": totals["read"] + n, "created": totals["created"] + int(out.get("created") or 0),
            "updated": totals["updated"] + int(out.get("updated") or 0)}


def load_session_safely() -> str | None:
    try:
        return load_session()
    except SessionRefused:
        return None


ACCOUNT = Account()
