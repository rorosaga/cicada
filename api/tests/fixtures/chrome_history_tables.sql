-- G71 (2026-10-16): the two tables of Chrome's `History` database the app's YouTube reader queries, with Chrome's own
-- column names (a synthetic subset, no data). Built by api/tests/test_watch_history.py and the app's
-- WatchHistoryTests (SyntheticChromeHistory), so both run `ChromeWatchHistoryReader.visitsSQL` against one schema.
CREATE TABLE urls(id INTEGER PRIMARY KEY AUTOINCREMENT, url LONGVARCHAR, title LONGVARCHAR,
                  visit_count INTEGER DEFAULT 0 NOT NULL, typed_count INTEGER DEFAULT 0 NOT NULL,
                  last_visit_time INTEGER NOT NULL DEFAULT 0, hidden INTEGER DEFAULT 0 NOT NULL);
CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER NOT NULL, visit_time INTEGER NOT NULL,
                    from_visit INTEGER, transition INTEGER DEFAULT 0 NOT NULL, segment_id INTEGER,
                    visit_duration INTEGER DEFAULT 0 NOT NULL);
CREATE TABLE keyword_search_terms(keyword_id INTEGER NOT NULL, url_id INTEGER NOT NULL, term LONGVARCHAR NOT NULL,
                                  normalized_term LONGVARCHAR NOT NULL);
