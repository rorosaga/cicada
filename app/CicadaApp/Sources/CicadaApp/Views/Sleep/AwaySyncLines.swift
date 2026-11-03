import SwiftUI

/// G229 — under the machines strip, the sync each machine's app does after it was closed: one quiet line per machine
/// syncing ("Syncing Messages and Notes — 14 new conversations so far. 9 conversations came in while you were away.")
/// and, under it, one line per source that could not be read, its first clause in `warning` (DR-7) and the reader's own
/// sentence naming the fix; a click opens Sources, where that source's row and its button are.
///
/// Why here: the strip right above already says each machine's "N waiting", and this says why that number is still
/// moving — so the two read as one (DR-38: nothing said twice). Text only, in the column's caption face (DR-36): no
/// banner, no card for a line (DR-37), no motion (DR-61) — a static glyph says syncing or synced, and the words change
/// when the backend's answer does. Nothing here when no machine is syncing or has just synced.
struct AwaySyncLines: View {
    let entries: [(name: String?, catchUp: MachineAwaySync)]
    var openSources: () -> Void = {}

    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .center, spacing: CicadaTheme.spacingXS) {
                ForEach(Array(entries.enumerated()), id: \.offset) { _, entry in
                    line(entry.name, entry.catchUp)
                    ForEach(AwaySyncWords.failures(entry.catchUp), id: \.channel) { failure in
                        failureLine(failure)
                    }
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func line(_ name: String?, _ catchUp: MachineAwaySync) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
            Image(systemName: catchUp.isReading ? "arrow.triangle.2.circlepath" : "checkmark")
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            Text(AwaySyncWords.line(catchUp, machine: name))
                .font(CicadaTheme.captionFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
        }
        .accessibilityElement(children: .combine)
    }

    private func failureLine(_ failure: AwaySyncWords.Failure) -> some View {
        Button(action: openSources) {
            (Text(failure.lead).foregroundStyle(CicadaTheme.warning)
             + Text(verbatim: failure.fix.map { " " + $0 } ?? "").foregroundStyle(CicadaTheme.textSecondary))
                .font(CicadaTheme.captionFont)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.AwaySync.openSourcesHelp)
    }
}
