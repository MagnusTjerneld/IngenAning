import random

import pytest
from fastapi.testclient import TestClient

from app.game import CATEGORIES, GameError, Room, laps_for
from app.main import app


def make_room(n=4, seed=1):
    room = Room("TEST", random.Random(seed))
    players = [room.add_player(f"P{i}") for i in range(n)]
    return room, [p.id for p in players]


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


def test_spy_and_tv_never_get_word_before_reveal():
    room, ids = make_room(5)
    room.start_round(ids[0])
    r = room.round

    def check():
        spy_view = room.view_for(r.spy)
        assert r.word not in str(spy_view)
        assert spy_view["you"]["role"] == "spy"
        assert r.word not in str(room.view_tv())
        for k in r.knowers:
            assert room.view_for(k)["you"]["word"] == r.word

    check()
    assert "spyId" not in room.view_tv()
    room.open_vote(ids[0])
    check()
    assert "spyId" not in room.view_for(r.knowers[0])
    for p in r.participants:
        room.vote(p, next(x for x in r.participants if x != p))
    assert room.phase == "guess"
    check()  # den ovetande är utpekad men ordet är fortfarande hemligt för hen och TV:n
    assert room.view_tv()["spyId"] == r.spy


def play(room, spy_votes=None, jury=()):
    """Spelar en runda. spy_votes = hur många som pekar ut den ovetande (None = alla)."""
    room.start_round(room.host_id)
    r = room.round
    room.open_vote(room.host_id)
    for i, k in enumerate(r.knowers):
        target = r.spy if spy_votes is None or i < spy_votes else next(x for x in r.knowers if x != k)
        room.vote(k, target)
    assert room.phase == "vote"  # väntar på den ovetandes bluffröst
    room.vote(r.spy, r.knowers[0])
    assert room.phase == "guess"
    for k, ok in zip(r.knowers, jury):
        if room.phase == "guess":
            room.jury_vote(k, ok)
    assert room.phase == "reveal"
    return r


def test_majority_yes_scores_and_bluff_vote_is_ignored():
    room, ids = make_room(5)
    r = play(room, jury=[False, True, True, False])
    res = r.result
    assert res["outcome"] == "approved" and (res["juryYes"], res["juryNo"]) == (2, 1)  # klart vid hälften ja
    assert res["pointed"] == 4 and res["hid"] is False
    assert sum(t["count"] for t in res["tally"]) == 4  # bluffrösten räknas inte
    assert room.players[r.spy].score == 2
    assert all(room.players[k].score == 1 for k in r.knowers)


def test_jury_tie_goes_to_guesser():
    room, ids = make_room(5)
    r = play(room, jury=[False, True, False, True])
    assert r.result["outcome"] == "approved" and (r.result["juryYes"], r.result["juryNo"]) == (2, 2)
    assert room.players[r.spy].score == 2


def test_jury_rejects_and_hidden_bonus():
    room, ids = make_room(5)
    r = play(room, spy_votes=1, jury=[False, True, False, False])
    assert r.result["outcome"] == "rejected" and (r.result["juryYes"], r.result["juryNo"]) == (1, 3)
    assert r.result["hid"] is True  # 1 av 4 pekade ut hen
    assert room.players[r.spy].score == 1
    assert sum(room.players[k].score for k in r.knowers) == 1


def test_half_pointing_is_not_hidden():
    room, ids = make_room(5)
    r = play(room, spy_votes=2, jury=[False, False, False])
    assert r.result["outcome"] == "rejected" and r.result["hid"] is False
    assert room.players[r.spy].score == 0


def test_spy_bluff_needs_no_target():
    room, ids = make_room(4)
    room.start_round(ids[0])
    r = room.round
    room.open_vote(ids[0])
    room.vote(r.spy, "")
    assert r.spy in room.view_tv()["round"]["locked"]
    with pytest.raises(GameError):
        room.vote(r.knowers[0], "")


def test_host_decides_after_twenty_seconds():
    room, ids = make_room(5)
    clock = [100.0]
    room.now = lambda: clock[0]
    room.start_round(ids[0])
    r = room.round
    room.open_vote(ids[0])
    for p in r.participants:
        room.vote(p, next(x for x in r.participants if x != p))
    assert room.phase == "guess"
    decider = room.decider()
    assert decider in r.knowers and (decider == ids[0] or r.spy == ids[0])
    assert room.view_tv()["round"]["juryLeft"] == 25000
    room.jury_vote(next(k for k in r.knowers if k != decider), False)
    with pytest.raises(GameError):
        room.decide(decider, True)  # för tidigt
    clock[0] += 26
    assert room.view_tv()["round"]["juryLeft"] == 0
    with pytest.raises(GameError):
        room.decide(r.spy, True)  # den ovetande avgör aldrig själv
    room.decide(decider, True)
    assert room.phase == "reveal"
    assert r.result["outcome"] == "approved" and r.result["decidedBy"] == decider
    assert room.players[r.spy].score >= 2


