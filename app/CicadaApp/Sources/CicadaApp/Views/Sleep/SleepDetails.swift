import SwiftUI

/// Whether Details › Last cycle has anything to say (Track Z §4.1 F). The
/// four inputs are exactly the four banners' own conditions, so the section
/// can never render as an empty header.
func lastCycleSectionIsVisible(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?) -> Bool {
    pageError != nil || cancelled || capped || !(indexWarning ?? "").isEmpty
}

/// The page's one second surface (R-Z6, R-Z7): opened on purpose, remembered
/// per viewer (spec decision 16), and **not built while closed** — `SleepView`
/// wraps it in `if detailsOpen {}`, so a closed Details costs no queue
/// `LazyVStack`, no history and no tiles (design §10's budget).
///
/// Each section carries its `DetailsSection.anchorID`, which is how a sentence
/// tail ("it's in Details") and "See what changed ›" land on the right card.
/// R-A12: every section takes the liveness desaturation except Last cycle —
/// news stays at full contrast. The `.saturation` is applied unconditionally
/// (identity 1.0 while live) for the reason `SleepView.roomCard`'s call site
/// gives: a conditional modifier would remount the card and empty
/// `StudyListCard`'s expanded rows whenever the connection flaps.
struct SleepDetails: View {
    static let openKey = "cicada.sleep.detailsOpen"
    static let defaultOpen = false

    let page: SleepPageModel
    let liveness: SleepLiveness
    let pageError: String?
    let status: SleepStatusResponse?
    let episodes: [EpisodeQueueItem]
    let history: [SleepHistoryEntry]
    let details: [String: SleepCycleDetail]
    let expanded: String?
    let onToggleHistory: (String) -> Void
    var onSelectEntity: ((String) -> Void)?
    /// Track Z Z6 (I5, I7) — hands the room to What's waiting, so a row and
    /// its spine answer each other's hover.
    var room: RoomModel? = nil

    var body: some View {
        // R-HS15 — 28 pt between sections, the D-Sleep mock's gap: sections are labels over rows
        // now, so the space between them is what separates them (DR-37).
        VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
            if lastCycleSectionIsVisible(pageError: pageError, cancelled: page.cancelled,
                                         capped: page.capped, indexWarning: page.indexWarning) {
                LastCycleSection(pageError: pageError, status: status, cancelled: page.cancelled,
                                 capped: page.capped, indexWarning: page.indexWarning)
                    .id(DetailsSection.lastCycle.anchorID)
            }
            StudyListCard(rows: page.rows, episodes: episodes, queueLoad: page.queueLoad,
                          onSelectEntity: onSelectEntity, room: room)
                .id(DetailsSection.waiting.anchorID)
                .saturation(liveness.saturation)
            SleepReadoutView(mood: page.mood, debt: page.debt, read: page.read, total: page.total,
                             lastDurationMs: page.lastCycle?.durationMs,
                             lastEngine: status?.lastEngine, engineDetail: status?.engineDetail)
                .id(DetailsSection.readout.anchorID)
                .saturation(liveness.saturation)
            ConsolidationHistoryCard(entries: history, details: details, expanded: expanded,
                                     onToggle: onToggleHistory, onSelectEntity: onSelectEntity)
                .id(DetailsSection.pastNights.anchorID)
                .saturation(liveness.saturation)
        }
    }
}

/// DR-20, DR-37, DR-47 — one Details section in D's list grammar (R-HS15): its `SectionLabel` over
/// rows, no card. Details was four glass cards with their labels inside; §10 (Sleep) asks for "rows
/// and section labels, no bordered cards".
struct SleepDetailsSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            SectionLabel(title)
                .padding(.horizontal, CicadaTheme.scaled(10))
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One line of Details › Last cycle (R-HS15): what happened, in the words the banners said, and a
/// glyph that says whether it needs the person — a failure or a warning in `warning`, a cancel or a
/// cap in `textTertiary`. The filled banners (`danger`/`accent`/`warning` at 10–12 %) retired: DR-7
/// keeps `danger` for destructive actions, and a row never sits on a tint.
struct LastCycleRow: Equatable, Identifiable {
    enum Kind: String, Equatable { case failed, cancelled, capped, warning }

    let kind: Kind
    let title: String
    let text: String
    var id: String { kind.rawValue }
    var needsYou: Bool { kind == .failed || kind == .warning }
    var glyph: String {
        switch kind {
        case .failed, .warning: "exclamationmark.triangle"
        case .cancelled: "stop.circle"
        case .capped: "tray.and.arrow.down"
        }
    }

    /// The four conditions `lastCycleSectionIsVisible` reads, in the page's order. The cap's numbers
    /// come from the status itself, as the banner's did (L1/L4).
    static func rows(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?,
                     status: SleepStatusResponse?, locale: Locale = .autoupdatingCurrent) -> [LastCycleRow] {
        var rows: [LastCycleRow] = []
        if let pageError {
            rows.append(LastCycleRow(kind: .failed, title: Copy.SleepDetailsWords.failedTitle, text: pageError))
        }
        if cancelled {
            rows.append(LastCycleRow(kind: .cancelled, title: Copy.SleepDetailsWords.cancelledTitle,
                                     text: Copy.SleepDetailsWords.cancelledText))
        }
        if capped, let s = status {
            rows.append(LastCycleRow(kind: .capped, title: Copy.SleepDetailsWords.capTitle(s.episodeCap, locale: locale),
                                     text: Copy.SleepDetailsWords.capText(processed: s.episodesTotal,
                                                                          queued: s.episodesQueued, locale: locale)))
        }
        // Non-fatal warnings (e.g. the episode index rebuild failed even though entity writes and
        // the commit succeeded), so a "completed with warnings" cycle never looks like a clean pass.
        if let warning = indexWarning, !warning.isEmpty {
            rows.append(LastCycleRow(kind: .warning, title: Copy.SleepDetailsWords.warningTitle, text: warning))
        }
        return rows
    }
}

/// Details › Last cycle — the error (`pageError`), the cancel, the episode cap and the index warning,
/// at full contrast (R-A12). Moved from `SleepView` (Track Z §4.2); R-HS15 turned its four filled
/// banners into `LastCycleRow`s under the section's label.
///
/// Review fix L1/L4 still holds: `cancelled`/`episodeCap`/`episodesQueued`
/// were decoded but read by no view — only the free-text `progress` sentence
/// mentioned either — so each gets a real, structured readout here rather than
/// depending on the person to parse a sentence. The three conditions arrive
/// already resolved on `SleepPageModel` (the same values the sentence's tail
/// read), and the cap NUMBERS still come from the status itself.
struct LastCycleSection: View {
    let pageError: String?
    let status: SleepStatusResponse?
    let cancelled: Bool
    let capped: Bool
    let indexWarning: String?

    var body: some View {
        SleepDetailsSection(title: "Last cycle") {
            ForEach(LastCycleRow.rows(pageError: pageError, cancelled: cancelled, capped: capped,
                                      indexWarning: indexWarning, status: status)) { row in
                HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                    Image(systemName: row.glyph)
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(row.needsYou ? CicadaTheme.warning : CicadaTheme.textTertiary)
                        .padding(.top, CicadaTheme.scaled(2))
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        Text(row.title)
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Text(row.text)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.vertical, CicadaTheme.spacingSM)
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(row.needsYou ? .isStaticText : [])
            }
        }
    }
}
