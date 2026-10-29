import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// C11 (G146; F-11, F-12) — the one entity avatar. It draws what the picture precedence answered
/// (`Store.picture(for:held:)`: a write in flight, else the graph node's, else the page the surface holds) at 20–88 pt,
/// and D's fallback when there is none — never a solid hue fill (R-08's must-fix, plan R-PE14): a person is initials in
/// a 1.5 pt hue ring; every other type draws **nothing** (owner 2026-10-28, DESIGN_RULES §9: no generic type glyph or
/// made-up monogram stands in for a picture) — an empty slot of the same size, so a row's text keeps its leading edge,
/// or no slot at all where `collapsesWhenEmpty` (a lone picture beside a title). A non-person page shows initials only
/// when the person chose "Use initials instead". A logo stands bare (DR-52); a photo, a Contacts picture and a
/// thumbnail carry the resting ring. Clusters, the person card, the palette and Ask draw this, so a page looks the same
/// everywhere.
struct EntityPicture: View {
    /// How the picture answers the pointer (plan R-PE15; wired in Task 4).
    enum Editing: Equatable { case none, tile, hero }

    let id: String
    let name: String
    let type: EntityType
    /// Units — scaled here with `uiScale` (DR-70) and clamped to C11's 20…88.
    var size: CGFloat = 28
    /// The page the surface already holds (the card's full entity), for an id the graph has no node for.
    var held: EntityPictureRef? = nil
    var heldInputs: PictureInputs? = nil
    var editing: Editing = .none
    /// With nothing to draw (`EntityPictureLayout.isEmpty`), take no space at all instead of an empty slot: for a lone
    /// picture beside a title, or a list where no row has a picture. A row in a list that has some keeps the slot.
    var collapsesWhenEmpty = false

    @Environment(Store.self) private var store
    @State private var image: NSImage?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovering = false
    @State private var dropTargeted = false
    @State private var anchor = PictureMenuAnchor()

    private var editable: Bool { editing != .none && PictureActions.canEdit(type) }

    private var units: CGFloat { EntityPictureLayout.clamp(size) }
    private var frame: CGSize { EntityPictureLayout.frame(type, size: CicadaTheme.scaled(units)) }
    private var picture: EntityPictureRef? { store.picture(for: id, held: held) }
    private var loadKey: String { "\(store.bank)|\(id)|\(picture?.source.rawValue ?? "-")|\(picture?.url ?? "-")" }

    var body: some View {
        if collapsesWhenEmpty && EntityPictureLayout.isEmpty(type, picture: picture) {
            EmptyView()
        } else {
            drawn
        }
    }

    private var drawn: some View {
        content
            .task(id: loadKey) { image = await load() }
            .help(editable ? Copy.People.changeHelp(name, source: picture?.source) : Copy.People.sourceLine(picture?.source))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(editable ? Copy.People.changePictureLabel(name) : name)
            .accessibilityValue(Copy.People.sourceLine(picture?.source))
            .accessibilityAddTraits(editable ? .isButton : [])
            .accessibilityAction { if editable { openChoices() } }
    }

