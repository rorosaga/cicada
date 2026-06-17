import SwiftUI

struct EntityDetailCard: View {
    let entity: Entity
    @Environment(GraphViewModel.self) private var graphVM
    @State private var selectedTab: DetailTab = .content
    @State private var showRawMarkdown: Bool

    enum DetailTab {
        case content, history
    }

    /// `defaultRaw` opens the card on the verbatim Source view — used by the
    /// graph's click-to-preview overlay so a node tap shows raw markdown first.
    init(entity: Entity, defaultRaw: Bool = false) {
        self.entity = entity
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
                }
            }
        }
        .frame(maxHeight: .infinity)
        .glassCard()
        .onKeyPress(.escape) {
            graphVM.clearSelection()
            return .handled
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

                // Close button
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
        HStack(spacing: CicadaTheme.spacingXL) {
            Spacer()
            TabButton(title: "Content", isSelected: selectedTab == .content) {
                selectedTab = .content
            }
            TabButton(title: "History", isSelected: selectedTab == .history) {
                selectedTab = .history
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

            if showRawMarkdown {
                rawMarkdownView
            } else {
                renderedMarkdownView
            }

            Divider().background(CicadaTheme.border)
            metadataSection
        }
        .padding(CicadaTheme.spacingLG)
    }

    private var renderedMarkdownView: some View {
        Text(renderedMarkdownAttributed(entity.markdownContent))
            .font(CicadaTheme.bodyFont)
            .textSelection(.enabled)
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
