import SwiftUI

struct EntityDetailCard: View {
    let entity: Entity
    @Environment(GraphViewModel.self) private var graphVM
    @State private var selectedTab: DetailTab = .content
    @State private var showRawMarkdown: Bool

    // Claim-layer state (§3b perspectives, §4 timeline). Loaded lazily on tab
    // open. Includes superseded claims so the timeline tab can list contested
    // keys; the perspective tab filters to valid claims itself.
    @State private var claims: [Claim] = []
    @State private var claimsLoaded = false
    @State private var timelineKey: TimelineKey?

    // Location listing (issue #7). Loaded lazily on appear for `.location`
    // entities; nil while loading or when no path/endpoint is available.
    @State private var locationListing: LocationListing?

    struct TimelineKey: Identifiable, Hashable {
        let predicate: String
        let context: String
        var id: String { "\(predicate)|\(context)" }
    }

    enum DetailTab {
        case content, history, perspectives, timeline
    }

    /// Whether to show the card's own close (✕) button. The Clusters detail
    /// embeds this card inside a view that already provides a Back button, so
    /// it passes `false` — the card's ✕ only drives `graphVM.clearSelection()`,
    /// which is a no-op (dead button) outside the graph's selection context.
    let showsCloseButton: Bool

    /// `defaultRaw` opens the card on the verbatim Source view — used by the
    /// graph's click-to-preview overlay so a node tap shows raw markdown first.
    init(entity: Entity, defaultRaw: Bool = false, showsCloseButton: Bool = true) {
        self.entity = entity
        self.showsCloseButton = showsCloseButton
        _showRawMarkdown = State(initialValue: defaultRaw)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            tabSwitcher
            Divider().background(CicadaTheme.border)

            ScrollView {
                switch selectedTab {
                case .content: contentTab
                case .history: historyTab
                case .perspectives: perspectivesTab
                case .timeline: timelineTab
                }
            }
        }
        .frame(maxHeight: .infinity)
        .glassCard()
        .onKeyPress(.escape) {
            graphVM.clearSelection()
            return .handled
        }
        .sheet(item: $timelineKey) { key in
            beliefTimelineSheet(key)
        }
    }

    // MARK: - Header

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack {
                // Type badge
                Label(entity.type.label, systemImage: entity.type.icon)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(CicadaTheme.entityColor(for: entity.type))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(CicadaTheme.entityColor(for: entity.type).opacity(0.15))
                    .clipShape(Capsule())

                // Status badge
                Text(entity.status.label)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(CicadaTheme.statusColor(for: entity.status))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(CicadaTheme.statusColor(for: entity.status).opacity(0.15))
                    .clipShape(Capsule())

                Spacer()

                // Close button — only when this card owns dismissal (graph
                // overlay). Suppressed in Clusters, which has its own Back button.
                if showsCloseButton {
                    Button {
                        graphVM.clearSelection()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .frame(width: 28, height: 28)
                            .background(CicadaTheme.surfaceHover)
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                }
            }

            Text(entity.name)
                .font(CicadaTheme.titleFont)
                .foregroundStyle(CicadaTheme.textPrimary)

            // Confidence bar
            HStack(spacing: CicadaTheme.spacingSM) {
                Text("Confidence")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(CicadaTheme.border)
                            .frame(height: 4)

                        RoundedRectangle(cornerRadius: 2)
                            .fill(CicadaTheme.statusColor(for: entity.status))
                            .frame(width: geo.size.width * entity.confidence, height: 4)
                    }
                }
                .frame(height: 4)

                Text(String(format: "%.0f%%", entity.confidence * 100))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 36, alignment: .trailing)
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    // MARK: - Tab Switcher

    private var tabSwitcher: some View {
        HStack(spacing: CicadaTheme.spacingLG) {
            Spacer()
            TabButton(title: "Content", isSelected: selectedTab == .content) {
                selectedTab = .content
            }
            TabButton(title: "History", isSelected: selectedTab == .history) {
                selectedTab = .history
            }
            TabButton(title: "Perspectives", isSelected: selectedTab == .perspectives) {
                selectedTab = .perspectives
                Task { await loadClaimsIfNeeded() }
            }
            TabButton(title: "Timeline", isSelected: selectedTab == .timeline) {
                selectedTab = .timeline
                Task { await loadClaimsIfNeeded() }
            }
            Spacer()
        }
        .padding(.horizontal, CicadaTheme.spacingLG)
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    // MARK: - Content Tab

    private var contentTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            // Rendered/Source toggle + copy
            HStack(spacing: CicadaTheme.spacingXS) {
                ViewModeButton(title: "Rendered", icon: "eye", isSelected: !showRawMarkdown) {
                    showRawMarkdown = false
                }
                ViewModeButton(title: "Source", icon: "chevron.left.forwardslash.chevron.right", isSelected: showRawMarkdown) {
                    showRawMarkdown = true
                }

                Spacer()

                Button {
                    let fullMarkdown = buildFullMarkdown()
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(fullMarkdown, forType: .string)
                } label: {
                    Image(systemName: "doc.on.doc")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .buttonStyle(.plain)
                .help("Copy markdown")
            }

            // G11: rich media preview above the body for `media`-type entities.
            if entity.type == .media, let media = entity.media, media.hasURL {
                MediaPreview(model: MediaPreviewModel(
                    block: media,
                    title: entity.name,
                    description: mediaDescription
                ))
                Divider().background(CicadaTheme.border)
            }

            if showRawMarkdown {
                rawMarkdownView
            } else {
                renderedMarkdownView
            }

            if entity.type == .location {
                Divider().background(CicadaTheme.border)
                locationSection
            }

            Divider().background(CicadaTheme.border)
            metadataSection
        }
        .padding(CicadaTheme.spacingLG)
        .task(id: entity.id) {
            // Reset before (re)fetching so swapping between entities can't show
            // a previous location's listing. `.task(id:)` already guarantees this
            // runs once per id, so no extra "loaded" guard is needed.
            locationListing = nil
            // Only location entities have a directory listing to fetch.
            guard entity.type == .location else { return }
            locationListing = try? await APIClient.shared.fetchLocationListing(id: entity.id)
        }
    }

    // MARK: - Location Section (issue #7)
    //
    // For `.location` entities, shows the declared directory path (monospace,
    // copyable) and a bounded listing of its immediate children. Degrades
    // quietly: no path / inaccessible / endpoint absent → renders nothing.

    @ViewBuilder
    private var locationSection: some View {
        // Prefer the listing's path (authoritative), falling back to the
        // entity's own `path` field if surfaced on the EntityResponse.
        let path = locationListing?.path ?? entity.path
        if let path, !path.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "folder")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.entityColor(for: .location))
                    Text("Path")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(path, forType: .string)
                    } label: {
                        Image(systemName: "doc.on.doc")
                            .font(.system(size: 11))
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .buttonStyle(.plain)
                    .help("Copy path")
                }

                Text(path)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceHover.opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))

                locationContents
            }
        }
    }

    @ViewBuilder
    private var locationContents: some View {
        if let listing = locationListing {
            if !listing.exists {
                locationNote("Directory not found.", icon: "questionmark.folder")
            } else if !listing.accessible {
                locationNote("Permission denied — can't list this directory.",
                             icon: "lock")
            } else if listing.entries.isEmpty {
                locationNote("Empty directory.", icon: "tray")
            } else {
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(listing.entries) { entry in
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: entry.isDir ? "folder.fill" : "doc")
                                .font(.system(size: 11))
                                .foregroundStyle(entry.isDir
                                                 ? CicadaTheme.entityColor(for: .location)
                                                 : CicadaTheme.textTertiary)
                                .frame(width: 16)
                            Text(entry.name)
                                .font(.system(size: 12))
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                            Spacer()
                            if !entry.isDir {
                                Text(humanSize(entry.size))
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                    if listing.truncated {
                        Text("…listing truncated")
                            .font(.system(size: 10))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.top, 2)
                    }
                }
            }
        }
    }

    private func locationNote(_ text: String, icon: String) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: icon)
                .font(.system(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(text)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// Human-readable byte size (e.g. "12 KB"). Dirs pass 0 and aren't shown.
    private func humanSize(_ bytes: Int) -> String {
        let units = ["B", "KB", "MB", "GB", "TB"]
        var value = Double(bytes)
        var unit = 0
        while value >= 1024, unit < units.count - 1 {
            value /= 1024
            unit += 1
        }
        return unit == 0
            ? "\(bytes) \(units[unit])"
            : String(format: "%.1f %@", value, units[unit])
    }

    /// The `## Description` body section of a media entity, used as the website
    /// preview card's description line. Falls back to `## Summary`. Returns nil
    /// when neither is present.
    private var mediaDescription: String? {
        for header in ["## Description", "## Summary"] {
            if let text = section(named: header, in: entity.markdownContent), !text.isEmpty {
                return text
            }
        }
        return nil
    }

    /// Extract the text under a `## Header` up to the next `## ` header (or EOF).
    private func section(named header: String, in markdown: String) -> String? {
        let lines = markdown.components(separatedBy: "\n")
        guard let start = lines.firstIndex(where: {
            $0.trimmingCharacters(in: .whitespaces) == header
        }) else { return nil }
        var body: [String] = []
        for line in lines[(start + 1)...] {
            if line.trimmingCharacters(in: .whitespaces).hasPrefix("## ") { break }
            body.append(line)
        }
        let text = body.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    private var renderedMarkdownView: some View {
        // Inline transclusion (§1): tokenize the body into text/embed segments
        // and render `![[…]]` embeds as nested collapsible cards. Falls back to
        // plain wikilink rendering for bodies with no embeds.
        TranscludingMarkdownView(body: entity.markdownContent)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var rawMarkdownView: some View {
        // Prefer the verbatim file from the API (transparency: this is the
        // exact markdown on disk, frontmatter included). The reconstruction
        // below only covers placeholder entities that haven't fully loaded.
        let source = entity.rawMarkdown.isEmpty ? buildFullMarkdown() : entity.rawMarkdown

        return Text(source)
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.surfaceHover.opacity(0.5))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private var metadataSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if !entity.tags.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text("Tags")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    FlowLayout(spacing: 6) {
                        ForEach(entity.tags, id: \.self) { tag in
                            Text(tag)
                                .font(.system(size: 11))
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(CicadaTheme.surfaceHover)
                                .clipShape(Capsule())
                        }
                    }
                }
            }

            if !entity.related.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text("Related")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    FlowLayout(spacing: 6) {
                        ForEach(entity.related, id: \.self) { rel in
                            Text(rel)
                                .font(.system(size: 11))
                                .foregroundStyle(CicadaTheme.accent)
                                .lineLimit(1)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(CicadaTheme.accent.opacity(0.1))
                                .clipShape(Capsule())
                        }
                    }
                }
            }

            HStack(spacing: CicadaTheme.spacingLG) {
                Label(entity.created, systemImage: "calendar")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                Label(entity.lastReferenced, systemImage: "clock")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    // MARK: - History Tab

    private var historyTab: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(entity.history.reversed().enumerated()), id: \.element.id) { index, entry in
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    // Timeline
                    VStack(spacing: 0) {
                        Circle()
                            .fill(index == 0
                                  ? Color(hex: 0x22C55E)
                                  : Color(hex: UInt32(entry.changeType.color, radix: 16) ?? 0x999999))
                            .frame(width: 10, height: 10)

                        if index < entity.history.count - 1 {
                            Rectangle()
                                .fill(CicadaTheme.border)
                                .frame(width: 1)
                                .frame(maxHeight: .infinity)
                        }
                    }
                    .frame(width: 10)

                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        HStack(spacing: CicadaTheme.spacingXS) {
                            Text(entry.date)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                            // M3 (backlog A2): who authored this commit.
                            // NOT BUILD-VERIFIED — needs Xcode compile.
                            if !entry.author.isEmpty {
                                Text(entry.author)
                                    .font(CicadaTheme.captionFont)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 1)
                                    .background(
                                        (entry.author == "user"
                                         ? Color(hex: 0x3B82F6)
                                         : Color(hex: 0x8B5CF6)).opacity(0.18)
                                    )
                                    .clipShape(Capsule())
                                    .foregroundStyle(entry.author == "user"
                                                     ? Color(hex: 0x3B82F6)
                                                     : Color(hex: 0x8B5CF6))
                            }
                        }

                        Text(entry.description)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)

                        // Inline per-commit diff when present (history fetched
                        // with includeDiff=true). NOT BUILD-VERIFIED.
                        if let diff = entry.diff,
                           !(diff.added.isEmpty && diff.removed.isEmpty) {
                            VStack(alignment: .leading, spacing: 1) {
                                ForEach(Array(diff.removed.split(separator: "\n").enumerated()), id: \.offset) { _, line in
                                    Text("- \(line)")
                                        .font(CicadaTheme.monoFont)
                                        .foregroundStyle(Color(hex: 0xEF4444))
                                }
                                ForEach(Array(diff.added.split(separator: "\n").enumerated()), id: \.offset) { _, line in
                                    Text("+ \(line)")
                                        .font(CicadaTheme.monoFont)
                                        .foregroundStyle(Color(hex: 0x22C55E))
                                }
                            }
                            .padding(CicadaTheme.spacingXS)
                            .background(CicadaTheme.border.opacity(0.25))
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                        }
                    }
                    .padding(.bottom, CicadaTheme.spacingLG)

                    Spacer()
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    // MARK: - Perspectives Tab (§3b)
    //
    // The subject's claims grouped by observer, each group a labeled section
    // (Observer.label + sfSymbol badge) of claim chips. Where two observers
    // disagree on the same (predicate, context), a divergence callout names the
    // "who believes what" contradiction-across-observers.

    private var perspectivesTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if !claimsLoaded {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .center)
            } else if validClaims.isEmpty {
                claimsEmptyState
            } else {
                ForEach(divergences, id: \.self) { d in
                    divergenceCallout(d)
                }
                ForEach(observerGroups, id: \.0.id) { observer, group in
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        HStack(spacing: CicadaTheme.spacingXS) {
                            ObserverBadge(observer)
                            Text("\(group.count)")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        ForEach(group) { claim in
                            ClaimChip(claim: claim, onOpenTimeline: {
                                timelineKey = TimelineKey(predicate: claim.predicate, context: claim.context)
                            })
                        }
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    // MARK: - Timeline Tab (§4)
    //
    // Lists the subject's CONTESTED keys — any (predicate, context) with ≥2
    // claims over time — and drills into BeliefTimelineView on tap.

    private var timelineTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if !claimsLoaded {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .center)
            } else if contestedKeys.isEmpty {
                VStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "clock.badge.questionmark")
                        .font(.system(size: 24))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text("No contested beliefs yet.")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text("A belief becomes contested when a (predicate, context) has changed over time.")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, CicadaTheme.spacingXL)
            } else {
                Text("Contested beliefs")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                ForEach(contestedKeys, id: \.id) { key in
                    Button {
                        timelineKey = key
                    } label: {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: "clock.arrow.circlepath")
                                .font(.system(size: 12))
                                .foregroundStyle(CicadaTheme.accent)
                            Text(key.predicate)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                            ContextPill(key.context)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.system(size: 10))
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        .padding(CicadaTheme.spacingMD)
                        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    private func beliefTimelineSheet(_ key: TimelineKey) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Spacer()
                Button { timelineKey = nil } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
                .padding(CicadaTheme.spacingMD)
            }
            ScrollView {
                BeliefTimelineView(subject: entity.id, predicate: key.predicate, context: key.context)
            }
        }
        .frame(minWidth: 460, minHeight: 420)
        .background(CicadaTheme.background)
    }

    private var claimsEmptyState: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "person.2.slash")
                .font(.system(size: 24))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text("No claims for this subject yet.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingXL)
    }

    private func divergenceCallout(_ d: Divergence) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.bubble.fill")
                    .font(.system(size: 11))
                    .foregroundStyle(Color(hex: 0xF59E0B))
                Text("Observers disagree on \(d.predicate)")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                ContextPill(d.context)
            }
            ForEach(Array(d.byObserver.enumerated()), id: \.offset) { _, pair in
                HStack(spacing: 4) {
                    ObserverBadge(pair.0)
                    Text("asserts")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text(pair.1)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .background(Color(hex: 0xF59E0B).opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(Color(hex: 0xF59E0B).opacity(0.3), lineWidth: 1)
        )
    }

    // MARK: - Claim derivations

    private var validClaims: [Claim] { claims.filter { $0.isValid } }

    /// Valid claims grouped by observer, observer order stable (agent, rodrigo,
    /// then externals).
    private var observerGroups: [(Observer, [Claim])] {
        let grouped = Dictionary(grouping: validClaims, by: { $0.observer })
        return grouped.sorted { observerRank($0.key) < observerRank($1.key) }
            .map { ($0.key, $0.value) }
    }

    private func observerRank(_ o: Observer) -> Int {
        switch o {
        case .agent: return 0
        case .rodrigo: return 1
        case .external: return 2
        }
    }

    struct Divergence: Hashable {
        let predicate: String
        let context: String
        let byObserver: [(Observer, String)]
        static func == (l: Divergence, r: Divergence) -> Bool {
            l.predicate == r.predicate && l.context == r.context
        }
        func hash(into h: inout Hasher) { h.combine(predicate); h.combine(context) }
    }

    /// (predicate, context) keys where ≥2 distinct observers assert different
    /// objects among the currently-valid claims.
    private var divergences: [Divergence] {
        let byKey = Dictionary(grouping: validClaims, by: { "\($0.predicate)|\($0.context)" })
        var out: [Divergence] = []
        for (_, group) in byKey {
            let distinctObservers = Set(group.map { $0.observer })
            let distinctObjects = Set(group.map { $0.object })
            if distinctObservers.count >= 2 && distinctObjects.count >= 2, let first = group.first {
                let pairs = group.map { ($0.observer, $0.object) }
                out.append(Divergence(predicate: first.predicate, context: first.context, byObserver: pairs))
            }
        }
        return out
    }

    /// (predicate, context) keys with ≥2 claims over time (valid + superseded).
    private var contestedKeys: [TimelineKey] {
        let byKey = Dictionary(grouping: claims, by: { TimelineKey(predicate: $0.predicate, context: $0.context) })
        return byKey.filter { $0.value.count >= 2 }.keys.sorted { $0.id < $1.id }
    }

    private func loadClaimsIfNeeded() async {
        guard !claimsLoaded else { return }
        // Include superseded so the timeline tab can detect contested keys.
        claims = (try? await APIClient.shared.fetchClaims(subject: entity.id, includeSuperseded: true)) ?? []
        claimsLoaded = true
    }

    // MARK: - Helpers

    private func buildFullMarkdown() -> String {
        // The API's verbatim file wins; the reconstruction is a fallback for
        // placeholder entities that haven't fully loaded yet.
        if !entity.rawMarkdown.isEmpty { return entity.rawMarkdown }
        return """
        ---
        type: \(entity.type.rawValue)
        status: \(entity.status.rawValue)
        confidence: \(entity.confidence)
        created: \(entity.created)
        last_referenced: \(entity.lastReferenced)
        decay_rate: \(entity.decayRate)
        version: \(entity.version)
        tags: [\(entity.tags.joined(separator: ", "))]
        related: [\(entity.related.joined(separator: ", "))]
        ---

        \(entity.markdownContent)
        """
    }
}

