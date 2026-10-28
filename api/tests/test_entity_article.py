"""Entity pages as articles (G194, owner 2026-10-09): the shape, the stamp, the writer's validation and provenance."""
import json

from api.services import entity_article as article, entity_body as body, section_provenance as sp
from api.services.claims import Claim, Evidence, write_claims

LEAD = "alpha-project is a notes app bob-example builds; in March 2026 it moved to [[SQLite]]."
ARTICLE = ("### What it is\n\nalpha-project keeps notes on a laptop and syncs them with [[SQLite]] files.\n\n"
           "It began as a weekend experiment in January 2026.\n\n### Where it stands\n\nIn March 2026 the sync "
           "moved to [[SQLite]].")
PAGE = f"## Summary\n{LEAD}\n\n## Article\n{ARTICLE}\n\n## Key Facts\n- Uses SQLite for sync.\n"


def _stamped_page():
    fm = {"name": "alpha-project", "type": "project"}
    article.stamp(fm, body.parse_sections(PAGE), written="2026-03-20")
    return fm


def test_article_is_canonical_and_ordered_after_the_lead():
    assert body.CANONICAL_SECTIONS[:3] == ["Summary", "Article", "Key Facts"]
    rendered = body.render_sections({"Key Facts": "- a", "Article": "### T\n\nProse.", "Summary": "Lead."})
    assert rendered.index("## Summary") < rendered.index("## Article") < rendered.index("## Key Facts")
    # The `### ` titles stay inside the Article: the grammar splits on `## ` only.
    assert body.parse_sections(PAGE)["Article"] == ARTICLE


def test_a_stamped_article_is_machine_prose_and_an_edit_makes_the_page_the_persons():
    fm = _stamped_page()
    assert article.stamped(fm, body.parse_sections(PAGE))
    assert not body.has_human_prose(fm, body.parse_sections(PAGE))
    edited = PAGE.replace("weekend experiment", "summer experiment")
    assert body.has_human_prose(fm, body.parse_sections(edited))
    lead_edited = PAGE.replace("notes app", "journal app")
    assert body.has_human_prose(fm, body.parse_sections(lead_edited))
    # An Article nobody stamped was written by hand.
    assert body.has_human_prose({}, body.parse_sections(PAGE))
    # No Article: the stamp decides nothing.
    assert not body.has_human_prose({}, {"Summary": "Lead.", "Key Facts": "- a"})


def test_carry_stamp_follows_a_mechanical_relink_but_never_an_edit():
    fm = _stamped_page()
    relinked = PAGE.replace("[[SQLite]]", "[[SQLite 3]]")
    article.carry_stamp(fm, PAGE, relinked)
    assert article.stamped(fm, body.parse_sections(relinked))
    assert fm["article"]["written"] == "2026-03-20"
    edited_fm = _stamped_page()
    hand = PAGE.replace("weekend", "summer")
    article.carry_stamp(edited_fm, hand, hand.replace("[[SQLite]]", "[[SQLite 3]]"))
    assert not article.stamped(edited_fm, body.parse_sections(hand.replace("[[SQLite]]", "[[SQLite 3]]")))


def test_an_article_pages_long_lead_survives_the_deterministic_merges():
    long_lead = " ".join(["alpha-project is a notes application bob-example has built since January 2026."] * 12)
    sections = {"Summary": long_lead, "Article": "### T\n\nProse.", "Key Facts": "- Old fact."}
    assert len(long_lead) > 600
    assert body.bound_summary(sections, name="alpha-project")["Summary"] == long_lead
    merged = body.merge_sections_fallback(sections, {"summary": "A different orientation.", "key_facts": ["New."]})
    assert merged["Summary"] == long_lead
    assert "- A different orientation." in merged["Key Facts"] and "- New." in merged["Key Facts"]
    assert merged["Article"] == "### T\n\nProse."


def test_recall_reads_the_article_after_the_record():
    text = body.summarize_for_recall(PAGE)
    assert "## Article" in text and text.index("## Key Facts") < text.index("## Article")


def test_provenance_scans_each_article_paragraph_as_an_item_at_its_own_offsets():
    items = sp.scan(PAGE)["article"]
    assert [i.text for i in items] == [
        "alpha-project keeps notes on a laptop and syncs them with [[SQLite]] files.",
        "It began as a weekend experiment in January 2026.",
        "In March 2026 the sync moved to [[SQLite]]."]
    for item in items:
        (start, end), = item.ranges
        assert PAGE[start:end] == item.text


