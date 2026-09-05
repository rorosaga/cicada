import SwiftUI

/// One queued/processed episode — a status dot (queued vs processed), the
/// source's mark (G105 companion: "where did this come from" at a glance,
/// the same mark the import catalog tile and the study list row wear),
/// title, source pill, timestamp and a two-line preview.
///
/// Extracted out of `SleepView.swift` (G125 Task 6, R11) — previously a
/// `private struct` used only by the old queue card, it is now `internal`
/// because `StudyListCard`'s per-origin disclosure renders it too.
struct EpisodeRow: View {
    let item: EpisodeQueueItem

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Circle()
                .fill(item.processed ? CicadaTheme.textTertiary : CicadaTheme.accent)
                .frame(width: 8, height: 8)
                .padding(.top, 6)

            OriginMark(origin: item.origin, size: 16)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(item.title ?? item.id)
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)

                    Text(item.source)
                        .font(CicadaTheme.font(size: 9, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 2)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Capsule())

                    Spacer()

                    Text(shortTimestamp(item.timestamp))
                        .font(CicadaTheme.font(size: 10, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }

                if !item.preview.isEmpty {
                    Text(item.preview)
                        .font(CicadaTheme.font(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(2)
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(CicadaTheme.surfaceHover.opacity(0.35))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private func shortTimestamp(_ raw: String) -> String {
        guard !raw.isEmpty else { return "—" }
        // Accept both ISO-8601 and plain dates; fall back to raw on parse failure.
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) {
            return Self.display.string(from: date)
        }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: raw) {
            return Self.display.string(from: date)
        }
        return String(raw.prefix(16))
    }

    private static let display: DateFormatter = {
        let f = DateFormatter()
        // Include the year — the queue can span multiple years after a bulk
        // import and a bare "Nov 3" is ambiguous without it.
        f.dateFormat = "MMM d, yyyy HH:mm"
        return f
    }()
}
