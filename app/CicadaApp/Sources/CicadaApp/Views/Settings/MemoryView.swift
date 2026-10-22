import SwiftUI

/// Settings → Memory (G139): G147's *How things fade* (`FadePaceCard`) — suggestions from the person's own decay
/// answers, applied only on Apply.
///
/// Search & files (owner, 2026-10-14) took the search index and the search version: how Cicada *finds* things now
/// lives on `SearchFilesView`, and Memory keeps how it tidies what it knows.
///
/// *Fetch link previews* left the page (settings defaults, owner 2026-10-22; UX principle 1, "never require memory
/// maintenance"): Sleep's tail already describes saved links on every run (`link_enrich_backfill_per_cycle`, 20 a
/// run, behind the same kill switch), so the button only hurried what happens anyway. The route
/// (`POST /maintenance/enrich-links`) stays for developers.
///
/// "Look for duplicates" is deliberately absent (R-O17): the dedup endpoint
/// blocks the event loop, its dry run never reaches the Inbox, and its live
/// run leaves uncommitted merges for the next `git add -A` writer (the G85
/// smear). `CicadaPagesTests.testNoPageCallsTheDedupSweep` holds that line.
struct MemoryView: View {
    var body: some View {
        SettingsPage(section: .memory) {
            FadePaceCard()
        }
    }
}
