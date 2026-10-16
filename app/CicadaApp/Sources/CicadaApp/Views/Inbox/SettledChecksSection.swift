import SwiftUI

/// Owner ruling 2026-10-16 — "Settled by a check", under the Inbox's questions: what a web lookup (or the person's own
/// agent) answered for them, each with its answer, the page and quote it rests on, and two neutral actions — Undo puts
/// the question back and takes back only what the check wrote; Track this source makes the citation one of the places
/// Cicada re-checks (only on this tap; a citation is never a tracked source by itself). Closed until asked for — the
/// inbox is there when wanted, not pushed (UX 4). Neutral buttons, no accent (DR-40); a fill, not a lift (DR-48); a
/// disabled action says why (DR-41); a keyboard path never animates (DR-60).
struct SettledChecksSection: View {
    let model: SettledChecks
    /// The Inbox refreshes its questions after an undo — the question is back there.
    let onUndone: @MainActor () async -> Void

    @State private var open = false

    var body: some View {
        if !model.rows.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Button { Instant.run { open.toggle() } } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Image(systemName: open ? "chevron.down" : "chevron.right")
                            .font(CicadaTheme.captionFont)
                        Text(Copy.Inbox.settledHeader(model.rows.count))
                            .font(CicadaTheme.metaMediumFont)
                    }
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help(Copy.Inbox.settledShowHelp)
                .accessibilityLabel(Copy.Inbox.settledTitle)
                .accessibilityValue(open ? "expanded" : "collapsed")

                if open {
                    ForEach(model.rows) { row in
                        SettledCheckRow(row: row, tracked: model.tracked.contains(row.id),
                                        busy: model.busy.contains(row.id),
                                        undo: { Task { await model.undo(row, then: onUndone) } },
                                        track: { Task { await model.track(row) } })
                    }
                    if let message = model.message {
                        Text(message)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            .padding(.top, CicadaTheme.spacingMD)
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
            Text("\(row.entityName) — \(row.answer)")
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
            if !row.quote.isEmpty {
                Text("\u{201C}\(row.quote)\u{201D}")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }
            Text("\(Copy.Inbox.settledFrom(row.host, when)) · \(who)")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .help(row.ref)
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.Inbox.settledUndo, size: .compact, isDisabled: busy,
                              help: Copy.Inbox.settledUndoHelp, action: undo)
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
