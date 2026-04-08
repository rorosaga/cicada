import SwiftUI

struct EntityDetailCard: View {
    let entity: Entity
    @Environment(GraphViewModel.self) private var graphVM
    @State private var selectedTab: DetailTab = .content
    @State private var showRawMarkdown = false

    enum DetailTab {
        case content, history
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
            // Markdown toggle + copy
            HStack {
                Picker("", selection: $showRawMarkdown) {
                    Text("Rendered").tag(false)
                    Text("Raw").tag(true)
                }
                .pickerStyle(.segmented)
                .frame(width: 180)

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
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            let parts = parseWikilinks(entity.markdownContent)
            FlowText(parts: parts)
        }
    }

    private var rawMarkdownView: some View {
        let yaml = """
        ---
        type: \(entity.type.rawValue)
        status: \(entity.status.rawValue)
        confidence: \(entity.confidence)
        created: \(formatDate(entity.created))
        last_referenced: \(formatDate(entity.lastReferenced))
        decay_rate: \(entity.decayRate)
        version: \(entity.version)
        tags: [\(entity.tags.joined(separator: ", "))]
        related: [\(entity.related.joined(separator: ", "))]
        ---

        \(entity.markdownContent)
        """

        return Text(yaml)
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .textSelection(.enabled)
    }

    private var metadataSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if !entity.tags.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text("Tags")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    ForEach(entity.tags, id: \.self) { tag in
                        Text(tag)
                            .font(.system(size: 11))
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(CicadaTheme.surfaceHover)
                            .clipShape(Capsule())
                    }
                }
            }

            if !entity.related.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text("Related")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    ForEach(entity.related, id: \.self) { rel in
                        Text(rel)
                            .font(.system(size: 11))
                            .foregroundStyle(CicadaTheme.accent)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(CicadaTheme.accent.opacity(0.1))
                            .clipShape(Capsule())
                    }
                }
            }

            HStack(spacing: CicadaTheme.spacingLG) {
                Label(formatDate(entity.created), systemImage: "calendar")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                Label(formatDate(entity.lastReferenced), systemImage: "clock")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    // MARK: - History Tab

    private var historyTab: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(entity.history.enumerated()), id: \.element.id) { index, entry in
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    // Timeline
                    VStack(spacing: 0) {
                        Circle()
                            .fill(Color(hex: UInt32(entry.changeType.color, radix: 16) ?? 0x999999))
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
                        Text(formatDate(entry.date))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)

                        Text(entry.description)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .padding(.bottom, CicadaTheme.spacingLG)

                    Spacer()
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    // MARK: - Helpers

    private func formatDate(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "MMM d, yyyy"
        return f.string(from: date)
    }

    private func buildFullMarkdown() -> String {
        """
        ---
        type: \(entity.type.rawValue)
        status: \(entity.status.rawValue)
        confidence: \(entity.confidence)
        created: \(formatDate(entity.created))
        last_referenced: \(formatDate(entity.lastReferenced))
        decay_rate: \(entity.decayRate)
        version: \(entity.version)
        tags: [\(entity.tags.joined(separator: ", "))]
        related: [\(entity.related.joined(separator: ", "))]
        ---

        \(entity.markdownContent)
        """
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

// MARK: - Wikilink Parsing

private struct TextPart: Identifiable {
    let id = UUID()
    let text: String
    let isWikilink: Bool
}

private func parseWikilinks(_ text: String) -> [TextPart] {
    var parts: [TextPart] = []
    let pattern = "\\[\\[(.+?)\\]\\]"
    guard let regex = try? NSRegularExpression(pattern: pattern) else {
        return [TextPart(text: text, isWikilink: false)]
    }

    let nsText = text as NSString
    var lastEnd = 0

    let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
    for match in matches {
        let beforeRange = NSRange(location: lastEnd, length: match.range.location - lastEnd)
        if beforeRange.length > 0 {
            parts.append(TextPart(text: nsText.substring(with: beforeRange), isWikilink: false))
        }
        let linkRange = match.range(at: 1)
        parts.append(TextPart(text: nsText.substring(with: linkRange), isWikilink: true))
        lastEnd = match.range.location + match.range.length
    }

    if lastEnd < nsText.length {
        parts.append(TextPart(text: nsText.substring(from: lastEnd), isWikilink: false))
    }

    return parts
}

private struct FlowText: View {
    let parts: [TextPart]

    var body: some View {
        parts.reduce(Text("")) { result, part in
            if part.isWikilink {
                return result + Text(part.text)
                    .foregroundColor(CicadaTheme.accent)
                    .fontWeight(.medium)
            } else {
                return result + Text(part.text)
                    .foregroundColor(CicadaTheme.textSecondary)
            }
        }
        .font(CicadaTheme.bodyFont)
    }
}
