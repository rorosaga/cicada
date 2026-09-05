import SwiftUI

/// Pure presentation for one `SleepHistoryEntry` (G125 R4/R5) — how long a
/// cycle took, its one-line summary, and its git-short date, each a static
/// function so wording is asserted in `SleepHistoryPresentationTests`
/// without standing up `ConsolidationHistoryCard` itself.
enum SleepHistoryPresentation {
    /// `nil` (no `sleep_run` ledger row joined — telemetry off, or the row
    /// predates this cycle) reads as an honest "—", never a guess (R5).
    /// Below a minute: whole seconds. Below an hour: minutes + the leftover
    /// seconds, both floored (so "4 m 12 s" means exactly that, not rounded).
    /// An hour or more: hours + minutes, both taken from the ROUNDED total
    /// minute count — at that scale seconds are noise, and a floor would
    /// under-report a cycle that ran 61.7 minutes as "1 h 1 m" instead of
    /// "1 h 2 m".
    static func durationText(ms: Int?) -> String {
        guard let ms, ms >= 0 else { return "—" }
        let totalSeconds = ms / 1000
        if totalSeconds < 60 {
            return "\(totalSeconds) s"
        }
        if totalSeconds < 3600 {
            let minutes = totalSeconds / 60
            let seconds = totalSeconds % 60
            return seconds > 0 ? "\(minutes) m \(seconds) s" : "\(minutes) m"
        }
        let totalMinutes = Int((Double(ms) / 60_000).rounded())
        let hours = totalMinutes / 60
        let remMinutes = totalMinutes % 60
        return remMinutes > 0 ? "\(hours) h \(remMinutes) m" : "\(hours) h"
    }

    /// A decay-only commit (the G85 split's `Sleep cycle <date> (decay)`) is
    /// pure arithmetic over entities never mentioned — no extraction ran, so
    /// "+N new · M updated" would credit an LLM for work it never did. Every
    /// other kind counts entities the manifest actually attributes to
    /// `sleep/extraction`/`sleep/promotion`/etc.
    static func summaryLine(_ e: SleepHistoryEntry) -> String {
        if e.kind == "decay" { return "decay pass" }
        return "+\(e.entitiesCreated) new · \(e.entitiesUpdated) updated"
    }

    /// `date` arrives as git's `--date=iso-strict` (`2026-09-05T21:41:00+00:00`)
    /// since R-A11, and as the older `--date=short` (`yyyy-MM-dd`) from any
    /// snapshot cached before that. git renders BOTH in the COMMIT's own
    /// zone — the previous comment here claimed `--date=short` was "anchored
    /// UTC" and the formatter pinned UTC, which would shift the displayed
    /// hour the moment a time existed. The offset is parsed for real and the
    /// result displayed in the reader's zone; `timeZone` is injectable so the
    /// tests never depend on the runner's locale.
    static func parsed(_ iso: String) -> Date? {
        let withOffset = ISO8601DateFormatter()
        withOffset.formatOptions = [.withInternetDateTime]
        if let d = withOffset.date(from: iso) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        dayOnly.locale = Locale(identifier: "en_US_POSIX")
        return dayOnly.date(from: String(iso.prefix(10)))
    }

    /// A raw string that fails to parse is shown as-is rather than hidden
    /// behind a blank field. A date-only value carries no zone of its own, so
    /// it keeps the UTC anchor it was parsed with — re-projecting a bare day
    /// into the reader's zone is what would slide it to the previous day.
    static func dateText(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard let date = parsed(iso) else { return iso }
        let f = DateFormatter()
        f.dateFormat = "MMM d"
        f.timeZone = iso.contains("T") ? timeZone : TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }

    /// `—`, never a fabricated midnight, for a value that carries no time
    /// (R-A14): a legacy `--date=short` row genuinely does not know the hour.
    static func timeText(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard iso.contains("T"), let date = parsed(iso) else { return "—" }
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        f.timeZone = timeZone
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }

