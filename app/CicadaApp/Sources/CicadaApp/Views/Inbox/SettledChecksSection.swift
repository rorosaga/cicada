import SwiftUI

/// Owner ruling 2026-10-16 — "Settled by a check", under the Inbox's questions (and, ruling 29, "Settled by Sleep":
/// what Sleep answered from the person's own words or assumed, each with its reason): what a web lookup (or the person's own
/// agent) answered for them, each with its answer, the page and quote it rests on, and two neutral actions — Undo puts
/// the question back and takes back only what the check wrote; Track this source makes the citation one of the places
/// Cicada re-checks (only on this tap; a citation is never a tracked source by itself). Open, capped, "All N" to the
/// whole list (ruling 48 (17), DR-81 — it was closed until asked for). Neutral buttons, no accent (DR-40); a fill, not a lift (DR-48); a
/// disabled action says why (DR-41); a keyboard path never animates (DR-60).
struct SettledChecksSection: View {
    let model: SettledChecks
    /// The Inbox refreshes its questions after an undo — the question is back there.
    let onUndone: @MainActor () async -> Void

    var body: some View {
        // Ruling 29: two groups, one machinery — what a check settled, and what Sleep answered or assumed.
        let checks = model.rows.filter { !$0.bySleep }
        let sleep = model.rows.filter(\.bySleep)
        if !model.rows.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SettledGroup(rows: checks, model: model, onUndone: onUndone, title: Copy.Inbox.settledTitle,
                             header: Copy.Inbox.settledHeader(checks.count), help: Copy.Inbox.settledShowHelp)
                SettledGroup(rows: sleep, model: model, onUndone: onUndone, title: Copy.Inbox.settledSleepTitle,
                             header: Copy.Inbox.settledSleepHeader(sleep.count), help: Copy.Inbox.settledSleepShowHelp)
                if let message = model.message {
                    Text(message)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.top, CicadaTheme.spacingMD)
        }
    }
}

/// One group of settled questions (ruling 48 (17), DR-81 — no folds): open, its first `SettledGroup.cap` rows under its
/// label, and "All N" opening the whole group in a sheet.
private struct SettledGroup: View {
    static let cap = 3

    let rows: [SettledCheck]
    let model: SettledChecks
    let onUndone: @MainActor () async -> Void
    let title: String
    let header: String
    let help: String

    @State private var showAll = false

    var body: some View {
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(header)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if rows.count > Self.cap {
                        InlineLink(title: Copy.FullList.all(rows.count), help: help) { showAll = true }
                    }
                }
                list(Array(rows.prefix(Self.cap)))
            }
            .sheet(isPresented: $showAll) {
                FullListSheet(title: title) { list(rows) }
            }
        }
    }

    private func list(_ shown: [SettledCheck]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(shown) { row in
                SettledCheckRow(row: row, tracked: model.tracked.contains(row.id),
                                busy: model.busy.contains(row.id),
                                undo: { Task { await model.undo(row, then: onUndone) } },
                                track: { Task { await model.track(row) } })
            }
        }
    }
}

struct SettledCheckRow: View {
    let row: SettledCheck
    let tracked: Bool
    let busy: Bool
    let undo: () -> Void
    let track: () -> Void

    private var when: String {
        InboxAge.phrase(days: InboxAge.days(since: row.settledAt, now: .now))
    }

    private var who: String {
        row.settledByKind == "agent" ? Copy.Inbox.settledByAgent : Copy.Inbox.settledBySleep
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.Inbox.settledAnswer(row.entityName, row.answer))
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
            if !row.quote.isEmpty {
                Text(Copy.Inbox.settledQuote(row.quote))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }
            if row.bySleep {
                Text(Copy.Inbox.settledSleepMeta(row.reason, when))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                Text(Copy.Inbox.settledMeta(row.host, when, who))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(row.ref)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.Inbox.settledUndo, size: .compact, isDisabled: busy,
                              help: row.bySleep ? Copy.Inbox.settledSleepUndoHelp : Copy.Inbox.settledUndoHelp,
                              action: undo)
                if row.canTrack {
                    NeutralButton(title: tracked ? Copy.Inbox.settledTracked : Copy.Inbox.settledTrack, size: .compact,
                                  isDisabled: tracked || busy, help: Copy.Inbox.settledTrackHelp, action: track)
                }
            }
        }
        .padding(CicadaTheme.scaled(10))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgHover))
    }
}
