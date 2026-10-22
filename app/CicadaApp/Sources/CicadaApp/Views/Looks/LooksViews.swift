import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Design taste (owner, 2026-10-14) — the views a look is drawn with. The Looks page went on 2026-10-20 (owner: "this
/// should be ingrained in the markdown of a specific thing"): a look now lives on the page of the thing it shows, and
/// the entity card draws it (`PageLooks.swift`) with these — the tile, the colour strip, the detail (what was liked, the
/// colours with their share, the type, the snippets, where it came from) and the drop intake. The app shrinks a
/// capture before it leaves (`DesignImageShrink`) and posts bytes; the server reads the colours, keeps the picture in
/// the bank and embeds it (`api/routers/design.py`) — nothing here decodes or ranks.

/// A tile's picture from Cicada's own API (`/design/{id}/image?v=…`), its colours standing in while it loads.
struct LooksStoredImage: View {
    let ref: DesignRefSummary

    var body: some View {
        StoredPreview(path: ref.image?.url) { LooksPaletteField(colours: ref.palette) }
    }
}

/// One look as a tile: the screenshot, its name, its colours as one strip, the site and the day. A click on the
/// screenshot or its name opens the look.
struct LooksTile: View {
    let ref: DesignRefSummary
    let selected: Bool
    let image: AnyView
    var onEnlarge: (CGRect) -> Void = { _ in }
    var onImageFrame: (CGRect) -> Void = { _ in }
    let action: () -> Void
    @State private var hovering = false
    @State private var imageFrame: CGRect = .zero

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Button { onEnlarge(imageFrame) } label: {
                image
                    .frame(maxWidth: .infinity)
                    .aspectRatio(16.0 / 10.0, contentMode: .fit)
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .looksZoomSource { frame in imageFrame = frame; onImageFrame(frame) }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.Looks.enlarge)
            .accessibilityLabel(Copy.Looks.enlarge)
            Button(action: action) {
                caption
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(ref.displayName)
        }
        .padding(CicadaTheme.spacingSM)
        .rowHover($hovering, selected: selected, cornerRadius: CicadaTheme.cornerRadius)
    }

    private var caption: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(ref.displayName)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                HStack(spacing: CicadaTheme.spacingSM) {
                    LooksPaletteStrip(colours: ref.palette)
                        .frame(width: CicadaTheme.scaled(64), height: CicadaTheme.scaled(6))
                    Text([ref.site ?? "", LooksDay.words(ref.day)].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }
}

/// The colours as one strip, no labels (the detail column names them). Looks v2: the ground takes half, and the
/// colours after it share the rest equally in their salience order — by area, a thin cobalt ink that *is* the look
/// drew as a hairline beside 90 % off-white.
struct LooksPaletteStrip: View {
    let colours: [DesignColour]

    var body: some View {
        GeometryReader { geo in
            let widths = LooksPaletteStrip.widths(colours, total: geo.size.width)
            HStack(spacing: 0) {
                ForEach(Array(colours.enumerated()), id: \.offset) { i, c in
                    Rectangle().fill(LooksColour.color(c.hex)).frame(width: widths[i])
                }
            }
        }
        .clipShape(Capsule())
        .overlay(Capsule().strokeBorder(CicadaTheme.border, lineWidth: 1))
        .accessibilityHidden(true)
    }

    /// Each colour's width: the first (the ground) half, the rest equal; one colour fills the strip.
    nonisolated static func widths(_ colours: [DesignColour], total: CGFloat) -> [CGFloat] {
        guard colours.count > 1 else { return colours.map { _ in total } }
        let rest = total / 2 / CGFloat(colours.count - 1)
        return [total / 2] + Array(repeating: rest, count: colours.count - 1)
    }
}

/// While a picture loads (or when none is here): its own colours as soft vertical bands — data, never painted art.
struct LooksPaletteField: View {
    let colours: [DesignColour]

    var body: some View {
        if colours.isEmpty {
            CicadaTheme.bgPane
        } else {
            LinearGradient(colors: colours.prefix(4).map { LooksColour.color($0.hex) }, startPoint: .top,
                           endPoint: .bottom)
        }
    }
}

enum LooksColour {
    /// `#rrggbb` → a colour; anything else is the pane (a hand-edited palette never crashes a tile).
    static func color(_ hex: String) -> Color {
        let raw = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        guard raw.count == 6, let value = UInt32(raw, radix: 16) else { return CicadaTheme.bgPane }
        return Color(hex: value)
    }
}

/// One look in full (opened large from a page, `PageLookSheet`).
struct LooksDetailColumn: View {
    let summary: DesignRefSummary
    let detail: DesignRef?
    let image: AnyView
    /// "‹ N looks" when DR-27 hid the board.
    var backLabel: String? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void
    let onRemove: () -> Void
    /// Esc closes the column — except while its picture is enlarged, when Esc closes that first.
    var escapeCloses = true
    var onEnlarge: (CGRect) -> Void = { _ in }
    var onImageFrame: (CGRect) -> Void = { _ in }
    /// What the surface that opened the look adds before "Saved" (a page's sheet: the similar looks, "Take it off").
    var extra: AnyView? = nil
    @State private var imageFrame: CGRect = .zero

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                DetailHeader(title: summary.displayName, backLabel: backLabel, onShowList: onShowList,
                             closeHelp: Copy.Looks.closeHelp,
                             closeShortcut: escapeCloses ? .cancelAction : nil, onClose: onClose)
                Button { onEnlarge(imageFrame) } label: {
                    image
                        .frame(maxWidth: .infinity)
                        .aspectRatio(summary.image?.aspect ?? 1.6, contentMode: .fit)
                        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                        .looksZoomSource { frame in imageFrame = frame; onImageFrame(frame) }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .keyboardShortcut("y", modifiers: .command)
                .help(Copy.Looks.enlargeHelp)
                .accessibilityLabel(Copy.Looks.enlarge)
                if let raw = summary.url, let url = URL(string: raw) {
                    InlineLink(title: summary.site ?? Copy.Looks.openPage, help: raw) { NSWorkspace.shared.open(url) }
                }
                if let heading = LooksNote.heading(summary) {
                    section(heading) {
                        Text(LooksNote.text(summary: summary, detail: detail))
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(summary.noteIsTheirs ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                }
                if !summary.palette.isEmpty {
                    section(Copy.Looks.palette) {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                            ForEach(summary.palette, id: \.self) { c in
                                HStack(spacing: CicadaTheme.spacingSM) {
                                    Circle().fill(LooksColour.color(c.hex))
                                        .frame(width: CicadaTheme.scaled(14), height: CicadaTheme.scaled(14))
                                        .overlay(Circle().strokeBorder(CicadaTheme.border, lineWidth: 1))
                                    Text(c.hex).font(CicadaTheme.metaFont).monospacedDigit()
                                        .foregroundStyle(CicadaTheme.textPrimary).textSelection(.enabled)
                                    if let role = c.role {
                                        Text(Copy.Looks.colourRole(role)).font(CicadaTheme.metaFont)
                                            .foregroundStyle(CicadaTheme.textTertiary)
                                    }
                                    Spacer()
                                    if let share = Copy.Looks.share(c.share, role: c.role) {
                                        Text(share).font(CicadaTheme.metaFont).monospacedDigit()
                                            .foregroundStyle(CicadaTheme.textTertiary)
                                    }
                                }
                            }
                            if !summary.look.isEmpty {
                                HStack(spacing: CicadaTheme.spacingXS) {
                                    ForEach(summary.look, id: \.self) { Tag(text: $0) }
                                }
                                .padding(.top, CicadaTheme.spacingXS)
                            }
                        }
                    }
                }
                if let roles = detail?.colourRoles, !roles.isEmpty {
                    section(Copy.Looks.colourRoles) {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                            ForEach(roles, id: \.self) { r in
                                HStack(spacing: CicadaTheme.spacingSM) {
                                    Circle().fill(LooksColour.color(r.hex))
                                        .frame(width: CicadaTheme.scaled(14), height: CicadaTheme.scaled(14))
                                        .overlay(Circle().strokeBorder(CicadaTheme.border, lineWidth: 1))
                                    Text(Copy.Looks.colourRole(r.role)).font(CicadaTheme.metaFont)
                                        .foregroundStyle(CicadaTheme.textPrimary)
                                    Text(r.hex).font(CicadaTheme.metaFont).monospacedDigit()
                                        .foregroundStyle(CicadaTheme.textSecondary).textSelection(.enabled)
                                    Spacer()
                                    Text(Copy.Looks.colourSource(r.source)).font(CicadaTheme.metaFont)
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                }
                            }
                        }
                    }
                }
                if let specimens = detail?.specimens, !specimens.isEmpty {
                    section(Copy.Looks.type) { LooksSpecimenList(specimens: specimens) }
                } else if let roles = detail?.typeRoles, !roles.isEmpty {
                    section(Copy.Looks.type) {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            ForEach(roles, id: \.self) { t in
                                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                                    Text(Copy.Looks.typeRole(t.role)).font(CicadaTheme.metaFont)
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                    Text(t.family).font(CicadaTheme.bodyFont)
                                        .foregroundStyle(CicadaTheme.textPrimary).textSelection(.enabled)
                                    let line = Copy.Looks.typeDetail(size: t.size, weight: t.weight,
                                                                     lineHeight: t.lineHeight)
                                    if !line.isEmpty {
                                        Text(line).font(CicadaTheme.metaFont).monospacedDigit()
                                            .foregroundStyle(CicadaTheme.textSecondary)
                                    }
                                }
                            }
                        }
                    }
                } else if !summary.fonts.isEmpty {
                    section(Copy.Looks.type) {
                        Text(summary.fonts.joined(separator: ", "))
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                    }
                }
                if let snippets = detail?.snippets, !snippets.isEmpty {
                    section(Copy.Looks.snippets) {
                        MarkdownBody(text: snippets.map { "```\($0.lang)\n\($0.code)\n```" }.joined(separator: "\n\n"))
                    }
                }
                if let extra { extra }
                section(Copy.Looks.savedFrom) {
                    Text(Copy.Looks.savedLine(day: LooksDay.words(summary.day),
                                              by: summary.addedBy == "user" ? Copy.Looks.byYou
                                                  : OriginIconography.label(for: summary.addedBy),
                                              via: Copy.Looks.via(summary.via)))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                NeutralButton(title: Copy.Looks.remove, size: .compact, help: Copy.Looks.removeHelp, action: onRemove)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
            // DR-36 — the detail takes the columns' remainder; its words keep the focus card's measure, as Sources'.
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(CicadaTheme.bgPane)
    }

    private func section<C: View>(_ label: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(label)
            content()
        }
    }
}

