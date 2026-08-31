import SwiftUI

// M3 (backlog A2): "which model authored which belief" — repo-wide attribution
// parsed from Cicada-Author commit trailers.
/// The Contributors half of the Activity page: repo-wide model/user
/// attribution parsed from `Cicada-Author` commit trailers. No page header of
/// its own — `ActivityView` owns the title.
struct ContributorsSection: View {
    @Environment(ContributorsViewModel.self) private var viewModel

    /// At most one contributor is expanded at a time — the drill-down is tall
    /// and two open at once makes the list unreadable.
    @State private var expandedAuthor: String?

    private func toggle(_ author: String) {
        expandedAuthor = expandedAuthor == author ? nil : author
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            // Error → never-loaded → loaded-but-empty → list. Without the
            // never-loaded branch a cold launch with the backend down showed
            // "No attributed commits yet", which is a claim about the repo, not
            // about the request that failed.
            if let err = viewModel.errorMessage {
                errorState(err)
            } else if !viewModel.hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading commit trailers…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if viewModel.contributors.isEmpty {
                Text("No attributed commits yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(viewModel.contributors) { c in
                            ContributorRow(
                                contributor: c,
                                totalCommits: viewModel.totalCommits,
                                isExpanded: expandedAuthor == c.author,
                                onToggle: { toggle(c.author) }
                            )
                        }
                    }
                }
            }

            Spacer()
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        // No `.task { load() }`: `ContributorsViewModel` is a thin projection
        // over `Store.contributors`, already hydrated + kept live by the
        // Store — this tab renders instantly from the snapshot on revisit.
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

private struct ContributorRow: View {
    let contributor: Contributor
    let totalCommits: Int
    let isExpanded: Bool
    let onToggle: () -> Void

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

    // Prefer the backend-derived `kind`; fall back to the author string so the
    // row still classifies correctly against an older backend (no `kind`).
    private var kind: String {
        if let k = contributor.kind, !k.isEmpty { return k }
        if contributor.author == "user" { return "user" }
        if contributor.author == "unknown" { return "unknown" }
        return "model"
    }

    private var accent: Color {
        switch kind {
        case "user": CicadaTheme.info
        case "unknown": CicadaTheme.textTertiary
        default: ContributorAvatar.providerColor(contributor.provider)
        }
    }

    private var share: Double {
        guard totalCommits > 0 else { return 0 }
        return Double(contributor.commitCount) / Double(totalCommits)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Button(action: onToggle) { summary }
                .buttonStyle(.plain)
                .accessibilityLabel("\(contributor.author), \(contributor.commitCount) commits")

            if isExpanded { drillDown }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.surfaceHover.opacity(0.4))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .task(id: isExpanded) {
            // Re-expanding after a failure retries: `commits` is still nil.
            guard isExpanded, commits == nil else { return }
            await loadCommits()
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

    private var summary: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                ContributorAvatar(contributor: contributor, kind: kind)
                Text(contributor.author)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                Text("\(contributor.commitCount) commits")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }

            HStack(spacing: CicadaTheme.spacingMD) {
                Text("\(contributor.entityCount) entities")
                Text("\(contributor.fileCount) files")
                if !contributor.lastActive.isEmpty {
                    Text("last \(contributor.lastActive)")
                }
            }
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(CicadaTheme.border)
                        .frame(height: 4)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(accent)
                        .frame(width: geo.size.width * share, height: 4)
                }
            }
            .frame(height: 4)
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var drillDown: some View {
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
            .buttonStyle(.plain)
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
                Text("\(commit.filesChanged) files")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
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
        Text("+\(hidden) more")
            .font(.system(size: 11))
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(CicadaTheme.surfaceHover)
            .foregroundStyle(CicadaTheme.textTertiary)
            .clipShape(Capsule())
            .help("\(hidden) more entity page(s) changed in this commit")
            .accessibilityLabel("\(hidden) more entities changed, not shown")
    }

    private func entityChip(_ entityId: String, commit: ContributorCommit) -> some View {
        let key = DiffCacheKey(entityId: entityId, commitHash: commit.commitHash)
        let isOpen = openDiff == key
        return Button {
            toggleEntityDiff(key)
        } label: {
            Text(entityId)
                .font(.system(size: 11))
                .lineLimit(1)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(isOpen ? CicadaTheme.accent.opacity(0.22)
                                   : CicadaTheme.accent.opacity(0.10))
                .foregroundStyle(CicadaTheme.accent)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
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
    }
}

// G15 — a per-contributor avatar (GitHub-repo-contributors style).
//   user    -> the user's GitHub profile picture (rounded), falling back to a
//              person glyph if there's no URL or the image fails to load.
//   model   -> a provider badge: a colored circle with a 1-letter monogram
//              (provider brand-ish colors; "other" neutral). Real logo assets
//              are a follow-up; the monogram badge is the v1.
//   unknown -> a muted question-mark glyph.
private struct ContributorAvatar: View {
    let contributor: Contributor
    let kind: String

    private static let size: CGFloat = 22

    var body: some View {
        switch kind {
        case "user":
            userAvatar
        case "unknown":
            Image(systemName: "questionmark.circle.fill")
                .font(.system(size: Self.size))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: Self.size, height: Self.size)
        default:
            providerBadge
        }
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
            .font(.system(size: Self.size))
            .foregroundStyle(CicadaTheme.info)
            .frame(width: Self.size, height: Self.size)
    }

    private var providerBadge: some View {
        Circle()
            .fill(Self.providerColor(contributor.provider))
            .frame(width: Self.size, height: Self.size)
            .overlay(
                Text(Self.monogram(contributor.provider))
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(.white)
            )
    }

    /// Brand-ish color per provider; "other"/unknown -> a neutral tone.
    static func providerColor(_ provider: String?) -> Color {
        switch provider {
        case "anthropic": Color(hex: 0xD97757)  // Anthropic clay/terracotta
        case "openai": Color(hex: 0x10A37F)      // OpenAI teal-green
        case "google": Color(hex: 0x4285F4)      // Google blue
        default: CicadaTheme.textTertiary        // "other" / unknown — neutral
        }
    }

    /// 1-letter monogram per provider.
    static func monogram(_ provider: String?) -> String {
        switch provider {
        case "anthropic": "A"
        case "openai": "O"
        case "google": "G"
        default: "?"
        }
    }
}