    /// R-PE15, owner 2026-10-29 — the picture is the control: a click offers its choices (`PictureChoices`: the picker
    /// at once when a file is the only choice), a hover dims under a camera with a link cursor, a dropped image uploads,
    /// a right-click offers the same choices. A drag that is not an image passes through to the window's intake drop
    /// (`ContentView`).
    @ViewBuilder
    private var content: some View {
        if editable {
            Button(action: openChoices) {
                surface.overlay {
                    if hovering || dropTargeted {
                        EntityPictureVeil(showsWord: editing == .hero, units: units)
                            .clipShape(EntityPictureLayout.clip(type, height: frame.height))
                            .transition(.opacity)
                    }
                }
            }
            .buttonStyle(.cicadaPlain)
            .background(PictureMenuAnchorView(anchor: anchor))
            .onHover { hovering = $0 }
            .roomLinkCursor()
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering || dropTargeted)
            .onDrop(of: [UTType.image], isTargeted: $dropTargeted, perform: drop)
            .contextMenu { PictureMenuItems(id: id, name: name, type: type, held: held, heldInputs: heldInputs) }
        } else {
            surface
        }
    }

    private func openChoices() {
        PictureChoices.open(id: id, name: name, type: type, held: held, heldInputs: heldInputs, store: store,
                            anchor: anchor.view)
    }

    private func drop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.image.identifier) })
        else { return false }
        let (id, type, store) = (self.id, self.type, self.store)
        let bank = store.bank   // G183(d): the bank the picture was dropped in, before the data loads
        let inputs = store.pictureInputs(for: id, held: heldInputs)
        provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
            guard let data else { return }
            Task { @MainActor in await PictureActions.upload(data: data, id: id, type: type, bank: bank, store: store,
                                                                   inputs: inputs) }
        }
        return true
    }

    var surface: some View {
        let shape = EntityPictureLayout.clip(type, height: frame.height)
        let fit = picture?.source == .logo
        return ZStack {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: fit ? .fit : .fill)
                    .frame(width: frame.width, height: frame.height)
            } else {
                EntityPictureFallback(type: type, name: name, units: units, frame: frame,
                                      chosenInitials: picture?.source == .initials)
            }
        }
        .frame(width: frame.width, height: frame.height)
        .clipShape(shape)
        .overlay {
            if EntityPictureLayout.ringed(picture?.source, hasImage: image != nil, type: type) {
                shape.stroke(CicadaTheme.ring(.resting), lineWidth: 1)
            }
        }
    }

    private func load() async -> NSImage? {
        guard let picture, let raw = picture.url else { return nil }
        switch picture.source {
        case .logo:
            return await LogoStore.shared.image(entityId: id, bank: store.bank)
        case .upload, .contacts, .messages, .thumbnail, .profile:
            guard let url = PictureURL.parse(raw) else { return nil }
            return await PictureStore.shared.image(url, bank: store.bank)
        case .initials:
            return nil
        }
    }
}

/// C11 / R-PE14 — the avatar's geometry and fallback, pure.
enum EntityPictureLayout {
    enum Shape: Equatable { case circle, square, wide }
    /// `none` — owner 2026-10-28: a page that is not a person and has no picture draws nothing, never a type glyph.
    enum Fallback: Equatable { case initials(String), monogram(String), none }

    /// C11 — 20 to 88 pt, in units.
    static let sizeRange: ClosedRange<CGFloat> = 20...88

    static func clamp(_ units: CGFloat) -> CGFloat { min(max(units, sizeRange.lowerBound), sizeRange.upperBound) }

    static func shape(_ type: EntityType) -> Shape {
        switch type {
        case .person: .circle
        case .media: .wide
        default: .square
        }
    }

    /// A media page's well is 3:2 (F-11's video frame); everything else is square.
    static func frame(_ type: EntityType, size: CGFloat) -> CGSize {
        shape(type) == .wide ? CGSize(width: (size * 1.5).rounded(), height: size) : CGSize(width: size, height: size)
    }

    /// Continuous corners that scale with the picture (DR-12).
    static func clip(_ type: EntityType, height: CGFloat) -> AnyShape {
        switch shape(type) {
        case .circle: AnyShape(Circle())
        case .square: AnyShape(CicadaTheme.shape(height * 0.22))
        case .wide: AnyShape(CicadaTheme.shape(height * 0.2))
        }
    }

    /// `chosenInitials` — the person picked "Use initials instead" (R-PE4): initials on every type, since the menu said
    /// initials. With nothing chosen a person wears their initials and every other page nothing (owner 2026-10-28:
    /// the type glyphs and a company's made-up monogram read as placeholders, "npc icons").
    static func fallback(_ type: EntityType, name: String, chosenInitials: Bool = false) -> Fallback {
        if type == .person { return .initials(LogoImage.monogram(for: name)) }
        return chosenInitials ? .monogram(LogoImage.monogram(for: name)) : .none
    }

