"""G212 (owner 2026-10-29): seamless, secure devices. A paired device's token can be bound to a key that never leaves
the device (DPoP-style, RFC 9449's shape): the server keeps the key's thumbprint, and a bound token works only with a
fresh proof of that key for that very request. Already-paired devices keep working, unbound, and may bind themselves.
A phone asks to be capture-only and can never widen its code. Revoking takes effect on the next request. The guided
reach setup only reads Tailscale's state and checks the served address the way a phone would.

Synthetic bank, placeholder names, no network, never the real tailscale CLI; keys are made here in software."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.remote import reach
from api.services import device_proof, device_tokens

BASE = "https://mac.example.ts.net:8443"


@pytest.fixture
def server(tmp_path, monkeypatch):
    from api import config
    from api.main import app

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(reach, "tailnet_backend", lambda port, **kw: reach.TailnetBackend("missing", None))
    config.get_settings.cache_clear()
    device_proof.reset()
    from api.routers import devices as devices_router

    monkeypatch.setattr(devices_router, "_WRONG_CODES", None)   # the /pair rate bucket is per process; one per test
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master
    config.get_settings.cache_clear()


def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _signed(key, token, method, path, **kw):
    return {**_bearer(token), "DPoP": device_proof.make_proof(key, method, f"{BASE}{path}", token=token, **kw)}


def _pair(client, master, *, key=None, kind=None, ask=None, name="Example Phone"):
    made = client.post("/devices/pairing", json={"kind": kind} if kind else {}, headers=_bearer(master)).json()
    headers = {"DPoP": device_proof.make_proof(key, "POST", f"{BASE}/pair")} if key is not None else {}
    body = {"code": made["code"], "name": name, **({"kind": ask} if ask else {})}
    got = client.post("/pair", json=body, headers=headers)
    assert got.status_code == 201, got.text
    return got.json()["device"], got.json()["token"]


def _reason(response) -> str:
    header = response.headers.get("www-authenticate", "")
    assert header.startswith('DPoP error="invalid_dpop_proof"'), header
    return header.split('error_description="')[1].rstrip('"')


# --- a token born key-bound ------------------------------------------------------------------------------------------

def test_a_device_that_pairs_with_a_proof_is_key_bound_and_a_copied_token_alone_is_useless(server):
    client, master = server
    key = _key()
    device, token = _pair(client, master, key=key)
    assert device["keyBound"] is True and device["keyBoundAt"]
    # The token alone — what a copy of it would be — is refused, never a fall back to bearer.
    bare = client.get("/capture/mine", headers=_bearer(token))
    assert bare.status_code == 401 and _reason(bare) == "missing"
    # With the device's own proof for this very request it works, under either scheme.
    assert client.get("/capture/mine", headers=_signed(key, token, "GET", "/capture/mine")).status_code == 200
    dpop_scheme = _signed(key, token, "POST", "/capture/note")
    dpop_scheme["Authorization"] = f"DPoP {token}"
    assert client.post("/capture/note", json={"text": "a thought", "id": "n1"}, headers=dpop_scheme).status_code == 200
    # Another key holding the same token — the copied token in someone else's hands — is refused.
    thief = client.get("/capture/mine", headers=_signed(_key(), token, "GET", "/capture/mine"))
    assert thief.status_code == 401 and _reason(thief) == "wrong_key"


@pytest.mark.parametrize("bend, reason", [
    (lambda key, token: _signed(key, token, "GET", "/graph"), "wrong_request"),          # signed for another path
    (lambda key, token: _signed(key, token, "POST", "/capture/mine"), "wrong_request"),   # another method
    (lambda key, token: _signed(key, token, "GET", "/capture/mine", now=time.time() - 3600), "stale"),
    (lambda key, token: {**_bearer(token), "DPoP": device_proof.make_proof(
        key, "GET", f"{BASE}/capture/mine", token="cic_dev_aaaaaaaa_" + "b" * 43)}, "wrong_token"),
    (lambda key, token: {**_bearer(token), "DPoP": "not.a.proof"}, "malformed"),
])
def test_every_failing_proof_names_its_step(server, bend, reason):
    client, master = server
    key = _key()
    _, token = _pair(client, master, key=key)
    answer = client.get("/capture/mine", headers=bend(key, token))
    assert answer.status_code == 401 and _reason(answer) == reason
    assert answer.json()["detail"] == "This device's token works only with its own key, and this request's proof " \
                                      "did not pass. Check the device's clock, or pair it again."


def test_a_proof_is_good_for_one_request_only(server):
    client, master = server
    key = _key()
    _, token = _pair(client, master, key=key)
    headers = _signed(key, token, "GET", "/capture/mine")
    assert client.get("/capture/mine", headers=headers).status_code == 200
    again = client.get("/capture/mine", headers=headers)
    assert again.status_code == 401 and _reason(again) == "replayed"


def test_a_proof_that_does_not_pass_at_pairing_spends_nothing(server):
    client, master = server
    made = client.post("/devices/pairing", json={}, headers=_bearer(master)).json()
    stale = device_proof.make_proof(_key(), "POST", f"{BASE}/pair", now=time.time() - 3600)
    refused = client.post("/pair", json={"code": made["code"], "name": "Example Phone"}, headers={"DPoP": stale})
    assert refused.status_code == 400 and "stale" in refused.json()["detail"]
    # The code still waits: the same phone with a good clock pairs with it.
    key = _key()
    fresh = {"DPoP": device_proof.make_proof(key, "POST", f"{BASE}/pair")}
    assert client.post("/pair", json={"code": made["code"], "name": "Example Phone"}, headers=fresh).status_code == 201


def _bind_in_store(device_id: str, key) -> None:
    """A full device bound in the store itself — the API refuses to make one (review 2026-10-29), but the gate must
    still hold for a row that is bound however it got there."""
    jkt = device_proof.thumbprint(device_proof.public_jwk(key))
    db = sqlite3.connect(device_tokens.store().path)
    db.execute("UPDATE devices SET key_thumbprint=?, key_bound_at='2026-10-29T00:00:00+00:00' WHERE id=?",
               (jkt, device_id))
    db.commit()
    db.close()


def test_healthz_says_more_to_a_bound_computer_only_with_its_proof(server):
    client, master = server
    key = _key()
    device, token = _pair(client, master, kind="full", name="laptop")
    _bind_in_store(device["id"], key)
    assert client.get("/healthz", headers=_bearer(token)).json().get("memoryPath") is None
    full = client.get("/healthz", headers=_signed(key, token, "GET", "/healthz")).json()
    assert full.get("memoryPath")


# --- review 2026-10-29 -----------------------------------------------------------------------------------------------

def _sign_raw(key, claims_json: str) -> str:
    """A proof whose claims are exactly ``claims_json`` (so a test can put NaN in it), properly signed."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": device_proof.public_jwk(key)}
    signing = device_proof.b64url(json.dumps(header).encode()) + "." + device_proof.b64url(claims_json.encode())
    r, s_ = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing}.{device_proof.b64url(r.to_bytes(32, 'big') + s_.to_bytes(32, 'big'))}"


