import SwiftUI

// M3 (backlog A2): "which model authored which belief" — repo-wide attribution
// parsed from Cicada-Author commit trailers.
/// One contributor's drill-down: the 53-week calendar of when they wrote
/// memory (G124 R14) and their recent commits, each listing the entity pages it
/// touched with a per-chip diff (G67).
///
/// R-S14 — this body, its caches and its two loaders moved **verbatim** out of
/// the old `ContributorRow` when `ContributorsSection` became
/// `ContributorsStrip`. It is one definition on purpose: the strip presents it
/// in a sheet (R-S15), and a second copy would let two surfaces disagree about
/// what an author actually wrote. The only change is the trigger — a `.task`
/// on appear, because a sheet that is on screen is already "expanded", where
/// the row keyed its fetch to `isExpanded`.
struct ContributorDrillDown: View {
    let contributor: Contributor

    // G67 — the drill-down: this author's recent commits, each listing the
    // entities it touched. Fetched once per row on first expand and kept for
    // the life of the view; `commitDiffs` caches per `DiffCacheKey`
    // (entity + commit — shared with `EntityDetailCard`'s History tab, see
    // `DiffView.swift`; this row's fetches are already scoped to a specific
    // (entityId, commitHash) pair per chip, so there's no cross-entity
    // poisoning risk to guard against here, just the same cache-key shape).
    @State private var commits: [ContributorCommit]?
    @State private var isLoadingCommits = false
    /// Set when the commits fetch FAILED. `commits` stays nil in that case, so
    /// the row can retry — a failure must never be cached as "no commits".
    @State private var commitsLoadFailed = false
    @State private var openDiff: DiffCacheKey?
    @State private var commitDiffs: [DiffCacheKey: EntityDiff] = [:]
    @State private var loadingDiffs: Set<DiffCacheKey> = []
    @State private var diffErrors: Set<DiffCacheKey> = []

    // G124 R14 — when this contributor wrote memory: one 53-week calendar
    // per `Cicada-Author`, fetched on first expand alongside the commits and
    // kept for the life of the view. A failure sets `calendarFailed` rather
    // than caching an empty grid as "never wrote anything".
    @State private var calendar: ContributorCalendar?
    @State private var calendarFailed = false
    @State private var selectedDay: CalendarDay?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            // G124 R14 — when this contributor wrote memory. The same
            // `HeatmapView` the old Usage page used, fed per author; levels
            // come from writes alone, so the tooltip and the selected-day
            // line never mention tokens or cost.
            if let calendar {
                HeatmapView(days: calendar.days, selected: $selectedDay)
                if let day = selectedDay {
                    Text("\(day.date) · \(UsageFormat.count(day.memoryWrites)) memory write\(day.memoryWrites == 1 ? "" : "s")")
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            } else if calendarFailed {
                Text("Couldn't load this contributor's calendar")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            commitsDrillDown
        }
        .task {
            // Re-presenting after a failure retries: `commits` (or `calendar`)
            // is still nil. The two fetches are independent, so one failing
            // never blocks the other from rendering.
            if commits == nil { await loadCommits() }
            if calendar == nil { await loadCalendar() }
        }
    }

    /// G124 R14 — this author's memory-write calendar. Same cancellation
    /// rule as `loadCommits`: a collapsed row mid-flight is neither a failure
    /// nor a result, so re-expanding simply fetches again.
    private func loadCalendar() async {
        calendarFailed = false
        do {
            calendar = try await APIClient.shared.fetchContributorCalendar(author: contributor.author)
        } catch {
            guard !Self.isCancellation(error) else { return }
            calendarFailed = true
        }
    }

    /// Fetch this author's commits. A failure leaves `commits` nil and raises
    /// `commitsLoadFailed`, so the drill-down shows a retry affordance instead
    /// of the "No commits found for this author" empty state. A CANCELLED
    /// fetch (the row was collapsed while the request was in flight) is neither
    /// — it clears both flags so re-expanding simply fetches again.
    private func loadCommits() async {
        guard !isLoadingCommits else { return }
        isLoadingCommits = true
        commitsLoadFailed = false
        defer { isLoadingCommits = false }
        do {
            commits = try await APIClient.shared.fetchContributorCommits(
                author: contributor.author
            )
        } catch {
            guard !Self.isCancellation(error) else { return }
            commitsLoadFailed = true
        }
    }

