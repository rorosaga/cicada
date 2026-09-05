import SwiftUI

/// The grid of source cards (G124 — "in a grid, no horizontal scroll"),
/// grouped into sections by kind (Track D) so seventeen-odd sources read as
/// a handful of short, labelled groups instead of one long shuffled list.
/// Never-loaded → loading; loaded-but-empty → the one call to action (R2: a
/// row is shown only when it has evidence, and the Feed's `+` catalog is
/// where a person adds a source); otherwise one section per non-empty kind.
struct SourceCardGrid: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let isRefreshing: Bool
    let onOpen: (SourceOverview) -> Void

    private let columns = [GridItem(.adaptive(minimum: 220, maximum: 320), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        Group {
            if !hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sources…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if rows.isEmpty {
                Text("Nothing has fed this memory yet. Add a source from the Feed's + button.")
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(SourceSections.group(rows), id: \.kind) { section in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            Text(section.title)
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .tracking(1.2)
                            LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
                                ForEach(section.rows) { row in
                                    Button { onOpen(row) } label: { SourceCard(source: row) }
                                        .buttonStyle(.cicadaPlain)
                                        .accessibilityLabel("\(row.label), \(row.countLines.joined(separator: ", "))")
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
    }
}

/// One card: mark, label, the counts that apply, last activity, state. The
/// mark reuses `OriginMark` (Track D) — the same bundled-logo → drawn-glyph →
/// SF-Symbol precedence the Sleep queue and the import catalog already draw,
/// so a source's card, its queue row and its catalog tile show the identical
/// mark instead of the card alone falling back to a bare SF Symbol.
struct SourceCard: View {
    let source: SourceOverview

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: source.mark, size: 20)
                    .frame(width: 24, height: 24)
                    .background(OriginIconography.color(for: source.mark).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(source.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer()
                Circle().fill(source.connected ? CicadaTheme.success : CicadaTheme.textTertiary.opacity(0.4))
                    .frame(width: 7, height: 7)
                    .help(source.connected ? "Connected" : "Not connected")
            }
            ForEach(source.countLines, id: \.self) { line in
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let relative = relativeLastActivity {
                Text("Last \(relative)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let error = source.lastError, !error.isEmpty {
                Text("Needs attention").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger).help(error)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .contentShape(Rectangle())
    }

    private var relativeLastActivity: String? {
        guard let date = source.lastActivityDate else { return nil }
        let fmt = RelativeDateTimeFormatter(); fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }
}