@pytest.mark.parametrize("iat", ["NaN", "Infinity", "-Infinity", "1800000000.5", '"1800000000"', "true",
                                 "1" + "0" * 400])
def test_a_proof_whose_time_is_not_a_whole_number_never_passes(iat):
    """Review B1: `json` reads NaN, and NaN passes every comparison — a NaN proof would never expire."""
    device_proof.reset()
    key = _key()
    claims = (f'{{"htm":"GET","htu":"{BASE}/capture/mine","iat":{iat},"jti":"jti-{abs(hash(iat))}"}}')
    for moment in (time.time(), time.time() + 10**7):          # now, and 10^7 seconds later
        with pytest.raises(device_proof.ProofError) as caught:
            device_proof.verify(_sign_raw(key, claims), method="GET", path="/capture/mine", now=moment)
        assert caught.value.reason == "malformed", iat
    good = f'{{"htm":"GET","htu":"{BASE}/capture/mine","iat":{int(time.time())},"jti":"jti-good-1"}}'
    assert device_proof.verify(_sign_raw(key, good), method="GET", path="/capture/mine")


def test_a_non_string_method_or_url_or_ath_is_refused():
    device_proof.reset()
    key = _key()
    now = int(time.time())
    for claims, reason in (
            (f'{{"htm":["GET"],"htu":"{BASE}/x","iat":{now},"jti":"jti-a-0001"}}', "wrong_request"),
            (f'{{"htm":"GET","htu":7,"iat":{now},"jti":"jti-a-0002"}}', "wrong_request"),
            (f'{{"htm":"GET","htu":"{BASE}/x","iat":{now},"jti":"jti-a-0003","ath":1}}', "wrong_token")):
        with pytest.raises(device_proof.ProofError) as caught:
            device_proof.verify(_sign_raw(key, claims), method="GET", path="/x", token="cic_dev_abcd1234_" + "x" * 43)
        assert caught.value.reason == reason