    /// URLSession surfaces a cancelled request as `URLError.cancelled`, not as
    /// `CancellationError`, so both have to be recognised.
    private static func isCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        if let urlError = error as? URLError, urlError.code == .cancelled { return true }
        return false
    }

    @ViewBuilder
    private var commitsDrillDown: some View {
        if isLoadingCommits {
            HStack(spacing: CicadaTheme.spacingXS) {
                ProgressView().controlSize(.small)
                Text("Loading commits…")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        } else if commitsLoadFailed {
            // NOT the empty state: the fetch failed, so we don't know whether
            // this author has commits. Same shape as `DiffView.error`.
            Button { Task { await loadCommits() } } label: {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(CicadaTheme.diffRemoved)
                    Text("Couldn't load these commits — tap to retry")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel("Retry loading commits for \(contributor.author)")
        } else if let commits, commits.isEmpty {
            Text("No commits found for this author.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        } else if let commits {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(commits) { commit in
                    commitRow(commit)
                }
            }
            .padding(.leading, CicadaTheme.spacingMD)
        }
    }

    private func commitRow(_ commit: ContributorCommit) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(commit.date)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                Text(commit.subject)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                Spacer()
                Text("\(UsageFormat.count(commit.filesChanged)) files")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                FromConversationButton(sessionIds: commit.sessions)
            }

            if commit.entities.isEmpty {
                Text("No entity pages changed in this commit.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                FlowLayout(spacing: 6) {
                    ForEach(commit.entities, id: \.self) { entityId in
                        entityChip(entityId, commit: commit)
                    }
                    // The backend caps the chips it sends (a Sleep cycle can
                    // touch 900 pages). Say so rather than under-report; the
                    // capsule is deliberately NOT a button — there is no id
                    // behind it to diff.
                    if commit.hiddenEntityCount > 0 {
                        moreEntitiesCapsule(commit.hiddenEntityCount)
                    }
                }
            }

            if let key = openDiff, key.commitHash == commit.commitHash {
                if let diff = commitDiffs[key] {
                    DiffView(diff: diff)
                } else if loadingDiffs.contains(key) {
                    DiffView.loading
                } else if diffErrors.contains(key) {
                    DiffView.error { fetchEntityDiff(key) }
                } else {
                    DiffView.empty
                }
            }
        }
        .padding(CicadaTheme.spacingSM)
        .background(CicadaTheme.surface.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    /// "+N more" — a non-interactive sibling of `entityChip`, styled as muted
    /// so it doesn't read as a tappable entity.
    private func moreEntitiesCapsule(_ hidden: Int) -> some View {
        Text("+\(UsageFormat.count(hidden)) more")
            .font(CicadaTheme.font(size: 11))
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(CicadaTheme.surfaceHover)
            .foregroundStyle(CicadaTheme.textTertiary)
            .clipShape(Capsule())
            .help("\(UsageFormat.count(hidden)) more entity page(s) changed in this commit")
            .accessibilityLabel("\(hidden) more entities changed, not shown")
    }

    private func entityChip(_ entityId: String, commit: ContributorCommit) -> some View {
        let key = DiffCacheKey(entityId: entityId, commitHash: commit.commitHash)
        let isOpen = openDiff == key
        return Button {
            toggleEntityDiff(key)
        } label: {
            Text(entityId)
                .font(CicadaTheme.font(size: 11))
                .lineLimit(1)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(isOpen ? CicadaTheme.accent.opacity(0.22)
                                   : CicadaTheme.accent.opacity(0.10))
                .foregroundStyle(CicadaTheme.accent)
                .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .help("Show what changed on \(entityId) in this commit")
    }

    private func toggleEntityDiff(_ key: DiffCacheKey) {
        if openDiff == key {
            openDiff = nil
            return
        }
        openDiff = key
        guard commitDiffs[key] == nil, !loadingDiffs.contains(key) else { return }
        fetchEntityDiff(key)
    }

    /// Fetches (or retries) one (entity, commit) chip's diff.
    private func fetchEntityDiff(_ key: DiffCacheKey) {
        diffErrors.remove(key)
        loadingDiffs.insert(key)
        Task {
            do {
                let diff = try await APIClient.shared.fetchEntityCommitDiff(
                    id: key.entityId, commitHash: key.commitHash
                )
                loadingDiffs.remove(key)
                commitDiffs[key] = diff
            } catch {
                loadingDiffs.remove(key)
                diffErrors.insert(key)
            }
        }
    }}

// G15 — a per-contributor avatar (GitHub-repo-contributors style).
//   user    -> the user's GitHub profile picture (rounded), falling back to a
//              person glyph if there's no URL or the image fails to load.
//   system  -> the bookworm itself (Track L R8): Cicada's own maintenance
//              commits are neither a model nor a person, and drawing them as
//              an unknown model was the loudest instance of the "?" bug.
//   model   -> the provider's REAL mark when one is bundled (R-L6), else a
//              coloured circle carrying the author's initials. The "logo
//              assets are a follow-up" note this comment used to carry is
//              what Track L delivered.
//   unknown -> a muted question-mark glyph — the ONE place a "?" is honest,
//              because a legacy untrailered commit genuinely has no author.
//
// R-S14 — internal, not `private`: the chip strip reuses this exact view
// rather than re-deriving a mark, so a chip and its drill-down can never wear
// two different faces for one author.
struct ContributorAvatar: View {
    let contributor: Contributor
    let kind: String

    private static let size: CGFloat = 22

    var body: some View {
        switch kind {
        case "user":
            userAvatar
        case "system":
            systemAvatar
        case "unknown":
            Image(systemName: "questionmark.circle.fill")
                .font(CicadaTheme.font(size: Self.size))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: Self.size, height: Self.size)
        default:
            providerBadge
        }
    }

    /// A STATIC frame 0 of the bookworm, not a `BookwormView` (R8): a 22 pt
    /// sprite animating inside a scrolling table is motion nobody asked for,
    /// and frame 0 at this size is a `BookwormRenderer` cache hit the menu bar
    /// has usually already paid for. `.interpolation(.none)` keeps the pixel
    /// grid hard at a non-multiple scale, exactly as the menu bar draws it.
    private var systemAvatar: some View {
        Image(nsImage: BookwormRenderer.cachedImage(state: .happy, frameIndex: 0, pointSize: 24))
            .interpolation(.none)
            .resizable()
            .frame(width: Self.size, height: Self.size)
            .clipShape(Circle())
    }

    @ViewBuilder
    private var userAvatar: some View {
        if let urlStr = contributor.avatarUrl, let url = URL(string: urlStr) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .empty:
                    ProgressView().scaleEffect(0.5)
                default:
                    userFallback
                }
            }
            .frame(width: Self.size, height: Self.size)
            .clipShape(Circle())
        } else {
            userFallback
        }
    }

    private var userFallback: some View {
        Image(systemName: "person.crop.circle.fill")
            .font(CicadaTheme.font(size: Self.size))
            .foregroundStyle(CicadaTheme.info)
            .frame(width: Self.size, height: Self.size)
    }

    /// R8 — the real mark when the provider ships one, else the provider's
    /// colour carrying the AUTHOR's initials. Initials, not a per-provider
    /// letter: `openrouter/z-ai/glm-5.2` and a bare `glm-5.2` are two
    /// different authors and must not collapse into one badge.
    @ViewBuilder
    private var providerBadge: some View {
        if let logo = ContributorIdentity.logoName(provider: contributor.provider) {
            LogoImage(name: logo, size: Self.size)
        } else {
            Circle()
                .fill(Self.providerColor(contributor.provider))
                .frame(width: Self.size, height: Self.size)
                .overlay(
                    Text(ContributorIdentity.monogram(for: contributor.author))
                        .font(CicadaTheme.font(size: 10, weight: .bold))
                        .foregroundStyle(.white)
                )
        }
    }

    /// Brand-ish color per provider; "other"/unknown -> a neutral tone.
    ///
    /// The R-L6 providers that have no bundled mark deliberately stay neutral:
    /// a router (`openrouter`, `ollama`) did not make the model, and painting
    /// an open-weight family in a vendor's colour would claim a brand the id
    /// does not carry. Colour here means "we know whose model this was", and
    /// the initials carry the rest. Still used by `ContributorsStrip`, which
    /// tints each bar segment and its chip by the same rule (R-S6).
    static func providerColor(_ provider: String?) -> Color {
        switch provider {
        case "anthropic": Color(hex: 0xD97757)  // Anthropic clay/terracotta
        case "openai": Color(hex: 0x10A37F)      // OpenAI teal-green
        case "google": Color(hex: 0x4285F4)      // Google blue
        default: CicadaTheme.textTertiary        // router / open-weight / "other" — neutral
        }
    }
}
