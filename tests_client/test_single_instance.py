# -*- coding: utf-8 -*-
"""Instance unique : deux « instances » dans le meme processus, fichier perime, secret different, client
muet ou malveillant (le serveur ne se bloque pas)."""
import json
import os
import socket
import threading
import time

import pytest

import single_instance as si


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "inst"
    d.mkdir()
    return str(d)


def _wait(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_deuxieme_lancement_transmet_ses_arguments(data):
    got = []
    first = si.SingleInstance(data, on_message=got.append)
    try:
        assert first.acquire(["--debug"]) is True
        info = json.load(open(os.path.join(data, "instance.json"), encoding="utf-8"))
        assert info["port"] == first.port and info["pid"] == os.getpid()
        assert len(info["secret_hash"]) == 64
        key = open(os.path.join(data, "instance.key"), encoding="ascii").read()
        assert key not in json.dumps(info), "le secret ne doit pas être dans instance.json"
        second = si.SingleInstance(data)
        assert second.acquire(["--url", "dodotopia://room/K7P2QD"]) is False
        assert _wait(lambda: got == [["--url", "dodotopia://room/K7P2QD"]])
        third = si.SingleInstance(data)
        assert third.acquire([]) is False
        assert _wait(lambda: len(got) == 2 and got[1] == [])
    finally:
        first.close()
    assert not os.path.exists(os.path.join(data, "instance.json"))


def test_messages_recus_avant_le_branchement(data):
    first = si.SingleInstance(data)
    try:
        assert first.acquire([])
        assert si.SingleInstance(data).acquire(["a"]) is False
        assert _wait(lambda: first._backlog == [["a"]])
        got = []
        first.set_handler(got.append)
        assert got == [["a"]]
    finally:
        first.close()


def test_fichier_perime_port_ferme(data):
    first = si.SingleInstance(data)
    assert first.acquire([])
    port = first.port
    first._closed.set()
    first._listener.close()                 # plantage : instance.json reste en place
    assert os.path.exists(os.path.join(data, "instance.json"))
    second = si.SingleInstance(data, on_message=lambda a: None)
    try:
        t = time.monotonic()
        assert second.acquire(["x"]) is True
        assert time.monotonic() - t < 2.5
        assert second.port and json.load(open(os.path.join(data, "instance.json")))["port"] == second.port
    finally:
        second.close()
    assert port


def test_fichier_perime_processus_mort(data, monkeypatch):
    got = []
    first = si.SingleInstance(data, on_message=got.append)
    try:
        assert first.acquire([])
        monkeypatch.setattr(si, "pid_alive", lambda pid: False)
        second = si.SingleInstance(data)
        assert second.acquire(["y"]) is True, "pid mort : on devient l'instance principale"
        second.close()
        assert got == []
    finally:
        first.close()


def test_secret_different_ne_transmet_rien(data, tmp_path):
    got = []
    first = si.SingleInstance(data, on_message=got.append)
    try:
        assert first.acquire([])
        # autre dossier de donnees mais meme fichier instance.json : le secret ne correspond pas
        other = tmp_path / "autre"
        other.mkdir()
        with open(os.path.join(data, "instance.json"), encoding="utf-8") as f:
            info = f.read()
        (other / "instance.json").write_text(info, encoding="utf-8")
        intruder = si.SingleInstance(str(other))
        assert intruder.acquire(["z"]) is True
        intruder.close()
        # et meme en forcant le bon hash, le defi HMAC echoue sans le secret
        intruder2 = si.SingleInstance(str(other))
        intruder2._secret = b"x" * 32
        forged = json.loads(info)
        forged["secret_hash"] = si._hash(intruder2._secret)
        assert intruder2._forward(forged, ["z"]) is False
        time.sleep(0.2)
        assert got == []
    finally:
        first.close()


def test_client_muet_ne_bloque_pas_le_serveur(data, monkeypatch):
    monkeypatch.setattr(si, "EXCHANGE_TIMEOUT", 0.5)
    got = []
    first = si.SingleInstance(data, on_message=got.append)
    try:
        assert first.acquire([])
        mute = socket.create_connection(("127.0.0.1", first.port))       # ne repond jamais au defi
        junk = socket.create_connection(("127.0.0.1", first.port))
        junk.sendall(b"\x00\x00\x00\x05hello")
        assert si.SingleInstance(data).acquire(["ok"]) is False
        assert _wait(lambda: got == [["ok"]])
        mute.close()
        junk.close()
    finally:
        first.close()


def test_secret_cree_une_fois_et_relu(data):
    a = si.SingleInstance(data)
    s1 = a._load_secret()
    s2 = si.SingleInstance(data)._load_secret()
    assert s1 == s2 and len(s1) == 32
    with open(os.path.join(data, "instance.key"), "w") as f:
        f.write("pas de l'hexadecimal")
    s3 = si.SingleInstance(data)._load_secret()
    assert s3 != s1 and len(s3) == 32


def test_pid_alive():
    assert si.pid_alive(os.getpid())
    assert not si.pid_alive(0) and not si.pid_alive("abc") and not si.pid_alive(None)
    assert not si.pid_alive(2 ** 31 - 2)