def test_a_computer_is_never_key_bound_yet_and_its_code_still_waits(server):
    client, master = server
    made = client.post("/devices/pairing", json={"kind": "full"}, headers=_bearer(master)).json()
    proof = {"DPoP": device_proof.make_proof(_key(), "POST", f"{BASE}/pair")}
    refused = client.post("/pair", json={"code": made["code"], "name": "laptop"}, headers=proof)
    assert refused.status_code == 409 and refused.json()["code"] == "full_device"
    assert "can't sign" in refused.json()["detail"]
    # Nothing was spent: the computer pairs with the same code, without a key.
    assert client.post("/pair", json={"code": made["code"], "name": "laptop"}).status_code == 201
    # A computer paired the old way cannot lock itself either; narrowing to capture first is the one way in.
    _, token = _pair(client, master, kind="full", name="laptop-2")
    key = _key()
    bind = client.post("/devices/me/key", json={}, headers=_signed(key, token, "POST", "/devices/me/key"))
    assert bind.status_code == 409 and bind.json()["code"] == "full_device"
    assert client.get("/graph", headers=_bearer(token)).status_code == 200      # it keeps working, unchanged


def test_the_status_row_says_when_the_device_was_locked_to_its_key(server):
    client, master = server
    _pair(client, master, key=_key(), name="Example Phone")
    row = next(r for r in client.get("/devices/status", headers=_bearer(master)).json()["devices"]
               if r["name"] == "Example Phone")
    assert row["keyBound"] is True and row["keyBoundAt"]


