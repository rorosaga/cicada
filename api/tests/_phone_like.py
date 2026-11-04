"""A client shaped like the phone of ruling 51f (owner 2026-11-03: "for now, the phone i mainly want it as a way to
capture"): a capture-only device token bound to its own P-256 key, no copy, no follower — only a durable outbox of
captures and the same ordered route list a computer runs (``sync_routes``), through the home's door (``sync_door``).

It is the reference for the phone app's later build: everything here is what that app must do, in Swift or React
Native, and nothing here is a backend. Captures go to the existing capture routes (``/capture/note``) with an
``Idempotency-Key``, so a resend by any route is the first answer.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from api.services import device_proof, sync_door, sync_routes, tx_outbox


class PhoneKey:
    """The phone's Secure-Enclave key, played by a software P-256 key."""

    def __init__(self):
        self.k = ec.generate_private_key(ec.SECP256R1())
        self.jwk = device_proof.public_jwk(self.k)

    def sign(self, data: bytes) -> str:
        r, s = decode_dss_signature(self.k.sign(data, ec.ECDSA(hashes.SHA256())))
        return base64.urlsafe_b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).rstrip(b"=").decode()

    def proof(self, method: str, url: str) -> str:
        return device_proof.make_proof(self.k, method, url)


class PhoneLike:
    def __init__(self, folder: Path, device_id: str, key: PhoneKey, door: dict):
        """``door`` is what pairing handed the phone (``POST /devices/pairing``'s ``door``: the home's id, its signing
        key, its door key, port and addresses)."""
        self.folder = folder
        self.key = key
        self.identity = sync_door.Identity(device_id, key.jwk, key.sign)
        self.target = sync_door.Target(door["home"], sync_door._b64d(door["key"]), door["sign"])   # noqa: SLF001
        self.book = sync_routes.Book("device", fingerprint=None)
        self.pool = sync_door.Pool()
        self.found: list[tuple[str, int]] = []
        self.learned: dict | None = None
        self.sent: list[str] = []

    # -- routes: what the app's Bonjour found, then what the door said last ----------------------------------------
    def find(self, host: str, port: int) -> None:
        self.found.insert(0, (host, port))
        self.book.note_network_change()

    def network_changed(self) -> None:
        self.pool.drop()
        self.book.note_network_change()

    def _learn(self, _device: str, routes: dict) -> None:
        self.learned = routes

    def routes(self) -> list[sync_routes.Route]:
        out = [sync_routes.Route("lan", "door", h, p) for h, p in self.found]
        if self.learned:
            out += sync_routes.door_routes(self.learned, lan_ok=True, tailnet_ok=False)
        return sync_routes.order(out)

    # -- sending -------------------------------------------------------------------------------------------------------
    def _send(self, entry: dict):
        def attempt(route):
            try:
                return sync_door.request(route.host, route.port, self.target, self.identity, entry["method"],
                                         entry["path"], body=base64.b64decode(entry["body"]),
                                         headers={"Idempotency-Key": entry["id"],
                                                  "Content-Type": entry["contentType"]},
                                         timeout=15, connect_timeout=route.connect_s, on_routes=self._learn,
                                         pool=self.pool, carrier=route.carrier)
            except sync_door.Unreachable:
                raise sync_routes.NoAnswer("unreachable") from None
            except sync_door.Dropped:
                raise sync_routes.NoAnswer("timeout") from None

        try:
            status, _h, body = sync_routes.drive(self.book, self.routes(), attempt)
        except sync_routes.NoAnswer as exc:
            return None, {"_noAnswer": exc.kind}
        self.sent.append(entry["id"])
        return status, body if isinstance(body, dict) else None

    def capture(self, text: str, *, key: str | None = None):
        """Keep the note in the outbox, then send what waits. ``(verdict, status, body)`` for this note."""
        body = json.dumps({"text": text}).encode()
        entry = tx_outbox.rest_entry("POST", "/capture/note", "", body, "application/json", bank_id=None,
                                     base_seq=None, key=key or uuid.uuid4().hex)
        return tx_outbox.submit(entry, self._send, home=self.folder, deadline_s=20)

    def flush(self, now=time.time):
        return tx_outbox.flush(self._send, home=self.folder, deadline_s=20, now=now)

    def waiting(self) -> int:
        return tx_outbox.counts(self.folder)["waiting"]
