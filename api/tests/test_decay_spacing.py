"""G147 — spacing-aware decay: how often a page came up sets how fast its
silence counts. Frequency is DISTINCT ISO WEEKS, never mentions (plan R-FD2):
fifty mentions in one afternoon are one burst, twelve weeks are twelve reviews.

Hermetic like `test_decay_engines.py`: `resolve_and_prune` runs with an EMPTY
`resolved` list, so the synthesis/contradiction LLM path is never entered.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from api.config import Settings
from api.models.schemas import DecayClass, InboxResolveRequest
from api.services import conflict_resolver, decay_policy, inbox_service, markdown_parser


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    memory_path = None
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def _weekly(start: str, n: int) -> list[str]:
    """``n`` episode ids exactly 7 days apart — always ``n`` distinct ISO weeks."""
    d0 = date.fromisoformat(start)
    return [f"ep_{(d0 + timedelta(days=7 * i)).isoformat()}_001" for i in range(n)]


# --- mention_weeks (R-FD2) --------------------------------------------------


def test_fifty_mentions_in_one_afternoon_are_one_week():
    assert decay_policy.mention_weeks([f"ep_2026-06-01_{i:03d}" for i in range(1, 51)]) == 1


def test_twelve_weekly_mentions_are_twelve_weeks():
    assert decay_policy.mention_weeks(_weekly("2026-03-02", 12)) == 12


def test_weeks_are_iso_weeks_across_a_year_boundary():
    # 2025-12-29 (Mon) and 2026-01-04 (Sun) are both 2026-W01; 2026-01-05 opens W02.
    assert decay_policy.mention_weeks(["ep_2025-12-29_001", "ep_2026-01-04_003"]) == 1
    assert decay_policy.mention_weeks(["ep_2025-12-29_001", "ep_2026-01-05_001"]) == 2


def test_unparseable_ids_count_once_as_unknown():
    assert decay_policy.mention_weeks(
        ["ep_2026-06-01_001", "legacy-a", "ep_2026-13-40_001", ""]
    ) == 2
    assert decay_policy.mention_weeks(["legacy-a", "legacy-b"]) == 1
    assert decay_policy.mention_weeks([]) == 0
    assert decay_policy.mention_weeks(None) == 0


def test_a_bare_string_is_one_id_never_its_characters():
    assert decay_policy.mention_weeks("ep_2026-06-01_001") == 1


def test_kept_dates_join_the_week_set():
    eps = ["ep_2026-06-01_001"]
    assert decay_policy.mention_weeks(eps, ["2026-06-03"]) == 1  # same ISO week
    assert decay_policy.mention_weeks(eps, ["2026-07-20"]) == 2
    assert decay_policy.mention_weeks(eps, [date(2026, 7, 20), "not a date"]) == 2


# --- stability (R-FD1) --------------------------------------------------------


@pytest.mark.parametrize(
    "weeks,expected",
    [(0, 1.0), (1, 1.0), (2, 0.706), (4, 0.546), (12, 0.401), (52, 0.297), (148, 0.25), (1000, 0.25)],
)
def test_stability_curve_is_the_ruled_one(weeks, expected):
    assert round(decay_policy.stability(weeks), 3) == expected


def test_spacing_params_default_and_refuse_junk():
    assert decay_policy.spacing_params(_FakeSettings()) == (0.6, 0.25)

    class Junk:
        decay_spacing_alpha = "steep"
        decay_spacing_floor = True

    assert decay_policy.spacing_params(Junk()) == (0.6, 0.25)

    class Wild:
        decay_spacing_alpha = 99.0
        decay_spacing_floor = 0.0

    assert decay_policy.spacing_params(Wild()) == (5.0, 0.05)


def test_config_defaults_match_the_policy_constants():
    fields = Settings.model_fields
    assert fields["decay_spacing_alpha"].default == decay_policy.SPACING_ALPHA
    assert fields["decay_spacing_floor"].default == decay_policy.SPACING_FLOOR


# --- effective (R-FD11) -------------------------------------------------------


def test_effective_rate_is_base_times_stability_times_type_pace():
    fm = {"type": "person", "decay_class": "active", "source_episodes": _weekly("2026-03-02", 12)}
    eff = decay_policy.effective(fm, tuning={"person": 0.5})
    assert eff.decay_class is DecayClass.active
    assert eff.base_rate == 0.05
    assert eff.mention_weeks == 12
    assert eff.type_multiplier == 0.5
    assert eff.rate == pytest.approx(0.05 * decay_policy.stability(12) * 0.5)


def test_an_explicit_rate_is_still_the_base():
    eff = decay_policy.effective(
        {"decay_class": "active", "decay_rate": 0.1, "source_episodes": _weekly("2026-03-02", 4)}
    )
    assert eff.rate == pytest.approx(0.1 * decay_policy.stability(4))


def test_evergreen_stays_zero_whatever_the_weeks_or_pace():
    eff = decay_policy.effective(
        {"type": "media", "source_episodes": _weekly("2026-03-02", 30)}, tuning={"media": 3.0}
    )
    assert eff.decay_class is DecayClass.evergreen
    assert eff.rate == 0.0


def test_a_page_with_no_episodes_decays_exactly_as_before():
    assert decay_policy.effective({"decay_class": "active"}).rate == 0.05
    assert decay_policy.effective({"type": "skill"}).rate == 0.02


def test_kept_on_counts_in_effective():
    fm = {"decay_class": "active", "source_episodes": ["ep_2026-06-01_001"], "kept_on": ["2026-08-10"]}
    assert decay_policy.effective(fm).mention_weeks == 2


# --- the pass over simulated cycles (the brief's verification) -----------------


def _page(root: Path, eid: str, episodes: list[str], start: str) -> None:
    markdown_parser.write(
        root / "entities" / f"{eid}.md",
        {
            "name": eid, "type": "concept", "status": "active", "confidence": 0.62,
            "created": start, "last_referenced": start,
            "decay_class": "active", "decay_rate": 0.05,
            "source_episodes": episodes, "tags": [], "related": [], "version": 1,
        },
        "## Summary\n\nA synthetic page.\n",
    )


def _existing(root: Path) -> list[dict]:
    out = []
    for path in sorted((root / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        out.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return out


def test_a_twelve_week_page_outlasts_a_one_week_page_over_simulated_cycles(tmp_path):
    (tmp_path / "entities").mkdir()
    start = date(2026, 6, 7)
    _page(tmp_path, "spaced", _weekly("2026-03-15", 12), start.isoformat())
    _page(tmp_path, "burst", ["ep_2026-06-01_001", "ep_2026-06-02_004", "ep_2026-06-03_002"],
          start.isoformat())
    first: dict[tuple[str, str], int] = {}
    for cycle in range(1, 23):
        now = datetime.combine(start + timedelta(days=7 * cycle), datetime.min.time())
        changes = run(conflict_resolver.resolve_and_prune([], _existing(tmp_path), _FakeSettings(), now=now))
        conflict_resolver.apply_changes(changes, tmp_path)
        for change in changes:
            first.setdefault((change["id"], change["action"]), cycle)
    # Same class, same start (0.62), same silence — only the spacing differs.
    # burst:  0.05/wk            -> asked at cycle 5,  archived at 9.
    # spaced: 0.05 x f(12)/wk    -> asked at cycle 11, archived at 21 (0.0200727/wk).
    assert first[("burst", "decay_nudge")] == 5
    assert first[("burst", "archive")] == 9
    assert first[("spaced", "decay_nudge")] == 11
    assert first[("spaced", "archive")] == 21


def test_an_injected_pace_multiplies_the_pass():
    existing = [{
        "id": "bob-example",
        "frontmatter": {"type": "person", "status": "active", "confidence": 0.7,
                        "decay_class": "active",
                        "last_referenced": str(date.today() - timedelta(days=35))},
        "body": "x",
    }]
    changes = run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings(), tuning={"person": 0.5}))
    assert changes[0]["new_confidence"] == pytest.approx(0.7 - 0.025)


# --- "keep" is a week (R-FD3) --------------------------------------------------


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(memory), *args], check=True, capture_output=True, text=True
    ).stdout


class _InboxSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    (m / "entities" / "alpha-project.md").write_text(
        "---\ntype: project\nstatus: decaying\nconfidence: 0.35\ncreated: 2026-01-01\n"
        "last_referenced: 2026-01-01\ndecay_rate: 0.05\nsource_episodes: []\ntags: []\n"
        "related: []\nversion: 1\n---\n# Alpha Project\n"
    )
    (m / "inbox" / "inbox-001.md").write_text(
        "---\nkind: decay\nrequired_input: choice\nstatus: pending\npriority: 0.3\n"
        "entity_id: alpha-project\nentity_name: Alpha Project\n"
        "title: Still tracking Alpha Project?\ncreated_date: 2026-08-01\n---\n"
    )
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def _fm(bank: Path) -> dict:
    return markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter


def test_keep_records_today_as_a_kept_week(bank):
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), _InboxSettings(bank)))
    fm = _fm(bank)
    assert fm["kept_on"] == [date.today().isoformat()]
    assert fm["status"] == "active" and fm["confidence"] == 0.6  # unchanged behaviour
    assert decay_policy.effective(fm).mention_weeks == 1


def test_keep_appends_to_earlier_keeps_and_caps_the_list(bank):
    page = bank / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    seeds = [(date(2025, 1, 6) + timedelta(days=7 * i)).isoformat() for i in range(52)]
    parsed.frontmatter["kept_on"] = seeds
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="resolve", option_key="keep"),
                              _InboxSettings(bank)))
    kept = _fm(bank)["kept_on"]
    assert len(kept) == decay_policy.KEPT_ON_CAP == 52
    assert kept[-1] == date.today().isoformat()
    assert kept[0] == seeds[1]


def test_archive_writes_no_kept_week(bank):
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="archive"), _InboxSettings(bank)))
    assert "kept_on" not in _fm(bank)


def test_record_keep_is_idempotent_within_a_day():
    fm = {"kept_on": ["2026-09-01"]}
    assert decay_policy.record_keep(fm, "2026-09-01") == ["2026-09-01"]
    assert decay_policy.record_keep({"kept_on": "2026-09-01"}, "2026-09-24") == ["2026-09-01", "2026-09-24"]
