from api.services.entity_body import sections_to_fields


def test_sections_to_fields_maps_titles_and_splits_bullets():
    sections = {
        "Summary": "A one-line summary.",
        "Key Facts": "- fact one\n- fact two",
        "History": "- 2025-01-01: a thing",
        "Links": "- https://x.example",
        "Open Questions": "- what next?",
        "My Notes": "non-canonical prose",  # ignored by the structured shape
    }
    f = sections_to_fields(sections)
    assert f["summary"] == "A one-line summary."
    assert f["key_facts"] == ["fact one", "fact two"]
    assert f["history_entries"] == [{"date": "2025-01-01", "event": "a thing"}]
    assert f["links"] == ["https://x.example"]
    assert f["open_questions"] == ["what next?"]


def test_sections_to_fields_history_entries_dict_shape():
    f = sections_to_fields({"History": "- 2025-01-01: a thing\n- no-date event"})
    assert f["history_entries"] == [
        {"date": "2025-01-01", "event": "a thing"},
        {"date": "", "event": "no-date event"},
    ]
