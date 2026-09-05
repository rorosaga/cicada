import SwiftUI

/// R-S6 — *who wrote your memory*, in one strip.
///
/// What it replaces (`ContributorsSection`, deleted with this file's arrival):
/// one padded, expandable card per author, each carrying its own unlabelled
/// 4 pt bar scaled by `commitCount / totalCommits` and sitting under numbers
/// that were entities and files (critique E2), with a 53-week calendar
/// expanding *in place* so the page grew by a screenful per click (E4). On a
/// real bank that is a wall of near-identical rows that never answers the one
/// question the section is named after.
///
/// What replaces it: a chip row over ONE stacked bar with ONE named scale
/// (`ContributorShare`), and a sentence (`ContributorSummary`). The drill-down
/// is unchanged — it moved into `ContributorDrillDown` and opens in a sheet
/// (R-S15), so the page stays one screen tall and ⌘[ keeps meaning exactly one
/// thing on this page (`SourcesRoute`'s Back).
///
/// The four states of the old section move with it and are not dropped: error →
/// never-loaded → loaded-but-empty → content. The never-loaded branch matters
/// most — "No attributed commits yet" on a cold launch with the backend down is
/// a claim about the repo, not about the request that failed.
struct ContributorsStrip: View {
    @Environment(ContributorsViewModel.self) private var viewModel

    /// The author whose drill-down is open, or nil. One at a time by
    /// construction: a sheet is modal, where the old in-place expansion had to
    /// police itself with an `expandedAuthor` guard.
    @State private var sheetAuthor: Contributor?

    private var segments: [ContributorShare.Segment] {
        ContributorShare.segments(viewModel.contributors)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("WHO WROTE YOUR MEMORY")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            if let err = viewModel.errorMessage {
                errorState(err)
            } else if !viewModel.hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading commit trailers…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if segments.isEmpty {
                Text("No attributed commits yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                content
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        // No `.task { load() }`: `ContributorsViewModel` is a thin projection
        // over `Store.contributors`, already hydrated + kept live by the
        // Store — this strip renders instantly from the snapshot on revisit.
        .sheet(item: $sheetAuthor) { c in
            drillDownSheet(c)
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            FlowLayout(spacing: CicadaTheme.spacingSM) {
                ForEach(segments) { chip($0) }
            }
            bar
            Text("share of entities written")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(ContributorSummary.sentence(viewModel.contributors))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    /// One chip: the author's real mark, its name, its share. The mark is
    /// `ContributorAvatar` itself (R-S14) — the bookworm for Cicada's own
    /// maintenance, the provider's PNG for a model that ships one, initials
    /// otherwise — never a re-derived glyph.
    @ViewBuilder
    private func chip(_ segment: ContributorShare.Segment) -> some View {
        let label = HStack(spacing: CicadaTheme.spacingXS) {
            if let c = segment.contributor {
                ContributorAvatar(contributor: c, kind: ContributorIdentity.kind(of: c))
            }
            Text(segment.displayName)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            Text(Self.percent(segment.fraction))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .padding(.vertical, CicadaTheme.spacingXS)
        .background(CicadaTheme.surfaceHover.opacity(0.4))
        .clipShape(Capsule())

        if let c = segment.contributor {
            Button { sheetAuthor = c } label: { label.contentShape(Capsule()) }
                .buttonStyle(.cicadaPlain)
                // E3 — a long model id is elided in a chip, so the full,
                // honest `Cicada-Author` value stays one hover away.
                .help(segment.author)
                .accessibilityLabel("\(segment.displayName), \(Self.percent(segment.fraction)) "
                                    + "of entities written")
        } else {
            // The folded tail is not a button: there is no single author
            // behind it to drill into.
            label.help("Every remaining contributor, folded into one share")
        }
    }

    /// ONE stacked bar, not one bar per row (E2). A segment is floored at 2 pt
    /// so an author with a 0.4 % share is still visible — a slice that rounds
    /// to nothing reads as "this author wrote nothing", which is a different
    /// claim. The overshoot that floor can cause is bounded by the segment
    /// count (at most 6 × 2 pt) and never redistributed, because a bar that
    /// silently shrinks its biggest slice to pay for its smallest is the
    /// dishonest half of the same problem.
    private var bar: some View {
        GeometryReader { geo in
            HStack(spacing: 1) {
                ForEach(segments) { segment in
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Self.color(of: segment))
                        .frame(width: max(2, geo.size.width * segment.fraction))
                }
                Spacer(minLength: 0)
            }
            .frame(width: geo.size.width, alignment: .leading)
        }
        .frame(height: CicadaTheme.scaled(8))
        .background(CicadaTheme.border)
        .clipShape(RoundedRectangle(cornerRadius: 2))
        .accessibilityHidden(true)  // the chips above already speak every share
    }

    /// The same rule the old row's `accent` used, so a chip and its slice can
    /// never disagree: the user's own colour, the neutral tone for a legacy
    /// untrailered author, and otherwise the provider's colour — which is
    /// deliberately neutral for a router or an open-weight family (R-L6).
    private static func color(of segment: ContributorShare.Segment) -> Color {
        guard let c = segment.contributor else { return CicadaTheme.border }
        switch ContributorIdentity.kind(of: c) {
        case "user": return CicadaTheme.info
        case "unknown": return CicadaTheme.textTertiary
        case "system": return CicadaTheme.accent
        default: return ContributorAvatar.providerColor(c.provider)
        }
    }

    /// Whole percent. `UsageFormat.percent` takes the value already scaled to
    /// 0–100 for the Codex rate-limit windows, so the share is scaled here
    /// rather than teaching that formatter a second convention.
    private static func percent(_ fraction: Double) -> String {
        UsageFormat.percent(fraction * 100)
    }

    private func drillDownSheet(_ c: Contributor) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ContributorAvatar(contributor: c, kind: ContributorIdentity.kind(of: c))
                Text(ContributorIdentity.displayName(author: c.author,
                                                     kind: ContributorIdentity.kind(of: c)))
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                Button { sheetAuthor = nil } label: {
                    Image(systemName: "xmark")
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel("Close")
            }
            .padding(CicadaTheme.spacingMD)
            ScrollView {
                ContributorDrillDown(contributor: c)
                    .padding(CicadaTheme.spacingMD)
            }
        }
        .frame(minWidth: 520, minHeight: 460)
        .background(CicadaTheme.background)
    }

    private func errorState(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(message)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.danger)
            Button("Retry") { Task { await viewModel.load() } }
                .buttonStyle(.bordered)
                .accessibilityLabel("Retry loading contributors")
        }
    }
}
