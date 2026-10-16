import Foundation

/// The Sleep redesign (owner approval 2026-10-16, DESIGN_RULES §9) — the page's four lists under the room, one list
/// grammar (DR-45). Details retired: its four sections and the Feed became these tabs.
///
/// - **Waiting** — what Sleep has not read yet (Details › What's waiting).
/// - **Saved** — everything that came in (the Feed's list, its sort and kind filter, its detail column).
/// - **Videos** — the Feed's Videos list and its watch run; drawn only while a video is saved (one queue, one place).
/// - **Past reads** — Last cycle, the Readout and Past nights (ruling 12's one home for prices on this page).
enum SleepTab: String, CaseIterable, Hashable {
    case waiting, saved, videos, pastReads

    var label: String {
        switch self {
        case .waiting: Copy.SleepTabs.waiting
        case .saved: Copy.SleepTabs.saved
        case .videos: Copy.SleepTabs.videos
        case .pastReads: Copy.SleepTabs.pastReads
        }
    }

    /// The tabs on screen, in order. A count of zero hides its tab (DR-45; owner 2026-10-16, "Waiting 0 · Saved 0" on a
    /// fresh page): Waiting while nothing waits (unless a run's own block, a parked conversation or a queue that could
    /// not be read still has something to say there), Saved while nothing is saved, Videos while none is. Past reads
    /// always shows — it carries no count, and the page needs one list.
    static func visible(waitingHasRows: Bool, saved: Int, videos: Int) -> [SleepTab] {
        allCases.filter { tab in
            switch tab {
            case .waiting: waitingHasRows
            case .saved: saved > 0
            case .videos: videos > 0
            case .pastReads: true
            }
        }
    }

    /// The tab the page opens on: Waiting while anything waits, Past reads when nothing does (§3.5).
    static func preferred(waitingHasRows: Bool) -> SleepTab { waitingHasRows ? .waiting : .pastReads }

    /// The person's choice wins while its tab is on screen; a choice whose tab hid (the queue emptied, the last video
    /// went) falls back to the preferred tab rather than to a list that is not drawn.
    static func resolve(chosen: SleepTab?, waitingHasRows: Bool, saved: Int, videos: Int) -> SleepTab {
        let shown = visible(waitingHasRows: waitingHasRows, saved: saved, videos: videos)
        if let chosen, shown.contains(chosen) { return chosen }
        return preferred(waitingHasRows: waitingHasRows)
    }

    /// Every old Details section lands on the tab that holds it now (DESIGN §3.6): What's waiting → Waiting; Last
    /// cycle, the Readout and Past nights → Past reads.
    static func holding(_ section: DetailsSection) -> SleepTab {
        section == .waiting ? .waiting : .pastReads
    }

    /// Find (⌘F) searches a list of saved items; Waiting and Past reads have none to search.
    var hasFind: Bool { self == .saved || self == .videos }
}

/// "Sleep · 42 waiting · last read 2 h ago" — the page's eyebrow (DR-25, DR-26), which replaced the "Sleep Cycle"
/// title. Pure: `now` is passed in. A count goes through `UsageFormat` (DR-21); no last read is said until one happened.
enum SleepEyebrow {
    static func text(waiting: Int, lastSleepAt: String?, now: Date) -> String {
        let count = waiting > 0 ? Copy.SleepTabs.waitingCount(waiting) : Copy.SleepTabs.nothingWaiting
        let last = lastSleepAt.flatMap { InboxAge.date($0) }.map { Copy.SleepTabs.lastRead(ago($0, now: now)) } ?? ""
        return Eyebrow.text(Copy.SleepTabs.page, count, last)
    }

    /// "just now", "12 min ago", "2 h ago", then the Inbox's day words ("yesterday", "3 days ago").
    static func ago(_ date: Date, now: Date) -> String {
        let seconds = max(0, now.timeIntervalSince(date))
        if seconds < 60 { return Copy.SleepTabs.justNow }
        if seconds < 3_600 { return Copy.SleepTabs.minutesAgo(Int(seconds / 60)) }
        if seconds < 86_400 { return Copy.SleepTabs.hoursAgo(Int(seconds / 3_600)) }
        return InboxAge.phrase(days: Int(seconds / 86_400))
    }
}

extension SleepLayout {
    /// The room's art, out of its card (DESIGN §3.2): the 160 × 64 lattice at a WHOLE number of points per cell, so a
    /// pixel is never resampled (ruling R3, TODO ruling 18). A step function of the width the art may take — 5 pt
    /// (800 × 320) from 880, 4 pt (640 × 256) from 720, else 3 pt (480 × 192) — never fractional, so a window resize
    /// never blurs a pixel. Below 480 (only ⌘+ zoom with the Reader open gets there) it is 2 pt rather than clipped.
    static func artScale(columnWidth: CGFloat) -> CGFloat {
        if columnWidth >= 880 { return 5 }
        if columnWidth >= 720 { return 4 }
        if columnWidth >= CGFloat(RoomLattice.cols) * 3 { return 3 }
        return 2
    }

    /// The widest the art is drawn: 880 pt of column (the 800 pt room and its breathing room).
    static let artMaxWidth: CGFloat = 880
}
