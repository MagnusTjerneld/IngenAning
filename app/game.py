"""Spelregler för Ingen aning. Ren logik utan nätverk, så att den går att testa."""
from __future__ import annotations

import json
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

COLORS = [
    "#FFF4DC", "#FFC94A", "#F5A3A3", "#9ADBC5", "#F4B183", "#A9C7F5",
    "#D9B8F0", "#B8E08A", "#F7A8D0", "#8FD3E8", "#E8D27A", "#C9B6A4",
]
CODE_ALPHABET = "ABCDEFGHJKLMNPRSTUVXYZ"
MIN_PLAYERS = 3
MAX_PLAYERS = 12
MAX_NAME = 16
MAX_GUESS = 40
MIX = "blandat"

CATEGORIES: list[dict] = json.loads(
    (Path(__file__).parent / "words.json").read_text(encoding="utf-8")
)
_CAT_BY_ID = {c["id"]: c for c in CATEGORIES}

_SUFFIXES = ("", "n", "en", "et", "t", "an", "na", "ar", "er", "or", "arna", "erna", "orna", "s")


class GameError(Exception):
    """Fel som ska visas för spelaren."""


def normalize(text: str) -> str:
    text = re.sub(r"[^a-zåäöéà ]", "", text.lower().strip())
    return re.sub(r"\s+", " ", text).strip()


def is_exact(guess: str, word: str) -> bool:
    """Exakt träff, förlåtande för versaler, mellanslag och bestämd form."""
    g, w = normalize(guess), normalize(word)
    if not g:
        return False
    if g.replace(" ", "") == w.replace(" ", ""):
        return True
    return any(g == w + s for s in _SUFFIXES)


def laps_for(player_count: int) -> int:
    return 2 if player_count <= 5 else 1


@dataclass
class Player:
    id: str
    name: str
    color: str
    score: int = 0
    connected: bool = True


@dataclass
class Round:
    n: int
    participants: list[str]
    spy: str
    word: str
    category: str
    starter: str
    laps: int
    seen: set[str] = field(default_factory=set)
    votes: dict[str, str] = field(default_factory=dict)
    guess: str | None = None
    jury: dict[str, bool] = field(default_factory=dict)
    result: dict | None = None

    @property
    def knowers(self) -> list[str]:
        return [p for p in self.participants if p != self.spy]