def test_only_jurors_decide():
    room, ids = make_room(4)
    room.start_round(ids[0])
    r = room.round
    room.open_vote(ids[0])
    with pytest.raises(GameError):
        room.jury_vote(r.knowers[0], True)  # för tidigt
    for p in r.participants:
        room.vote(p, next(x for x in r.participants if x != p))
    with pytest.raises(GameError):
        room.jury_vote(r.spy, True)  # den ovetande dömer inte sig själv
    room.jury_vote(r.knowers[0], False)
    with pytest.raises(GameError):
        room.jury_vote(r.knowers[0], True)


def test_disconnect_does_not_block_and_force_works():
    room, ids = make_room(4)
    room.start_round(ids[0])
    r = room.round
    room.open_vote(ids[0])
    slow = next(p for p in r.participants if p != ids[0])
    for p in r.participants:
        if p != slow:
            room.vote(p, next(x for x in r.participants if x != p))
    assert room.phase == "vote"
    room.set_connected(slow, False)
    assert room.phase == "guess"
    for k in r.knowers:
        if k != slow and room.phase == "guess":
            room.jury_vote(k, False)
    assert room.phase == "reveal"  # den frånkopplade jurymedlemmen blockerar inte

    room.set_connected(slow, True)
    room.start_round(ids[0])
    room.open_vote(ids[0])
    room.force_close(ids[0])
    assert room.phase == "guess"
    with pytest.raises(GameError):
        room.force_close(ids[0])  # juryn avgörs av röster eller av den som dömer, inte genom att hoppa över


def test_words_do_not_repeat_until_exhausted():
    room, ids = make_room(3)
    room.set_category(ids[0], "bondgard")
    seen = []
    for _ in range(16):
        room.start_round(ids[0])
        seen.append(room.round.word)
        room.open_vote(ids[0])
        room.force_close(ids[0])
        room.jury_vote(room.round.knowers[0], True)
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
                s.send_json({"t": "vote", "target": spy if pid != spy else host_id if spy != host_id else next(p for p in socks if p != spy)})
            for pid, s in socks.items():
                st = drain(s, "guess")
                assert st["spyId"] == spy
                if pid != spy:
                    s.send_json({"t": "jury", "ok": False})
                else:
                    assert word not in str(st)
            assert word not in str(drain(tv, "guess"))
            final = drain(host, "reveal")
            assert final["result"]["outcome"] == "rejected"
            assert final["result"]["spyId"] == spy
            scores = {p["id"]: p["score"] for p in final["players"]}
            assert scores[spy] == 0 and sum(scores.values()) == 2
            assert drain(tv, "reveal")["result"]["word"] == word


def test_rejoin_by_name_takes_the_same_seat_mid_round():
    client = TestClient(app)
    with client.websocket_connect("/ws") as host:
        host.send_json({"t": "create", "name": "Värd"})
        code = host.receive_json()["code"]
        with client.websocket_connect("/ws") as a:
            a.send_json({"t": "join", "code": code, "name": "Elsa"})
            a.receive_json()
            with client.websocket_connect("/ws") as b:
                b.send_json({"t": "join", "code": code, "name": "Nils"})
                nils = b.receive_json()["pid"]
                # samma namn medan Nils är ansluten: avvisas
                with client.websocket_connect("/ws") as dup:
                    dup.send_json({"t": "join", "code": code, "name": " nils "})
                    err = dup.receive_json()
                    assert err["t"] == "error" and err["fatal"]
                host.send_json({"t": "start"})
            # Nils tappar anslutningen mitt i rundan och kommer tillbaka från en annan webbläsare, utan sitt id
            with client.websocket_connect("/ws") as b2:
                b2.send_json({"t": "join", "code": code, "name": "nils"})
                again = b2.receive_json()
                assert again["t"] == "joined" and again["pid"] == nils
                state = b2.receive_json()["state"]
                assert state["phase"] == "clues" and state["you"]["inRound"] is True
                assert len(state["players"]) == 3


def test_ping_gets_pong():
    client = TestClient(app)
    with client.websocket_connect("/ws") as s:
        s.send_json({"t": "ping"})
        assert s.receive_json() == {"t": "pong"}
