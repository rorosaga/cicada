"""Direct saved-content API connectors (G71 §2).

G69's route matrix names exactly two platforms that expose a *personal saved
index* through a sanctioned API: Pinterest v5 and Reddit. Pinterest is
implemented here; Reddit is a planned peer for the same seam, added in a
follow-up slice. Everything else in Cicada's import story is an export-file
parser living in ``media_ingestor`` — aggregators were evaluated and rejected
(they cannot reach these surfaces, and every hosted one proxies tokens through
its own cloud).

House rules, meant to hold for every adapter added to this package:

* credentials live ONLY in ``$CICADA_HOME/secrets.env`` (0600) via
  ``connections.secrets`` — never in a bank, never in git, never in a log line,
  an error string, or an HTTP response;
* every HTTP call goes through an injected ``http_fn``, so the test suite has
  zero network and the default transport is the only code path that does;
* the default transport is additionally gated on ``CICADA_ALLOW_CONNECTOR_FETCH=1``
  (mirroring ``CICADA_ALLOW_FEED_FETCH`` / ``CICADA_ALLOW_LOGO_FETCH``);
* ``sync()`` never raises: a failure is recorded through
  ``sync_state.record_error`` and surfaces per-channel on ``GET /sources/channels``;
* nothing new is invented downstream — a connector emits ``RawItem``s into
  ``media_ingestor.ingest_batch`` and the Sleep pipeline absorbs them unchanged.
"""
