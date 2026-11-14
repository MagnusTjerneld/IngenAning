import random

import pytest
from fastapi.testclient import TestClient

from app.game import CATEGORIES, GameError, Room, is_exact, laps_for
from app.main import app


def make_room(n=4, seed=1):
    room = Room("TEST", random.Random(seed))
    players = [room.add_player(f"P{i}") for i in range(n)]
    return room, [p.id for p in players]


def test_exact_match_is_forgiving():
    assert is_exact("Lussekatt", "lussekatt")
    assert is_exact("  lussekatten ", "lussekatt")
    assert is_exact("granen", "gran")
    assert is_exact("janssons  frestelse", "Janssons frestelse")
    assert not is_exact("saffransbulle", "lussekatt")
    assert not is_exact("skinka", "julskinka")
    assert not is_exact("", "ko")


def test_laps():
    assert [laps_for(n) for n in (3, 5, 6, 9)] == [2, 2, 1, 1]


def test_words_unique_per_category():
    for c in CATEGORIES:
        assert len(c["words"]) == len(set(c["words"])) >= 15, c["id"]


def test_needs_three_players_and_host():
    room, ids = make_room(2)
    with pytest.raises(GameError):
        room.start_round(ids[0])
    room, ids = make_room(3)
    with pytest.raises(GameError):
        room.start_round(ids[1])
    room.start_round(ids[0])
    assert room.phase == "clues"


def test_spy_never_gets_word_before_reveal():
    room, ids = make_room(5)
    room.start_round(ids[0])
    r = room.round
    for phase_step in (None, "vote"):
        if phase_step:
            room.open_vote(ids[0])
        spy_view = room.view_for(r.spy)
        assert r.word not in str(spy_view)
        assert spy_view["you"]["role"] == "spy"
        assert r.word not in str(room.view_tv())
        for k in r.knowers:
            assert room.view_for(k)["you"]["word"] == r.word


def play(room, ids, guess, spy_votes=None, jury=None):
    room.start_round(room.host_id)
    r = room.round
    room.open_vote(room.host_id)
    for i, k in enumerate(r.knowers):
        target = r.spy if spy_votes is None or i < spy_votes else next(x for x in r.knowers if x != k)
        room.vote(k, target)
    room.guess(r.spy, guess)
    if room.phase == "jury":
        assert r.word not in str(room.view_for(r.spy))
        for k, ok in zip(r.knowers, jury):
            room.jury_vote(k, ok)
    assert room.phase == "reveal"
    return r


def test_exact_guess_skips_jury_and_scores():
    room, ids = make_room(5)
    room.start_round(ids[0])
    word = room.round.word
    room.phase, room.round = "lobby", None
    room.used_words.clear()
    room.rng = random.Random(1)
    room.round_count = 0
    r = play(room, ids, word.upper())
    assert r.word == word
    res = r.result
    assert res["outcome"] == "exact" and res["juryYes"] == res["juryNo"] == 0
    assert room.players[r.spy].score == 2  # rätt ord, men alla pekade ut hen
    assert all(room.players[k].score == 1 for k in r.knowers)


def test_jury_tie_goes_to_guesser():
    room, ids = make_room(5)
    r = play(room, ids, "nästan rätt", jury=[True, True, False, False])
    assert r.result["outcome"] == "approved"
    assert room.players[r.spy].score == 2


def test_jury_rejects_and_hidden_bonus():
    room, ids = make_room(5)
    r = play(room, ids, "helt fel", spy_votes=1, jury=[False, False, False, True])
    assert r.result["outcome"] == "rejected"
    assert r.result["hid"] is True  # 1 av 4 pekade ut hen
    assert room.players[r.spy].score == 1
    assert sum(room.players[k].score for k in r.knowers) == 1


def test_half_pointing_is_not_hidden():
    room, ids = make_room(5)
    r = play(room, ids, "", spy_votes=2)
    assert r.result["outcome"] == "none"
    assert r.result["hid"] is False
    assert room.players[r.spy].score == 0


def test_disconnect_does_not_block_and_force_works():
    room, ids = make_room(4)
    room.start_round(ids[0])
    r = room.round
    room.open_vote(ids[0])
    slow = next(k for k in r.knowers if k != ids[0])
    for k in r.knowers:
        if k != slow:
            room.vote(k, r.spy)
    room.guess(r.spy, "")
    assert room.phase == "vote"
    room.set_connected(slow, False)
    assert room.phase == "reveal"

    room.start_round(ids[0])
    room.open_vote(ids[0])
    room.force_close(ids[0])
    assert room.phase == "reveal"


def test_words_do_not_repeat_until_exhausted():
    room, ids = make_room(3)
    room.set_category(ids[0], "bondgard")
    seen = []
    for _ in range(16):
        room.start_round(ids[0])
        seen.append(room.round.word)
        room.open_vote(ids[0])
        room.force_close(ids[0])
    assert len(set(seen)) == 16


def test_full_round_over_websocket():
    client = TestClient(app)
    with client.websocket_connect("/ws") as host:
        host.send_json({"t": "create", "name": "Värd"})
        joined = host.receive_json()
        code, host_id = joined["code"], joined["pid"]
        host.receive_json()
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b, \
                client.websocket_connect("/ws") as tv:
            socks = {host_id: host}
            for s, name in ((a, "Elsa"), (b, "Nils")):
                s.send_json({"t": "join", "code": code.lower(), "name": name})
                socks[s.receive_json()["pid"]] = s
            tv.send_json({"t": "tv", "code": code})
            assert tv.receive_json()["pid"] is None

            def drain(sock, phase):
                while True:
                    m = sock.receive_json()
                    if m["t"] == "state" and m["state"]["phase"] == phase:
                        return m["state"]

            a.send_json({"t": "start"})  # inte värd
            while True:
                m = a.receive_json()
                if m["t"] == "error":
                    break
            host.send_json({"t": "start"})
            views = {pid: drain(s, "clues") for pid, s in socks.items()}
            tv_view = drain(tv, "clues")
            spies = [pid for pid, v in views.items() if v["you"]["role"] == "spy"]
            assert len(spies) == 1
            spy = spies[0]
            word = next(v["you"]["word"] for pid, v in views.items() if pid != spy)
            assert "word" not in views[spy]["you"] and word not in str(tv_view)

            host.send_json({"t": "openVote"})
            for pid, s in socks.items():
                drain(s, "vote")
                if pid == spy:
                    s.send_json({"t": "guess", "text": "något annat"})
                else:
                    s.send_json({"t": "vote", "target": spy})
            for pid, s in socks.items():
                st = drain(s, "jury")
                if pid != spy:
                    assert st["jury"]["word"] == word
                    s.send_json({"t": "jury", "ok": False})
                else:
                    assert "word" not in st["jury"]
            final = drain(host, "reveal")
            assert final["result"]["outcome"] == "rejected"
            assert final["result"]["spyId"] == spy
            scores = {p["id"]: p["score"] for p in final["players"]}
            assert scores[spy] == 0 and sum(scores.values()) == 2
            assert drain(tv, "reveal")["result"]["word"] == word
