import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// C11 (G146; F-11, F-12) — the one entity avatar. It draws what the picture precedence answered
/// (`Store.picture(for:held:)`: a write in flight, else the graph node's, else the page the surface holds) at 20–88 pt,
/// and D's fallback when there is none — never a solid hue fill (R-08's must-fix, plan R-PE14): a person is initials in
/// a 1.5 pt hue ring, a company a monogram in its hue on a neutral square, every other type its outline glyph in its
/// hue. A logo stands bare (DR-52); a photo, a Contacts picture and a thumbnail carry the resting ring. Clusters, the
/// person card, the palette and Ask draw this, so a page looks the same everywhere.
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

    @Environment(Store.self) private var store
    @State private var image: NSImage?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovering = false
    @State private var dropTargeted = false

    private var editable: Bool { editing != .none && PictureActions.canEdit(type) }

    private var units: CGFloat { EntityPictureLayout.clamp(size) }
    private var frame: CGSize { EntityPictureLayout.frame(type, size: CicadaTheme.scaled(units)) }
    private var picture: EntityPictureRef? { store.picture(for: id, held: held) }
    private var loadKey: String { "\(store.bank)|\(id)|\(picture?.source.rawValue ?? "-")|\(picture?.url ?? "-")" }

    var body: some View {
        content
            .task(id: loadKey) { image = await load() }
            .help(editable ? Copy.People.changeHelp(name) : Copy.People.sourceLine(picture?.source))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(name)
            .accessibilityValue(Copy.People.sourceLine(picture?.source))
            .accessibilityActions {
                if editable { Button(Copy.People.changePicture) { change() } }
            }
    }

    /// R-PE15 — a click opens the picker, a hover dims under a camera, a dropped image uploads, a right-click offers the
    /// rest. A drag that is not an image passes through to the window's intake drop (`ContentView`).
    @ViewBuilder
    private var content: some View {
        if editable {
            Button(action: change) {
                surface.overlay {
                    if hovering || dropTargeted {
                        EntityPictureVeil(showsWord: editing == .hero, units: units)
                            .clipShape(EntityPictureLayout.clip(type, height: frame.height))
                            .transition(.opacity)
                    }
                }
            }
            .buttonStyle(.cicadaPlain)
            .onHover { hovering = $0 }
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering || dropTargeted)
            .onDrop(of: [UTType.image], isTargeted: $dropTargeted, perform: drop)
            .contextMenu { PictureMenuItems(id: id, name: name, type: type, held: held, heldInputs: heldInputs) }
        } else {
            surface
        }
    }

    private func change() {
        PictureActions.change(id: id, name: name, type: type, store: store,
                              inputs: store.pictureInputs(for: id, held: heldInputs))
    }

    private func drop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.image.identifier) })
        else { return false }
        let (id, type, store) = (self.id, self.type, self.store)
        let inputs = store.pictureInputs(for: id, held: heldInputs)
        provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
            guard let data else { return }
            Task { @MainActor in await PictureActions.upload(data: data, id: id, type: type, store: store, inputs: inputs) }
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
        case .upload, .contacts, .thumbnail:
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
    enum Fallback: Equatable { case initials(String), monogram(String), glyph(String) }

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
    /// initials; with nothing chosen a non-person non-company page wears its outline glyph.
    static func fallback(_ type: EntityType, name: String, chosenInitials: Bool = false) -> Fallback {
        if chosenInitials, type != .person { return .monogram(LogoImage.monogram(for: name)) }
        switch type {
        case .person: return .initials(LogoImage.monogram(for: name))
        case .company: return .monogram(LogoImage.monogram(for: name))
        default: return .glyph(glyph(type))
        }
    }

    /// DR-53 — outline symbols; Clusters' card header wears the same one (F-11).
    static func glyph(_ type: EntityType) -> String {
        switch type {
        case .person: "person"
        case .project: "flag"
        case .company: "building.2"
        case .concept: "sparkles"
        case .tool: "wrench.and.screwdriver"
        case .deadline: "calendar"
        case .skill: "star"
        case .location: "mappin.and.ellipse"
        case .media: "play.rectangle"
        case .hub: "circle.hexagongrid"
        case .directory: "folder"
        case .unknown: "circle.dashed"
        }
    }

    /// A logo stands bare (DR-52); every other picture and every square fallback carries the resting ring; a person's
    /// fallback wears its own hue ring instead.
    static func ringed(_ source: PictureSource?, hasImage: Bool, type: EntityType) -> Bool {
        hasImage ? source != .logo : type != .person
    }
}

/// R-PE14 — D's fallback: the hue once, as a ring or a glyph, never as a fill (DR-8).
struct EntityPictureFallback: View {
    let type: EntityType
    let name: String
    let units: CGFloat
    let frame: CGSize
    var chosenInitials = false

    var body: some View {
        let hue = CicadaTheme.entityColor(for: type)
        switch EntityPictureLayout.fallback(type, name: name, chosenInitials: chosenInitials) {
        case .initials(let text):
            Text(text)
                .font(CicadaTheme.font(size: units * 0.36, weight: .medium))
                .foregroundStyle(hue)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
                .frame(width: frame.width, height: frame.height)
                .background(Circle().fill(CicadaTheme.bgFocus))
                .overlay(Circle().strokeBorder(hue, lineWidth: CicadaTheme.scaled(1.5)))
        case .monogram(let text):
            Text(text)
                .font(CicadaTheme.font(size: units * 0.36, weight: .medium))
                .foregroundStyle(hue)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
                .frame(width: frame.width, height: frame.height)
                .background(CicadaTheme.bgOption)
        case .glyph(let symbol):
            Image(systemName: symbol)
                .font(CicadaTheme.font(size: units * 0.42))
                .foregroundStyle(hue)
                .frame(width: frame.width, height: frame.height)
                .background(CicadaTheme.bgOption)
        }
    }
}
