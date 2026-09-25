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
/// is unchanged — it lives in `ContributorDrillDown` — and it opens as the
/// page's detail column (R-DL22), not a sheet: a sheet hid the Reader its own
/// "from conversation" opens. A chip is a button that opens that column.
///
/// The four states of the old section move with it and are not dropped: error →
/// never-loaded → loaded-but-empty → content. The never-loaded branch matters
/// most — "No attributed commits yet" on a cold launch with the backend down is
/// a claim about the repo, not about the request that failed.
///
/// **Empty means no CONTRIBUTORS, never no segments.** The two are different
/// banks and only one of them has nothing to say. `git_service.get_contributors`
/// builds `entity_count` from `entities/*.md` paths alone and keeps an author
/// that touched none, so a fresh install whose only commits are `cicada`'s own
/// `State snapshot`s — or a bank whose sole author has yet to write an entity
/// page — arrives here with real attributed commits and zero segments. Branching
/// the empty sentence on `segments` printed "No attributed commits yet." over a
/// bank that has them: the same false claim about the repo the never-loaded
/// branch above exists to prevent, and the deleted `ContributorsSection`
/// branched on `contributors` precisely to avoid it. Rendering `content` with
/// no segments is what `ContributorShare.segments`' own docstring promises —
/// the bar draws its empty track (an empty `ForEach`), and
/// `ContributorSummary.sentence` supplies the true line, which for that bank is
/// its maintenance-only branch: "Cicada's own maintenance wrote this bank."
struct ContributorsStrip: View {
    /// R-DL22 — a chip opens this author as Sources' detail column.
    let onOpen: (Contributor) -> Void

    @Environment(ContributorsViewModel.self) private var viewModel

    private var segments: [ContributorShare.Segment] {
        ContributorShare.segments(viewModel.contributors)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Lists.whoWrote)
            block
        }
        // No `.task { load() }`: `ContributorsViewModel` is a thin projection
        // over `Store.contributors`, already hydrated + kept live by the
        // Store — this strip renders instantly from the snapshot on revisit.
    }

    /// D's material (R-DL19): a `bgFocus` block with the resting ring, like the tiles beside it.
    private var block: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let err = viewModel.errorMessage {
                errorState(err)
            } else if !viewModel.hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading commit trailers…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if viewModel.contributors.isEmpty {
                Text("No attributed commits yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                content
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.scaled(16))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            FlowLayout(spacing: CicadaTheme.spacingSM) {
                ForEach(Array(segments.enumerated()), id: \.element.id) { index, segment in
                    chip(segment, rank: index)
                }
                Text(Copy.Lists.shareOfEntities)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(height: CicadaTheme.scaled(28))
            }
            bar
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
    private func chip(_ segment: ContributorShare.Segment, rank: Int) -> some View {
        let label = HStack(spacing: CicadaTheme.spacingXS) {
            // The chip's key to its slice of the bar — the same rank colour (R-DL22).
            CicadaTheme.shape(CicadaTheme.scaled(2))
                .fill(Self.color(of: segment, rank: rank))
                .frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
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
        // DR-44 — a chip is not a pill: the list row's surface, hover fill only.
        .listRowSurface(height: 28, selected: false)
        .fixedSize(horizontal: true, vertical: false)

        if let c = segment.contributor {
            Button { onOpen(c) } label: { label }
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
                ForEach(Array(segments.enumerated()), id: \.element.id) { index, segment in
                    CicadaTheme.shape(2)
                        .fill(Self.color(of: segment, rank: index))
                        .frame(width: max(2, geo.size.width * segment.fraction))
                }
                Spacer(minLength: 0)
            }
            .frame(width: geo.size.width, alignment: .leading)
        }
        .frame(height: CicadaTheme.scaled(8))
        .background(CicadaTheme.bgSelected)
        .clipShape(CicadaTheme.shape(2))
        .accessibilityHidden(true)  // the chips above already speak every share
    }

    /// R-DL22 — the share is data, never the accent (DR-5) and never a provider's hue (P2): neutral text steps by rank,
    /// the folded remainder the quietest.
    private static func color(of segment: ContributorShare.Segment, rank: Int) -> Color {
        if segment.isRemainder { return CicadaTheme.bgBadge }
        switch rank {
        case 0: return CicadaTheme.textTertiary
        case 1: return CicadaTheme.textQuaternary
        default: return CicadaTheme.bgBadge
        }
    }

    /// Whole percent. `UsageFormat.percent` takes the value already scaled to
    /// 0–100 for the Codex rate-limit windows, so the share is scaled here
    /// rather than teaching that formatter a second convention.
    private static func percent(_ fraction: Double) -> String {
        UsageFormat.percent(fraction * 100)
    }

    private func errorState(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(message)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.warning)  // DR-7 — danger is for destructive actions
            NeutralButton(title: Copy.Inbox.retry, size: .compact) { Task { await viewModel.load() } }
                .accessibilityLabel("Retry loading contributors")
        }
    }
}