def test_a_funnel_beside_a_tailnet_serve_is_never_hidden():
    """Review 2026-10-29: the backend served to the tailnet on 8443 AND funnelled on 443 is open to the internet."""
    both = {"Web": {"mac.example.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}},
                    "mac.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}},
            "AllowFunnel": {"mac.example.ts.net:443": True}}
    assert reach.serve_url_for_port(both, 8000) == ("https://mac.example.ts.net:8443", True)
    # Either order in the ServeConfig: the funnel listed first must not hide the serve's address, nor the reverse.
    reordered = {"Web": dict(reversed(list(both["Web"].items()))), "AllowFunnel": both["AllowFunnel"]}
    assert reach.serve_url_for_port(reordered, 8000) == ("https://mac.example.ts.net:8443", True)
    kw, _ = _fake_tailscale({"BackendState": "Running", "Self": {"DNSName": "mac.example.ts.net."}}, both)
    answer = reach.guide(8000, **kw)
    assert answer["step"] == "unfunnel" and answer["url"] is None
    assert answer["command"] == "tailscale funnel --https=443 off"


def test_a_funnelled_backend_puts_no_address_in_a_qr_even_beside_a_serve(server, monkeypatch):
    client, master = server
    monkeypatch.setattr(reach, "tailnet_backend", lambda port, **kw: reach.TailnetBackend(
        "running", "https://mac.example.ts.net:8443", True, 443))
    made = client.post("/devices/pairing", json={}, headers=_bearer(master)).json()
    assert made["qr"]["url"] is None and made["reach"]["public"] is True and made["reach"]["url"] is None


# --- already-paired devices: they keep working, and bind themselves -------------------------------------------------

def test_an_unbound_device_keeps_working_and_binds_itself_once(server):
    client, master = server
    device, token = _pair(client, master)                 # paired the old way: no proof
    assert device["keyBound"] is False
    assert client.get("/capture/mine", headers=_bearer(token)).status_code == 200
    # The bind needs the proof (with the token's ath); without one nothing changes.
    assert _reason(client.post("/devices/me/key", json={}, headers=_bearer(token))) == "missing"
    key = _key()
    bound = client.post("/devices/me/key", json={}, headers=_signed(key, token, "POST", "/devices/me/key"))
    assert bound.status_code == 200 and bound.json()["changed"] is True and bound.json()["device"]["keyBound"]
    # From the next request on, the token alone is refused and the proof works.
    assert client.get("/capture/mine", headers=_bearer(token)).status_code == 401
    assert client.get("/capture/mine", headers=_signed(key, token, "GET", "/capture/mine")).status_code == 200
    # The same key again changes nothing; another key never takes over a bound device.
    same = client.post("/devices/me/key", json={}, headers=_signed(key, token, "POST", "/devices/me/key"))
    assert same.status_code == 200 and same.json()["changed"] is False
    other = client.post("/devices/me/key", json={}, headers=_signed(_key(), token, "POST", "/devices/me/key"))
    assert other.status_code == 401 and _reason(other) == "wrong_key"


def test_a_full_phone_from_before_kinds_narrows_itself_to_capture_only(server):
    client, master = server
    _, token = _pair(client, master, kind="full")         # a phone paired before #432 is `full`
    assert client.get("/graph", headers=_bearer(token)).status_code == 200
    key = _key()
    answer = client.post("/devices/me/key", json={"narrow": "capture"},
                         headers=_signed(key, token, "POST", "/devices/me/key")).json()
    assert answer["device"]["kind"] == "capture" and answer["device"]["keyBound"]
    assert client.get("/graph", headers=_signed(key, token, "GET", "/graph")).status_code == 403
    # Nothing widens: the self route takes no "full".
    assert client.post("/devices/me/key", json={"narrow": "full"},
                       headers=_signed(key, token, "POST", "/devices/me/key")).status_code == 422


def test_the_self_route_is_the_only_device_route_a_device_may_write_and_the_master_has_no_device(server):
    client, master = server
    _, token = _pair(client, master)
    assert client.post("/devices/pairing", json={}, headers=_bearer(token)).status_code == 403
    assert client.post("/devices/me/key", json={}, headers=_bearer(master)).status_code == 400


def test_a_device_asks_to_be_capture_only_and_can_never_widen_its_code(server):
    client, master = server
    narrowed, _ = _pair(client, master, kind="full", ask="capture")
    assert narrowed["kind"] == "capture"
    kept, _ = _pair(client, master, kind="capture", ask="full")
    assert kept["kind"] == "capture"
    computer, _ = _pair(client, master, kind="full", name="laptop")
    assert computer["kind"] == "full"


def test_revoking_takes_effect_on_the_very_next_request(server):
    client, master = server
    key = _key()
    device, token = _pair(client, master, key=key)
    assert client.get("/capture/mine", headers=_signed(key, token, "GET", "/capture/mine")).status_code == 200
    assert client.delete(f"/devices/{device['id']}", headers=_bearer(master)).status_code == 200
    assert client.get("/capture/mine", headers=_signed(key, token, "GET", "/capture/mine")).status_code == 401


def test_the_devices_list_says_each_ones_kind_and_key_state(server):
    client, master = server
    _pair(client, master, key=_key(), name="Example Phone")
    _pair(client, master, kind="full", name="laptop")
    rows = {r["name"]: r for r in client.get("/devices/status", headers=_bearer(master)).json()["devices"]}
    assert (rows["Example Phone"]["kind"], rows["Example Phone"]["keyBound"]) == ("capture", True)
    assert (rows["laptop"]["kind"], rows["laptop"]["keyBound"]) == ("full", False)
    listed = client.get("/devices", headers=_bearer(master)).json()["devices"]
    assert all("thumbprint" not in json.dumps(d).lower() for d in listed)      # the wire says bound, never the key


def test_an_older_store_gains_the_key_columns_and_reads_every_device_as_unbound(tmp_path):
    path = tmp_path / "devices.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, "
               "created_at TEXT NOT NULL, revoked_at TEXT, last_used_at TEXT, use_count INTEGER NOT NULL DEFAULT 0, "
               "kind TEXT NOT NULL DEFAULT 'full')")
    db.execute("INSERT INTO devices (id, name, token_hash, created_at) VALUES ('abcd1234', 'phone', 'x', '2026-10-22')")
    db.commit()
    db.close()
    device = device_tokens.DeviceStore(path).get("abcd1234")
    assert device.key_bound is False and device.wire()["keyBound"] is False