// MARK: - View Mode Button (Rendered / Source)

private struct ViewModeButton: View {
    let title: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 10, weight: .medium))
                Text(title)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(isSelected ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(isSelected ? CicadaTheme.surfaceHover : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 4))
        }
        .buttonStyle(.plain)
        .help("\(title) view")
    }
}

// MARK: - Tab Button

private struct TabButton: View {
    let title: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Text(title)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(isSelected ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                Rectangle()
                    .fill(isSelected ? CicadaTheme.accent : .clear)
                    .frame(height: 2)
            }
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Flow Layout

/// A simple wrapping horizontal layout: items flow left-to-right and wrap to
/// the next line when the available width is exhausted. Used for tag/related
/// pills so large sets wrap naturally instead of overflowing the card.
private struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = layout(subviews: subviews, in: proposal.width ?? .infinity)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let positions = layout(subviews: subviews, in: bounds.width)
        for (index, subview) in subviews.enumerated() {
            let pt = positions.points[index]
            subview.place(at: CGPoint(x: bounds.minX + pt.x, y: bounds.minY + pt.y), proposal: .unspecified)
        }
    }

    private func layout(subviews: Subviews, in maxWidth: CGFloat) -> (size: CGSize, points: [CGPoint]) {
        var points: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalWidth: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            points.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            totalWidth = max(totalWidth, x - spacing)
        }
        return (CGSize(width: totalWidth, height: y + rowHeight), points)
    }
}