def _inputs(**over):
    record = {"Key Facts": "- Uses SQLite for sync.\n- Runs on a laptop.", "History": "- 2026-01-10: Started."}
    incoming = {"summary": "alpha-project is a notes app. It has 40 users.", "key_facts": ["Runs on a laptop."]}
    sp.attach(incoming, "ep_2026-03-02_001", "user: synthetic")
    kwargs = dict(name="alpha-project", entity_type="project", frontmatter={"created": "2026-01-10"},
                  original_body="## Summary\nOld lead about alpha-project notes.\n\n## Key Facts\n- Uses SQLite for sync.",
                  record=record, incoming=incoming, today="2026-03-20", update_days=["2026-03-02"],
                  owner="bob-example", linkable=["SQLite"])
    kwargs.update(over)
    return article.build(**kwargs)


def test_inputs_number_the_record_and_mark_only_orientation_for_retention():
    inputs = _inputs()
    kinds = {s.id: (s.kind, s.retain) for s in inputs.sources}
    assert kinds["p0"] == ("earlier", True)      # the old Summary on a page's first article
    assert kinds["s0"] == ("said", True) and kinds["s1"] == ("said", True)
    assert kinds["f0"] == ("fact", False) and kinds["h0"] == ("history", False)
    by_id = inputs.by_id()
    assert by_id["h0"].said_on == ["2026-01-10"]
    # An incoming fact carries the extraction's own row; its day is the conversation's.
    assert by_id["f1"].evidence and by_id["f1"].said_on == ["2026-03-02"]
    text = article.prompt(inputs, max_chars=100_000)
    assert "bob-example" in text and "the user" not in text.split("INPUT")[0].replace('never "the user"', "")
    assert article.prompt(inputs, max_chars=100) is None


def test_claims_are_inputs_with_their_own_evidence():
    claim = Claim(id="clm_1", text="alpha-project uses SQLite.", subject="alpha-project", predicate="uses",
                  object="sqlite", valid_from="2026-03-01",
                  evidence=[Evidence(episode="ep_2026-03-01_001", hash="0123456789ab", start=0, end=10, kind="user")])
    page = write_claims("## Summary\nA notes app.", [claim])
    inputs = _inputs(original_body=page)
    c0 = inputs.by_id()["c0"]
    assert c0.kind == "claim" and c0.said_on == ["2026-03-01"] and c0.evidence[0]["kind"] == "user"


def test_an_inferred_claim_reaches_the_writer_marked_as_one():
    """Ruling 48 (16), DR-80: what an agent only inferred is worded as an inference in the article."""
    guess = Claim(id="clm_2", text="alpha-project seems to favour local files.", subject="alpha-project",
                  predicate="prefers", object="local-files", epistemic="inductive", valid_from="2026-03-02")
    said = Claim(id="clm_3", text="alpha-project uses SQLite.", subject="alpha-project", predicate="uses",
                 object="sqlite", valid_from="2026-03-01")
    inputs = _inputs(original_body=write_claims("## Summary\nA notes app.", [guess, said]))
    texts = {s.text for s in inputs.sources if s.kind == "claim"}
    assert f"{article.INFERRED} alpha-project seems to favour local files." in texts
    assert "alpha-project uses SQLite." in texts
    assert '"(inferred)"' in article.PROMPT


def _answer(**over):
    answer = {
        "summary": {"text": "alpha-project is a notes app bob-example builds; it has 40 users as of March 2026.",
                    "from": ["s0", "s1"]},
        "sections": [{"title": "How it works", "paragraphs": [
            {"text": "It runs on a laptop and syncs through [[SQLite]].", "from": ["f0", "f1"]},
            {"text": "Work on it started in January 2026.", "from": ["h0"]}]}],
    }
    answer.update(over)
    return json.dumps(answer)


def test_parse_keeps_cited_paragraphs_with_their_inputs_evidence():
    inputs = _inputs()
    written = article.parse(_answer(), inputs, name="alpha-project", known=["SQLite", "sqlite"])
    assert written is not None and written.dropped == {}
    assert written.markdown() == ("### How it works\n\nIt runs on a laptop and syncs through [[SQLite]].\n\n"
                                  "Work on it started in January 2026.")
    assert written.lead.evidence and written.lead.evidence[0]["episode"] == "ep_2026-03-02_001"
    recs = article.records(written)
    assert recs[0]["field"] == "summary" and {r["field"] for r in recs[1:]} == {"article"}


