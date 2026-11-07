"""G132 phase 3a — pairing over an untrusted relay (gate g3): the QR pins the home's keys; a typed code shows the same
six digits on both screens only when nobody stood between them. The relay is played by the test, honest or not."""
from __future__ import annotations

import pytest
from nacl import pwhash

from api.services.sync_relay_crypto import Home, Keys, Refused
from api.services.sync_relay_pairing import (DevicePairing, HomePairing, qr_payload, random_slot, slot_for_code)

CODE = "ABCD-EFGH"
FAST = {"ops": pwhash.argon2id.OPSLIMIT_MIN, "mem": pwhash.argon2id.MEMLIMIT_MIN}
RELAY = "wss://relay.example/v1"
TOKEN = "cic_dev_" + "x" * 40   # a stand-in: 3b issues the real one from device_tokens


def test_the_qr_path_pins_the_home_and_hands_over_the_token_and_the_epoch_key():
    home = Home.create()
    slot = random_slot()
    hp = HomePairing(home=home, code=CODE, slot=slot, typed=False)
    qr = qr_payload(CODE, RELAY, slot, home.keys)
    assert set(qr) == {"v", "code", "relay", "slot", "home"} and qr["home"] == home.keys.public()
    dp = DevicePairing.from_qr(qr, name="laptop")
    dp.read_offer(hp.offer())
    candidate, reveal = hp.receive(dp.request())
    assert reveal is None and candidate.sas is None and candidate.name == "laptop"
    sealed, epoch_frame = hp.welcome(TOKEN, confirmed=True)
    assert TOKEN.encode() not in sealed and TOKEN.encode() not in epoch_frame
    token, endpoint = dp.accept_welcome(sealed, confirmed=False)
    assert token == TOKEN and endpoint.epoch == home.epoch and endpoint.mailbox == home.mailbox
    assert endpoint.open(home.seal("delta", b"first", meta={"seq": 1})[0]).payload == b"first"


def test_the_qr_path_refuses_a_substituted_offer_and_the_relay_cannot_read_the_request():
    home, mallory = Home.create(), Home.create()
    slot = random_slot()
    dp = DevicePairing.from_qr(qr_payload(CODE, RELAY, slot, home.keys), name="laptop")
    with pytest.raises(Refused) as exc:
        dp.read_offer(HomePairing(home=mallory, code=CODE, slot=slot, typed=False).offer())
    assert exc.value.code == "wrong_home"
    request = dp.request()
    assert CODE.encode() not in request
    with pytest.raises(Refused):
        HomePairing(home=mallory, code=CODE, slot=slot, typed=False).receive(request)


def test_the_typed_path_shows_the_same_six_digits_on_both_screens():
    home = Home.create()
    slot = slot_for_code(CODE, **FAST)
    assert slot == slot_for_code("abcdefgh", **FAST) and CODE not in slot
    hp = HomePairing(home=home, code=CODE, slot=slot, typed=True)
    dp = DevicePairing.from_code(CODE, name="phone", **FAST)
    dp.read_offer(hp.offer())
    candidate, reveal = hp.receive(dp.request())
    shown = dp.read_reveal(reveal)
    assert candidate.sas == shown and len(shown) == 7 and shown[3] == " "
    with pytest.raises(Refused) as exc:
        hp.welcome(TOKEN, confirmed=False)
    assert exc.value.code == "not_confirmed"
    sealed, _ = hp.welcome(TOKEN, confirmed=True)
    with pytest.raises(Refused):
        dp.accept_welcome(sealed, confirmed=False)
    token, endpoint = dp.accept_welcome(sealed, confirmed=True)
    assert token == TOKEN and endpoint.home == home.me


def test_a_relay_in_the_middle_of_a_typed_pairing_cannot_make_the_digits_match():
    """Mallory runs the relay: she answers the device as a fake home and the home as a fake device."""
    home, fake_home = Home.create(), Home.create()
    slot = slot_for_code(CODE, **FAST)
    real = HomePairing(home=home, code=CODE, slot=slot, typed=True)
    fake = HomePairing(home=fake_home, code=CODE, slot=slot, typed=True)
    device = DevicePairing.from_code(CODE, name="phone", **FAST)
    device.read_offer(fake.offer())                       # the device sees Mallory's offer
    _, fake_reveal = fake.receive(device.request())       # she learns the code from the device's request ...
    fake_device = DevicePairing.from_code(CODE, name="phone", **FAST)
    fake_device.read_offer(real.offer())
    candidate, _ = real.receive(fake_device.request())    # ... and answers the real home herself
    assert device.read_reveal(fake_reveal) != candidate.sas
    # The person sees two different numbers and cancels; the home never releases the welcome unconfirmed.
    with pytest.raises(Refused):
        real.welcome(TOKEN, confirmed=False)


def test_a_wrong_code_is_refused_and_a_second_answer_voids_the_slot():
    home = Home.create()
    slot = random_slot()
    hp = HomePairing(home=home, code=CODE, slot=slot, typed=False)
    qr = qr_payload(CODE, RELAY, slot, home.keys)
    wrong = DevicePairing.from_qr(qr | {"code": "ZZZZ-ZZZZ"}, name="x")
    with pytest.raises(Refused) as exc:
        hp.receive(wrong.request())
    assert exc.value.code == "bad_code"
    hp.receive(DevicePairing.from_qr(qr, name="laptop").request())
    with pytest.raises(Refused) as exc:
        hp.receive(DevicePairing.from_qr(qr, name="other").request())
    assert exc.value.code == "pairing_void"
    with pytest.raises(Refused):
        hp.welcome(TOKEN, confirmed=True)


def test_a_reveal_that_breaks_the_commitment_is_refused():
    home = Home.create()
    slot = slot_for_code(CODE, **FAST)
    hp = HomePairing(home=home, code=CODE, slot=slot, typed=True)
    dp = DevicePairing.from_code(CODE, name="phone", **FAST)
    dp.read_offer(hp.offer())
    other = HomePairing(home=home, code=CODE, slot=slot, typed=True)   # same keys, another nonce
    _, reveal = other.receive(dp.request())
    with pytest.raises(Refused) as exc:
        dp.read_reveal(reveal)
    assert exc.value.code == "bad_commitment"


def test_the_keys_are_fresh_per_device():
    a, b = Keys.generate(), Keys.generate()
    assert a.public() != b.public() and Keys.load(a.export()).public() == a.public()
