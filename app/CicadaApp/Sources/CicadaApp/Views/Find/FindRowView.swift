import SwiftUI

/// One palette row (design §3.3): mark, title with the matched runs bold,
/// type capsule, one detail line, a quoted passage for a conversation, a date
/// on the right and — on the selected row — what ⏎ and ⌥⏎ will do. A
/// superseded belief reads as history (R-SU19). Rows are content: fills, never glass.
struct FindRowView: View {
    let row: FindRow
    let selected: Bool
    @State private var hovered = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            FindMarkView(mark: row.mark)
            VStack(alignment: .leading, spacing: 2) {
                titleLine
                if let detail = row.detail {
                    Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
                if let snippet = row.snippet { snippetLine(snippet) }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if let trailing = row.trailing {
                Text(trailing).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if case .settings(let section) = row.destination {
                SettingsSectionLink(section: section, label: "Open")
            }
            if selected { hints }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
            .fill(selected || hovered ? CicadaTheme.surfaceHover : Color.clear))
        .contentShape(Rectangle())
        .onHover { hovered = $0 }
        // A Settings row keeps its children: its Open link is the only thing
        // that opens the scene, and `.ignore` hid it from VoiceOver while the
        // hint promised Settings (final review, finding 2).
        .accessibilityElement(children: opensSettings ? .contain : .ignore)
        .accessibilityLabel(FindRowText.accessibilityLabel(row))
        .accessibilityHint(FindRowText.primaryVerb(row.destination))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    private var opensSettings: Bool {
        if case .settings = row.destination { return true }
        return false
    }

    private var titleLine: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            if row.history != nil {
                Text("Was").font(CicadaTheme.font(size: 10, weight: .semibold)).foregroundStyle(CicadaTheme.textTertiary)
            }
            Text(ExcerptText.attributed(row.title, bold: row.titleRanges))
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(row.history == nil ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .lineLimit(1)
            if let badge = row.badge {
                Text(badge)
                    .font(CicadaTheme.font(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingXS)
                    .background(Capsule().fill(CicadaTheme.surfaceHover))
            }
            if let history = row.history {
                Text(history).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func snippetLine(_ snippet: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
            if let speaker = row.speaker {
                Text(speaker).font(CicadaTheme.font(size: 10, weight: .semibold)).foregroundStyle(CicadaTheme.textSecondary)
            }
            Text(ExcerptText.attributed(snippet, bold: row.snippetRanges))
                .font(CicadaTheme.quoteFont(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
        }
    }

    private var hints: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("⏎ \(FindRowText.primaryVerb(row.destination))")
            if let verb = FindRowText.secondaryVerb(row.secondary) { Text("⌥⏎ \(verb)") }
        }
        .font(CicadaTheme.font(size: 10, design: .monospaced))
        .foregroundStyle(CicadaTheme.textTertiary)
        .accessibilityHidden(true)
    }
}

/// A row's mark: the entity's own logo, a service's real mark, or a symbol.
struct FindMarkView: View {
    let mark: FindMark

    var body: some View {
        switch mark {
        case .entity(let id, let name, let type):
            LogoImage(entityId: id, name: name, type: type, size: CicadaTheme.scaled(20))
        case .origin(let origin):
            OriginMark(origin: origin, size: CicadaTheme.scaled(20))
        case .symbol(let name):
            Image(systemName: name)
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(20), height: CicadaTheme.scaled(20))
        }
    }
}