    /// The one decision every surface asks (owner 2026-10-28): is there anything to draw for this page? A person always
    /// has their initials; any other page only a picture (a logo, a photo, a thumbnail) or initials the person chose.
    static func isEmpty(_ type: EntityType, picture: EntityPictureRef?) -> Bool {
        type != .person && picture == nil
    }

    /// A list's slot rule (owner 2026-10-28): keep the picture column only while some row in it draws something, so
    /// names line up when pictures are mixed and start at the edge when there are none.
    static func anyDrawn(_ pages: [(type: EntityType, picture: EntityPictureRef?)]) -> Bool {
        pages.contains { !isEmpty($0.type, picture: $0.picture) }
    }

    @MainActor
    static func anyDrawn(_ entities: [Entity], store: Store) -> Bool {
        anyDrawn(entities.map { ($0.type, store.picture(for: $0.id, held: $0.pictureRef)) })
    }

    /// The initials' size and weight at `units`: 0.36 of the picture, medium. `compact` (the Messages bubbles only,
    /// 2026-10-16) — a stacked bubble below 24 units, where 0.36 set a 7 pt hairline nobody read as a picture, takes
    /// half its height, semibold. Every other small picture sits beside its own name in a row and keeps the proportion.
    static let smallInitialsBelow: CGFloat = 24
    /// A stacked bubble's monogram disc: the person's hue at this opacity over the ground (2026-10-16).
    static let bubbleFill: Double = 0.35
    static func initialsType(units: CGFloat, compact: Bool = false) -> (size: CGFloat, weight: Font.Weight) {
        compact && units < smallInitialsBelow ? (units * 0.5, .semibold) : (units * 0.36, .medium)
    }

    /// A logo stands bare (DR-52); every other picture and a chosen monogram carry the resting ring; a person's
    /// fallback wears its own hue ring instead, and an empty slot draws no ring at all.
    static func ringed(_ source: PictureSource?, hasImage: Bool, type: EntityType) -> Bool {
        hasImage ? source != .logo : (type != .person && source == .initials)
    }
}

/// R-PE14 — D's fallback: the hue once, as a ring or a chosen monogram, never as a fill (DR-8); nothing for a page that
/// is not a person (owner 2026-10-28).
struct EntityPictureFallback: View {
    let type: EntityType
    let name: String
    let units: CGFloat
    let frame: CGSize
    var chosenInitials = false
    /// A stacked bubble's face (`MessageBubbleFace`): bigger, semibold initials below 24 units.
    var compactInitials = false

    var body: some View {
        let hue = CicadaTheme.entityColor(for: type)
        let initials = EntityPictureLayout.initialsType(units: units, compact: compactInitials)
        switch EntityPictureLayout.fallback(type, name: name, chosenInitials: chosenInitials) {
        case .initials(let text) where compactInitials:
            // A stacked bubble (owner, 2026-10-16): a disc filled with the hue over the ground and the letter in the
            // primary text colour. A ring around one hue letter at bubble size read as an info glyph ("ⓘ").
            Text(text)
                .font(CicadaTheme.font(size: initials.size, weight: initials.weight))
                .foregroundStyle(CicadaTheme.textPrimary)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
                .frame(width: frame.width, height: frame.height)
                .background(Circle().fill(hue.opacity(EntityPictureLayout.bubbleFill)))
                .background(Circle().fill(CicadaTheme.bgBase))
        case .initials(let text):
            Text(text)
                .font(CicadaTheme.font(size: initials.size, weight: initials.weight))
                .foregroundStyle(hue)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
                .frame(width: frame.width, height: frame.height)
                .background(Circle().fill(CicadaTheme.bgFocus))
                .overlay(Circle().strokeBorder(hue, lineWidth: CicadaTheme.scaled(1.5)))
        case .monogram(let text):
            Text(text)
                .font(CicadaTheme.font(size: initials.size, weight: initials.weight))
                .foregroundStyle(hue)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
                .frame(width: frame.width, height: frame.height)
                .background(CicadaTheme.bgOption)
        case .none:
            Color.clear
                .frame(width: frame.width, height: frame.height)
                .accessibilityHidden(true)
        }
    }
}