class Room:
    def __init__(self, code: str, rng: random.Random | None = None):
        self.code = code
        self.rng = rng or random.Random()
        self.players: dict[str, Player] = {}
        self.host_id: str | None = None
        self.phase = "lobby"
        self.category_id = MIX
        self.used_words: set[str] = set()
        self.round: Round | None = None
        self.round_count = 0
        self.last_active = time.time()

    # ---------- spelare ----------

    def add_player(self, name: str) -> Player:
        name = re.sub(r"\s+", " ", name).strip()[:MAX_NAME]
        if not name:
            raise GameError("Skriv ett namn.")
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("Rummet är fullt.")
        taken = {p.color for p in self.players.values()}
        color = next((c for c in COLORS if c not in taken), COLORS[len(self.players) % len(COLORS)])
        player = Player(id=secrets.token_urlsafe(9), name=name, color=color)
        self.players[player.id] = player
        if self.host_id is None:
            self.host_id = player.id
        return player

    def find_by_name(self, name: str) -> Player | None:
        key = re.sub(r"\s+", " ", name).strip()[:MAX_NAME].casefold()
        return next((p for p in self.players.values() if p.name.casefold() == key), None) if key else None

    def set_connected(self, pid: str, connected: bool) -> None:
        player = self.players.get(pid)
        if not player:
            return
        player.connected = connected
        if not connected:
            self._advance_if_ready()

    def kick(self, by: str, pid: str) -> None:
        self._require_host(by)
        if pid == by or pid not in self.players:
            raise GameError("Den spelaren går inte att ta bort.")
        if self.round and pid in self.round.participants and self.phase != "reveal":
            raise GameError("Vänta till rundan är slut.")
        del self.players[pid]

    def claim_host(self, pid: str) -> None:
        if pid not in self.players:
            raise GameError("Du är inte med i rummet.")
        host = self.players.get(self.host_id or "")
        if host and host.connected:
            raise GameError(f"{host.name} är fortfarande värd.")
        self.host_id = pid

    def set_category(self, by: str, category_id: str) -> None:
        self._require_host(by)
        if category_id != MIX and category_id not in _CAT_BY_ID:
            raise GameError("Okänd kategori.")
        self.category_id = category_id

    # ---------- rundan ----------

    def start_round(self, by: str) -> None:
        self._require_host(by)
        if self.phase not in ("lobby", "reveal"):
            raise GameError("En runda pågår redan.")
        participants = [p.id for p in self.players.values() if p.connected]
        if len(participants) < MIN_PLAYERS:
            raise GameError(f"Ni behöver vara minst {MIN_PLAYERS}.")
        category, word = self._pick_word()
        self.round_count += 1
        self.round = Round(
            n=self.round_count,
            participants=participants,
            spy=self.rng.choice(participants),
            word=word,
            category=category,
            starter=self.rng.choice(participants),
            laps=laps_for(len(participants)),
        )
        self.phase = "clues"

    def mark_seen(self, pid: str) -> None:
        if self.round and pid in self.round.participants:
            self.round.seen.add(pid)

    def open_vote(self, by: str) -> None:
        self._require_host(by)
        if self.phase != "clues":
            raise GameError("Det går inte att rösta nu.")
        self.phase = "vote"

    def vote(self, pid: str, target: str) -> None:
        r = self._round_in("vote")
        if pid not in r.knowers:
            raise GameError("Du kan inte rösta den här rundan.")
        if target == pid or target not in r.participants:
            raise GameError("Välj en annan spelare.")
        if pid in r.votes:
            raise GameError("Din röst är redan låst.")
        r.votes[pid] = target
        self._advance_if_ready()

    def guess(self, pid: str, text: str) -> None:
        r = self._round_in("vote")
        if pid != r.spy:
            raise GameError("Du kan inte gissa den här rundan.")
        if r.guess is not None:
            raise GameError("Din gissning är redan låst.")
        r.guess = re.sub(r"\s+", " ", text).strip()[:MAX_GUESS]
        self._advance_if_ready()

    def force_close(self, by: str) -> None:
        """Värden går vidare utan att vänta på de som dröjer."""
        self._require_host(by)
        if self.phase == "vote":
            self._close_vote()
        elif self.phase == "jury":
            self._finalize()
        else:
            raise GameError("Det finns inget att avsluta.")

    def jury_vote(self, pid: str, ok: bool) -> None:
        r = self._round_in("jury")
        if pid not in r.knowers:
            raise GameError("Du sitter inte i juryn.")
        if pid in r.jury:
            raise GameError("Du har redan röstat.")
        r.jury[pid] = bool(ok)
        self._advance_if_ready()

    def to_lobby(self, by: str) -> None:
        self._require_host(by)
        if self.phase != "reveal":
            raise GameError("Vänta till rundan är slut.")
        self.phase = "lobby"
        self.round = None

    # ---------- internt ----------

    def _require_host(self, pid: str) -> None:
        if pid != self.host_id:
            raise GameError("Bara värden kan göra det.")

    def _round_in(self, phase: str) -> Round:
        if self.phase != phase or not self.round:
            raise GameError("Det går inte just nu.")
        return self.round

    def _pick_word(self) -> tuple[str, str]:
        cats = CATEGORIES if self.category_id == MIX else [_CAT_BY_ID[self.category_id]]
        pool = [(c["name"], w) for c in cats for w in c["words"] if w not in self.used_words]
        if not pool:
            for c in cats:
                self.used_words.difference_update(c["words"])
            pool = [(c["name"], w) for c in cats for w in c["words"]]
        category, word = self.rng.choice(pool)
        self.used_words.add(word)
        return category, word

    def _is_locked(self, pid: str) -> bool:
        r = self.round
        assert r
        return r.guess is not None if pid == r.spy else pid in r.votes

    def _advance_if_ready(self) -> None:
        r = self.round
        if not r:
            return
        active = [p for p in r.participants if p in self.players and self.players[p].connected]
        if self.phase == "vote":
            if active and all(self._is_locked(p) for p in active):
                self._close_vote()
        elif self.phase == "jury":
            jurors = [p for p in active if p != r.spy]
            if all(p in r.jury for p in jurors):
                self._finalize()

    def _close_vote(self) -> None:
        r = self.round
        assert r
        if r.guess is None:
            r.guess = ""
        if not r.guess or is_exact(r.guess, r.word):
            self._finalize()
            return
        self.phase = "jury"
        self._advance_if_ready()

    def _finalize(self) -> None:
        r = self.round
        assert r
        guess = r.guess or ""
        yes = sum(1 for v in r.jury.values() if v)
        no = len(r.jury) - yes
        if not guess:
            outcome = "none"
        elif is_exact(guess, r.word):
            outcome = "exact"
        elif yes >= no:  # lika går till den som gissade
            outcome = "approved"
        else:
            outcome = "rejected"
        knowers = r.knowers
        pointed = sum(1 for t in r.votes.values() if t == r.spy)
        hid = pointed * 2 < len(knowers)
        gains: dict[str, int] = {}
        for pid, target in r.votes.items():
            if target == r.spy:
                gains[pid] = 1
        spy_gain = (2 if outcome in ("exact", "approved") else 0) + (1 if hid else 0)
        if spy_gain:
            gains[r.spy] = spy_gain
        for pid, g in gains.items():
            if pid in self.players:
                self.players[pid].score += g
        tally: dict[str, int] = {}
        for target in r.votes.values():
            tally[target] = tally.get(target, 0) + 1
        r.result = {
            "spyId": r.spy,
            "word": r.word,
            "guess": guess,
            "outcome": outcome,
            "juryYes": yes,
            "juryNo": no,
            "tally": sorted(
                ({"id": k, "count": v} for k, v in tally.items()),
                key=lambda t: -t["count"],
            ),
            "pointed": pointed,
            "knowers": len(knowers),
            "hid": hid,
            "gains": gains,
        }
        self.phase = "reveal"

    # ---------- vyer ----------

    def _common(self) -> dict:
        r = self.round
        in_round = set(r.participants) if r else set()
        view: dict = {
            "code": self.code,
            "phase": self.phase,
            "hostId": self.host_id,
            "categoryId": self.category_id,
            "minPlayers": MIN_PLAYERS,
            "players": [
                {
                    "id": p.id, "name": p.name, "color": p.color, "score": p.score,
                    "connected": p.connected, "inRound": p.id in in_round,
                }
                for p in self.players.values()
            ],
        }
        if r:
            view["round"] = {
                "n": r.n,
                "category": r.category,
                "starter": r.starter,
                "laps": r.laps,
                "seen": len(r.seen),
                "size": len(r.participants),
                "locked": [p for p in r.participants if self._is_locked(p)]
                if self.phase == "vote" else [],
                "juryVoted": len(r.jury),
                "jurySize": len(r.knowers),
            }
            if self.phase == "reveal":
                view["result"] = r.result
        return view

    def view_for(self, pid: str) -> dict:
        """Vad en viss spelare får veta. Ordet skickas aldrig till den ovetande."""
        view = self._common()
        r = self.round
        you: dict = {"id": pid, "isHost": pid == self.host_id, "inRound": False}
        if r and pid in r.participants:
            is_spy = pid == r.spy
            you.update(
                inRound=True,
                role="spy" if is_spy else "knower",
                locked=self._is_locked(pid),
                juryVoted=pid in r.jury,
            )
            if not is_spy:
                you["word"] = r.word
            if self.phase == "jury":
                view["jury"] = {"guess": r.guess} if is_spy else {"guess": r.guess, "word": r.word}
        view["you"] = you
        view["categories"] = [{"id": c["id"], "name": c["name"]} for c in CATEGORIES]
        return view

    def view_tv(self) -> dict:
        """Vad TV:n visar. Inget hemligt före juryn och avslöjandet."""
        view = self._common()
        r = self.round
        if r and self.phase == "jury":
            view["jury"] = {"guess": r.guess, "word": r.word}
        view["tv"] = True
        return view


def new_code(existing: set[str] | dict, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    while True:
        code = "".join(rng.choice(CODE_ALPHABET) for _ in range(4))
        if code not in existing:
            return code
