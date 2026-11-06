import SwiftUI

/// ROR-138 follow-up (owner 2026-11-06: "each row shows a small logo of where it came from, so they can tell at a
/// glance") — the one leading slot of a Media row in Clusters. Every row spends the same 3:2 well (the size a media
/// page's picture is drawn in, `EntityPictureLayout.frame`) so the titles share one left edge whether the row has a
/// picture, only a source, or neither:
///   - a picture that arrived → the picture, with the source's mark as a small corner badge, so the origin is never lost
///     to a thumbnail;
///   - no picture (or one that has not arrived), a source → the source's own mark centred in a ringed well of the same size (DR-48: a ring, not a shadow);
///   - neither → the well is held empty only while a neighbour draws one, else it takes no space at all.
/// Nothing is fetched: the mark is the Sources page's own table (`OriginIconography`), and a type glyph is never drawn
/// (owner 2026-10-28) — an origin with no known mark ("unknown") draws nothing rather than a stand-in.
struct MediaLeadingSlot: View {
    let entity: Entity
    /// Some row beside this one draws a picture or a mark: keep the slot so every title starts at one edge.
    let reserves: Bool
    @Environment(Store.self) private var store
    @State private var imageArrived = false

    /// The picture's height in units — the row's two lines (13 pt title, 11 pt line) fit beside it.
    static let units: CGFloat = 32

    /// The origin whose mark this page draws, or nil: a media page with no origin, or only "unknown", draws none.
    static func markOrigin(_ entity: Entity) -> String? {
        guard entity.type == .media, let origin = entity.origin, !origin.isEmpty, origin != "unknown" else { return nil }
        return origin
    }

    private var well: CGSize { EntityPictureLayout.frame(.media, size: CicadaTheme.scaled(Self.units)) }

    var body: some View {
        let origin = Self.markOrigin(entity)
        let hasPicture = EntityPictureLayout.anyDrawn([entity], store: store)
        let dim = entity.quiet ? CicadaTheme.quietPictureOpacity : 1
        if hasPicture || origin != nil || reserves { slot(origin: origin, hasPicture: hasPicture, dim: dim) }
    }

    /// A picture whose image has not arrived (offline, a thumbnail that never loaded) leaves its slot to the source's
    /// mark, so there is never a hole; once it has, the mark moves to a corner badge.
    @ViewBuilder
    private func slot(origin: String?, hasPicture: Bool, dim: Double) -> some View {
        let showsImage = hasPicture && imageArrived
        ZStack {
            if let origin, !showsImage {
                CicadaTheme.shape(well.height * 0.2).fill(CicadaTheme.bgBase)
                    .overlay(CicadaTheme.shape(well.height * 0.2).stroke(CicadaTheme.ring(.resting), lineWidth: 1))
                    .overlay { OriginMark(origin: origin, size: CicadaTheme.scaled(Self.units * 0.62)) }
                    .help(Copy.Lists.cameFrom(OriginIconography.label(for: origin)))
                    .accessibilityHidden(true)
            }
            if hasPicture {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: Self.units,
                              heldInputs: entity.pictureInputs, imageArrived: $imageArrived)
                    .overlay(alignment: .bottomTrailing) {
                        if let origin, showsImage { badge(origin) }
                    }
            }
        }
        .opacity(dim)
        .frame(width: well.width, height: well.height)
        // The gap to the title belongs to the slot, so a row with no slot has no gap either.
        .padding(.trailing, CicadaTheme.spacingMD)
    }

    private func badge(_ origin: String) -> some View {
        OriginMark(origin: origin, size: CicadaTheme.scaled(14))
            .padding(CicadaTheme.scaled(1.5))
            .background(Circle().fill(CicadaTheme.bgFocus))
            .offset(x: CicadaTheme.scaled(4), y: CicadaTheme.scaled(4))
            .help(Copy.Lists.cameFrom(OriginIconography.label(for: origin)))
            .accessibilityHidden(true)
    }
}