/// Looks v2 — whose words a note is. "What you liked" is only ever the person's own; an agent's note sits under
/// "Noted by <agent>", and an agent's empty note shows no section at all.
enum LooksNote {
    static func agentName(_ id: String) -> String {
        id == "agent" || id == "unknown" || id.isEmpty ? Copy.Looks.anAgent : OriginIconography.label(for: id)
    }

    static func heading(_ summary: DesignRefSummary) -> String? {
        if summary.noteIsTheirs { return Copy.Looks.liked }
        return summary.notePreview.isEmpty ? nil : Copy.Looks.notedBy(agentName(summary.noteBy))
    }

    static func text(summary: DesignRefSummary, detail: DesignRef?) -> String {
        if let note = detail?.note, !note.isEmpty { return note }
        return summary.notePreview.isEmpty ? Copy.Looks.noNote : summary.notePreview
    }
}

/// Pictures from a drop or a paste: image data, or a file URL that holds one. Read here, in the app — the backend
/// is handed bytes only (the rail: the app reads, the backend parses bytes).
enum LooksIntake {
    static func load(_ providers: [NSItemProvider], _ deliver: @escaping @MainActor (NSImage) -> Void) {
        guard let provider = providers.first else { return }
        if provider.canLoadObject(ofClass: NSImage.self) {
            _ = provider.loadObject(ofClass: NSImage.self) { object, _ in
                guard let image = object as? NSImage else { return }
                Task { @MainActor in deliver(image) }
            }
            return
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                guard let url, let image = NSImage(contentsOf: url) else { return }
                Task { @MainActor in deliver(image) }
            }
        }
    }
}

/// DR-58 (consistency pass, 2026-10-20) — a look's day in the app's one day grammar ("Yesterday", "Sep 23", the year
/// only when it is not this one), computed when read; the stored `YYYY-MM-DD` was printed raw before. Anything that is
/// not a day stays as it came.
enum LooksDay {
    static func words(_ raw: String, today: ISODay = .today()) -> String {
        guard let day = ISODay(raw) else { return raw }
        return RelativeDay.phrase(day, today: today)
    }
}
