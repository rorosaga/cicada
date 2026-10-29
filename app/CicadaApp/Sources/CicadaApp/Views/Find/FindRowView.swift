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
            if selected { hints }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        // DR-48 — the palette's rows are rows: the selected one `bgSelected`, a hovered one `bgHover` (both read
        // `bgHover` until round 2, so the ⏎ target and the pointer's row looked the same).
        .rowHover($hovered, selected: selected)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(FindRowText.accessibilityLabel(row))
        .accessibilityHint(FindRowText.primaryVerb(row.destination))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    private var titleLine: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            if row.history != nil {
                Text("Was").font(CicadaTheme.font(size: 10, weight: .semibold)).foregroundStyle(CicadaTheme.textTertiary)
            }
            Text(ExcerptText.attributed(row.title, bold: row.titleRanges))
                .font(CicadaTheme.rowFont)
                .foregroundStyle(row.history == nil ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .lineLimit(1)
            QualifierTag(qualifier: row.qualifier)   // G227: which of the pages with this name
            // DR-44 — the row's type is the one pill, `Tag` (round 3, 2026-10-20: it was a 10 pt capsule of its own in
            // the hover fill, so on a hovered row it vanished into the row).
            if let badge = row.badge { Tag(text: badge) }
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
            Text(ExcerptText.cleanAttributed(snippet, bold: row.snippetRanges))
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
        .font(CicadaTheme.font(size: 10))
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
            EntityPicture(id: id, name: name, type: type, size: 20)
        case .origin(let origin):
            OriginMark(origin: origin, size: CicadaTheme.scaled(20))
        case .savedLink(let site):
            SavedLinkMark(mark: site, size: .row)
        case .symbol(let name):
            Image(systemName: name)
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(20), height: CicadaTheme.scaled(20))
        case .still(let path):
            FindStill(path: path)
        case .blank:
            EmptyView()
        }
    }
}

/// Meaning index 2 — a video frame's own thumbnail in a palette row: the Feed's video-frame pattern (2026-09-30
/// video boards: a stored still, 16:9, `cornerRadius` 4 continuous, DR-12) at the row's mark height, loaded through
/// the app's one picture store from Cicada's own API. A real picture or nothing — no stand-in tile while it loads or
/// when it can't (#512's rule; the 2026-10-28 "a page with no picture draws none" ruling).
struct FindStill: View {
    let path: String

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                let height = CicadaTheme.scaled(20)
                Image(nsImage: image).resizable().interpolation(.high).scaledToFill()
                    .frame(width: height * 16 / 9, height: height)
                    .clipShape(CicadaTheme.shape(CicadaTheme.scaled(4)))
            } else {
                // Nothing drawn and no space taken — but a view, so the load below runs (an empty `Group` never
                // appears, and its `.task` never starts: found driving the app, 2026-10-29).
                Color.clear.frame(width: 0, height: 0)
            }
        }
        .accessibilityHidden(true)
        .task(id: "\(store?.bank ?? "")|\(path)") {
            image = await SourcePictureStore.shared.image(path: path, bank: store?.bank ?? "")
        }
    }
}