// MARK: - Wikilink Rendering

/// Parse `[[Wikilinks]]` into an `AttributedString` where the link text is
/// highlighted in the accent color and the surrounding body uses the
/// secondary text color.
private func renderedMarkdownAttributed(_ text: String) -> AttributedString {
    var result = AttributedString()

    guard let regex = try? NSRegularExpression(pattern: "\\[\\[(.+?)\\]\\]") else {
        var plain = AttributedString(text)
        plain.foregroundColor = CicadaTheme.textSecondary
        return plain
    }

    let nsText = text as NSString
    var lastEnd = 0

    let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
    for match in matches {
        let beforeRange = NSRange(location: lastEnd, length: match.range.location - lastEnd)
        if beforeRange.length > 0 {
            var plain = AttributedString(nsText.substring(with: beforeRange))
            plain.foregroundColor = CicadaTheme.textSecondary
            result.append(plain)
        }

        let linkRange = match.range(at: 1)
        var link = AttributedString(nsText.substring(with: linkRange))
        link.foregroundColor = CicadaTheme.accent
        link.font = CicadaTheme.bodyFont.weight(.medium)
        result.append(link)

        lastEnd = match.range.location + match.range.length
    }

    if lastEnd < nsText.length {
        var plain = AttributedString(nsText.substring(from: lastEnd))
        plain.foregroundColor = CicadaTheme.textSecondary
        result.append(plain)
    }

    return result
}