    /// Which SF Symbol names an engine (G125) — `nil` (no `Cicada-Engine:`
    /// trailer; a decay or state-snapshot commit never carries one) gets a
    /// neutral placeholder rather than defaulting to any one real engine's
    /// icon.
    static func engineSymbol(_ engine: String?) -> String {
        switch engine {
        case "claude-cli": "cpu"
        case "ollama": "desktopcomputer"
        case "litellm": "key"
        default: "circle.dashed"
        }
    }

    /// `authors` are model ids ("gpt-5.4-mini") except the literal `user` —
    /// never shown as the raw literal, since a person reads it as "you", not
    /// as a model that ran.
    static func authorLabel(_ author: String) -> String {
        author == "user" ? "you" : author
    }
}

/// "RECENT CONSOLIDATIONS" (G125 R4/R12) — the Sleep page's history, newest
/// first. Each row is one commit; tapping it asks the caller (`onToggle`) to
/// flip `expanded` and fetch `details[commit]` if it isn't cached yet — this
/// view never fetches on its own, mirroring `StudyListCard`'s own "pure
/// renderer of what the caller already resolved" posture.
struct ConsolidationHistoryCard: View {
    let entries: [SleepHistoryEntry]
    let details: [String: SleepCycleDetail]
    let expanded: String?
    let onToggle: (String) -> Void
    var onSelectEntity: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("RECENT CONSOLIDATIONS")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            if entries.isEmpty {
                Text("Nothing consolidated yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            } else {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(entries) { entry in
                        row(entry)
                        if expanded == entry.commitHash {
                            detail(for: entry)
                                .padding(.leading, CicadaTheme.spacingLG)
                                .padding(.bottom, CicadaTheme.spacingSM)
                        }
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func row(_ entry: SleepHistoryEntry) -> some View {
        // A decay-only commit is arithmetic, not a consolidation an LLM
        // authored (G85) — every part of its row reads as muted so it never
        // looks like the same kind of event as a real cycle.
        let isDecay = entry.kind == "decay"
        let tone: Color = isDecay ? CicadaTheme.textTertiary : CicadaTheme.textSecondary
        return Button {
            onToggle(entry.commitHash)
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(SleepHistoryPresentation.dateText(entry.date))
                    .font(CicadaTheme.font(size: 11, design: .monospaced))
                    .foregroundStyle(tone)
                    .frame(width: 44, alignment: .leading)

                Image(systemName: SleepHistoryPresentation.engineSymbol(entry.engine))
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(isDecay || entry.engine == nil ? CicadaTheme.textTertiary : CicadaTheme.accent)
                    .frame(width: 14)

                Text(SleepHistoryPresentation.summaryLine(entry))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(isDecay ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                    .lineLimit(1)

                Spacer()

                Text(SleepHistoryPresentation.durationText(ms: entry.durationMs))
                    .font(CicadaTheme.font(size: 11, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)

                Image(systemName: expanded == entry.commitHash ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 9, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel("\(SleepHistoryPresentation.dateText(entry.date)), \(SleepHistoryPresentation.summaryLine(entry))")
    }

    @ViewBuilder
    private func detail(for entry: SleepHistoryEntry) -> some View {
        if let d = details[entry.commitHash] {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if !d.episodesByOrigin.isEmpty {
                    FlowLayout(spacing: 6) {
                        ForEach(d.episodesByOrigin.sorted(by: { $0.key < $1.key }), id: \.key) { origin, count in
                            HStack(spacing: 4) {
                                OriginMark(origin: origin, size: 12)
                                Text("\(count)")
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                            }
                        }
                    }
                }

                Text("\(d.sessions) conversation\(d.sessions == 1 ? "" : "s") · \(d.authors.map(SleepHistoryPresentation.authorLabel).joined(separator: ", "))")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                if d.entities.isEmpty {
                    Text("No entity pages changed.")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                } else {
                    FlowLayout(spacing: 6) {
                        ForEach(d.entities) { entity in
                            Button(entity.id) { onSelectEntity?(entity.id) }
                                .buttonStyle(.cicadaPlain)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.accent)
                        }
                        if d.truncated {
                            Text("+ more")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                }

                if d.inboxChanges > 0 {
                    Text("\(d.inboxChanges) inbox item\(d.inboxChanges == 1 ? "" : "s") changed")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        } else {
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Loading…")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }
}