def test_parse_drops_what_breaks_a_rail_and_rejects_a_bad_lead():
    inputs = _inputs()
    bad = {"title": "Background", "paragraphs": [
        {"text": "Notes apps are a large software category worldwide.", "from": []},           # G121: uncited
        {"text": "It currently runs on a laptop.", "from": ["f1"]},                            # G194
        {"text": "The user runs it on a laptop.", "from": ["f1"]},                             # G169
        {"text": "It runs on a laptop.", "from": ["h0"]},                                      # cites no shared word
        {"text": "It syncs with [[Postgres]].", "from": ["f0"]},                               # link to no page
    ]}
    written = article.parse(_answer(sections=[bad]), inputs, name="alpha-project", known=["SQLite"])
    assert written.dropped == {"uncited": 2, "relative_time": 1, "the_user": 1, "links_unwrapped": 1}
    assert written.markdown() == "### Background\n\nIt syncs with Postgres."
    for lead in ({"text": "It is now a notes app.", "from": ["s0"]}, {"text": "A notes app.", "from": []},
                 {"text": "Line one.\n\nLine two.", "from": ["s0"]}, "plain string"):
        assert article.parse(_answer(summary=lead), inputs, name="alpha-project") is None
    assert article.parse("not json", inputs, name="alpha-project") is None
    canonical = {"title": "Key Facts", "paragraphs": [{"text": "It runs on a laptop.", "from": ["f1"]}]}
    assert article.parse(_answer(sections=[canonical]), inputs, name="alpha-project").sections == []


def test_orientation_the_article_does_not_carry_is_retained_as_a_key_fact():
    inputs = _inputs()
    # The lead cites s0/s1 and carries "notes app" and "40 users"; the old Summary (p0) is not cited.
    written = article.parse(_answer(), inputs, name="alpha-project", known=["SQLite"])
    assert article.retained(inputs, written, name="alpha-project") == ["Old lead about alpha-project notes."]
    # A citing paragraph that drops the number does not carry the sentence.
    lead = {"text": "alpha-project is a notes app bob-example builds, used by many people.", "from": ["s0", "s1", "p0"]}
    written = article.parse(_answer(summary=lead), inputs, name="alpha-project", known=["SQLite"])
    assert "It has 40 users." in article.retained(inputs, written, name="alpha-project")


def test_compose_writes_lead_article_and_record_without_losing_an_item():
    inputs = _inputs()
    written = article.parse(_answer(), inputs, name="alpha-project", known=["SQLite"])
    data = article.payload(inputs, written, name="alpha-project")
    prose = ("## Summary\nOld lead about alpha-project notes.\n\n## Key Facts\n- Uses SQLite for sync.\n\n"
             "## History\n- 2026-01-10: Started.\n\n## Open Questions\n- Mobile app?")
    sections = article.compose(prose, "project", {"key_facts": ["Runs on a laptop."],
                                                  "history_entries": [{"date": "2026-03-02", "event": "40 users."}]},
                               data)
    assert sections["Summary"] == written.lead.text and sections["Article"] == written.markdown()
    facts = body._bullet_lines(sections["Key Facts"])
    assert facts == ["Uses SQLite for sync.", "Runs on a laptop.", "Old lead about alpha-project notes."]
    assert body._bullet_lines(sections["History"]) == ["2026-01-10: Started.", "2026-03-02: 40 users."]
    assert sections["Open Questions"] == "- Mobile app?"


def test_eligible_needs_two_conversations_after_the_update():
    assert not article.eligible({"source_episodes": ["ep_1"]}, ["ep_1"])
    assert article.eligible({"source_episodes": ["ep_1"]}, ["ep_2"])
    assert article.eligible({"source_episodes": ["ep_1", "ep_2"]}, [])


def test_worth_writing_is_two_conversations_or_enough_material():
    def inputs(*kinds):
        return article.Inputs([article.Source(f"x{i}", k, f"text {i}") for i, k in enumerate(kinds)], {})

    one = {"source_episodes": ["ep_1"]}
    rich = inputs("fact", "fact", "history", "said")
    thin = inputs("fact", "said", "earlier", "earlier", "link", "link")   # earlier prose and links are not material
    assert article.material(rich) == 4 and article.material(thin) == 2
    assert article.worth_writing(one, [], rich) and not article.worth_writing(one, [], thin)
    assert article.worth_writing(one, ["ep_2"], thin)                      # two conversations: always
    assert not article.worth_writing(one, [], rich, min_material=5)
    assert article.worth_writing(one, [], thin, min_material=1)
    assert not article.worth_writing(one, [], inputs("earlier"), min_material=0)   # nothing to write from