# --- the proof itself ------------------------------------------------------------------------------------------------

def _forge(header: dict, claims: dict, signature: bytes = b"\0" * 64) -> str:
    enc = lambda obj: device_proof.b64url(json.dumps(obj).encode())
    return f"{enc(header)}.{enc(claims)}.{device_proof.b64url(signature)}"


def test_the_verifier_refuses_what_is_not_an_es256_proof_of_a_public_key():
    device_proof.reset()
    key = _key()
    jwk = device_proof.public_jwk(key)
    claims = {"htm": "GET", "htu": f"{BASE}/x", "iat": int(time.time()), "jti": "abcdefgh12"}
    cases = {
        "unsupported": _forge({"typ": "dpop+jwt", "alg": "none", "jwk": jwk}, claims),
        "malformed": _forge({"typ": "jwt", "alg": "ES256", "jwk": jwk}, claims),
        "bad_signature": _forge({"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk}, claims),
    }
    with_private = dict(jwk, d=device_proof.b64url(key.private_numbers().private_value.to_bytes(32, "big")))
    cases["malformed "] = _forge({"typ": "dpop+jwt", "alg": "ES256", "jwk": with_private}, claims)
    for reason, proof in cases.items():
        with pytest.raises(device_proof.ProofError) as caught:
            device_proof.verify(proof, method="GET", path="/x")
        assert caught.value.reason == reason.strip()
    good = device_proof.make_proof(key, "GET", f"{BASE}/x/")
    assert device_proof.verify(good, method="get", path="/x") == device_proof.thumbprint(jwk)


def test_the_thumbprint_is_rfc_7638s():
    # RFC 7638 §3.1 computes over the required members only, in lexicographic order, with no whitespace.
    jwk = {"kty": "EC", "crv": "P-256", "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
           "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0", "kid": "ignored"}
    import base64
    import hashlib

    canonical = ('{"crv":"P-256","kty":"EC","x":"f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",'
                 '"y":"x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"}')
    expected = base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()
    assert device_proof.thumbprint(jwk) == expected


# --- the guided reach setup ------------------------------------------------------------------------------------------

def _fake_tailscale(status: dict | None, serve: dict | None = None, *, exists=True):
    calls = []

    class Done:
        def __init__(self, out, code=0):
            self.stdout, self.returncode = out, code

    def run(argv, **kw):
        calls.append(argv[1:])
        assert argv[1:] in (["status", "--json"], ["funnel", "status", "--json"]), argv   # reads only, never a change
        if argv[1] == "status":
            return Done(json.dumps(status) if status is not None else "", 0 if status else 1)
        return Done(json.dumps(serve or {}))

    which = (lambda name: "/opt/fake/tailscale" if name == "tailscale" else None) if exists else (lambda name: None)
    return dict(which=which, run=run, exists=lambda path: False), calls


def _serve(port: int, *, funnel: bool = False, hostport="mac.example.ts.net:8443") -> dict:
    return {"Web": {hostport: {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{port}"}}}},
            **({"AllowFunnel": {hostport: True}} if funnel else {})}


@pytest.mark.parametrize("status, serve, step, command", [
    (None, None, "install", None),
    ({}, None, "open", None),
    ({"BackendState": "NeedsLogin"}, None, "sign-in", None),
    ({"BackendState": "Stopped"}, None, "turn-on", None),
    ({"BackendState": "Running", "Self": {"DNSName": "mac.example.ts.net."}}, {}, "serve",
     "tailscale serve --bg --https=8443 8000"),
    ({"BackendState": "Running", "Self": {"DNSName": "mac.example.ts.net."}}, _serve(8000, funnel=True,
                                                                                     hostport="mac.example.ts.net:443"),
     "unfunnel", "tailscale funnel --https=443 off"),
    ({"BackendState": "Running", "Self": {"DNSName": "mac.example.ts.net."}}, _serve(8000), "ready", None),
])
def test_the_guide_names_the_one_next_step_from_reads_alone(status, serve, step, command):
    kw, calls = _fake_tailscale(status, serve, exists=status is not None)
    answer = reach.guide(8000, **kw)
    assert answer["step"] == step and answer["command"] == command
    assert answer["step"] in reach.GUIDE_STEPS
    if step == "ready":
        assert answer["url"] == "https://mac.example.ts.net:8443" and answer["dnsName"] == "mac.example.ts.net"
    else:
        assert answer["url"] is None                     # a funnelled or missing serve never reaches a QR


def _healthz(version="0.7.3", bank="bank-a", status=200):
    return lambda url, timeout: (status, json.dumps({"status": "ok", "version": version, "bankId": bank}))


@pytest.mark.parametrize("resolve, fetch, failed", [
    (lambda host, port: (_ for _ in ()).throw(OSError("no such host")), _healthz(), "dns"),
    (lambda host, port: [], lambda url, timeout: (_ for _ in ()).throw(ConnectionError("refused")), "overlay"),
    (lambda host, port: [], lambda url, timeout: (502, "Bad Gateway"), "backend"),
    (lambda host, port: [], lambda url, timeout: (200, "<html>router</html>"), "not-cicada"),
    (lambda host, port: [], _healthz(bank="bank-b"), "other-cicada"),
    (lambda host, port: [], _healthz(), None),
])
def test_the_live_check_names_where_it_stopped(resolve, fetch, failed):
    got = reach.self_check("https://mac.example.ts.net:8443", version="0.7.3", bank_id="bank-a",
                           resolve=resolve, fetch=fetch)
    assert got["failed"] == failed and got["ok"] is (failed is None)
    assert failed is None or failed in reach.CHECK_FAILURES


def test_the_reach_route_is_the_servers_and_checks_only_when_asked(server, monkeypatch):
    client, master = server
    asked = []
    monkeypatch.setattr(reach, "guide", lambda port, **kw: {"tailscale": "running", "dnsName": "mac.example.ts.net",
                                                            "url": "https://mac.example.ts.net:8443",
                                                            "command": None, "step": "ready"})
    monkeypatch.setattr(reach, "self_check", lambda url, **kw: asked.append(url) or {"ok": True, "failed": None,
                                                                                    "ms": 12})
    plain = client.get("/devices/reach", headers=_bearer(master)).json()
    assert plain["step"] == "ready" and plain["check"] is None and asked == []
    checked = client.get("/devices/reach?check=true", headers=_bearer(master)).json()
    assert checked["check"]["ok"] is True and asked == ["https://mac.example.ts.net:8443"]
    _, token = _pair(client, master, kind="full", name="laptop")
    assert client.get("/devices/reach", headers=_bearer(token)).status_code == 403
