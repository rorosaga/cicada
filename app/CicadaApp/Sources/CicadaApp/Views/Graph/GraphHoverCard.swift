import AppKit
import Observation
import SwiftUI

// ROR-135 (owner 2026-11-06) — the small card a hovered graph node shows: a book its cover, title and author; a person
// their picture and name; a company or anything else its logo or picture, its name and one short line.
//
// It is SwiftUI over the canvas, not drawn in graph.js, and it is built only from what the app already holds with the
// graph: the node (name, type, summary, byline), the picture the one precedence resolved onto it
// (`Store.picture(for:)`), and bytes already in `ImageMemory`. graph.js tells Swift which node and where (see
// `reportHover`); a hover does no fetch of its own, shows no spinner, and a page with no picture shows none (a person
// their initials; any other type nothing — never a type glyph, owner 2026-10-28). Applies DR-2 (the text ladder),
// DR-5 (no accent), DR-9/DR-10 (a floating surface: a ring, one soft shadow in light only), DR-12 (continuous radii),
// DR-52 (a logo stands bare), DR-70 (everything scales with uiScale).

// MARK: - Content (pure)

enum GraphHoverCardContent {
    struct Content: Equatable {
        var title: String
        /// The one short line — nil for a person (picture and name) and for a page with nothing to say.
        var line: String?
    }

    /// The longest "one short line", in characters. The card wraps it to two lines at most.
    static let lineLimit = 96

    /// The card for a node, or nil where no card is shown: a facet satellite is a view of a page, not a page.
    static func make(_ node: GraphNode) -> Content? {
        if node.isFacet { return nil }
        let title = node.shownName
        if node.isHub { return Content(title: title, line: node.memberCount > 0 ? Copy.Graph.hoverHubPages(node.memberCount) : nil) }
        if node.type == .person { return Content(title: title, line: nil) }
        if let byline = node.byline?.trimmingCharacters(in: .whitespacesAndNewlines), !byline.isEmpty {
            return Content(title: title, line: byline)
        }
        return Content(title: title, line: firstSentence(node.summary))
    }

    /// The summary's first sentence, cut at a word when it is still long.
    static func firstSentence(_ summary: String?, limit: Int = lineLimit) -> String? {
        let text = (summary ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        var sentence = text
        if let stop = text.range(of: #"[.!?](\s|$)"#, options: .regularExpression) {
            sentence = String(text[..<stop.lowerBound])
        }
        sentence = sentence.trimmingCharacters(in: .whitespacesAndNewlines)
        guard sentence.count > limit else { return sentence.isEmpty ? nil : sentence }
        let cut = sentence.prefix(limit)
        let atWord = cut.lastIndex(of: " ").map { String(cut[..<$0]) } ?? String(cut)
        return atWord.trimmingCharacters(in: CharacterSet(charactersIn: " ,;:—-")) + "…"
    }
}

// MARK: - When it opens (the model)

/// Which node's card is up, and when. The pointer's rest is judged here, not in graph.js, so sweeping across a dense
/// graph posts cheap messages and opens nothing; the card opens `hoverCardOpenDelay` after the pointer settles on a
/// node, and at once while another card is up or within `hoverCardWarmWindow` of one closing.
@Observable
@MainActor
final class GraphHoverModel {
    struct Anchor: Equatable {
        var id: String
        var x: CGFloat
        var y: CGFloat
        var r: CGFloat
    }

    /// What the card draws now; nil is no card.
    private(set) var shown: Anchor?
    @ObservationIgnored private var pending: Anchor?
    @ObservationIgnored private var openTask: Task<Void, Never>?
    @ObservationIgnored private var closedAt: Date?
    @ObservationIgnored private var warmTask: Task<Void, Never>?

    /// Pure: does a card open without waiting? One is up, or one closed within the warm window.
    nonisolated static func opensAtOnce(cardUp: Bool, closedAgo: TimeInterval?) -> Bool {
        cardUp || (closedAgo.map { $0 < CicadaMotion.hoverCardWarmWindow } ?? false)
    }

    func hover(_ anchor: Anchor, now: Date = Date()) {
        if shown?.id == anchor.id || Self.opensAtOnce(cardUp: shown != nil, closedAgo: closedAt.map { now.timeIntervalSince($0) }) {
            openTask?.cancel(); pending = nil
            shown = anchor
            return
        }
        if pending?.id == anchor.id { pending = anchor; return }
        pending = anchor
        openTask?.cancel()
        openTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(CicadaMotion.hoverCardOpenDelay))
            guard !Task.isCancelled, let self, let anchor = self.pending else { return }
            self.pending = nil
            self.shown = anchor
        }
    }

    func end(now: Date = Date()) {
        openTask?.cancel(); pending = nil
        guard shown != nil else { return }
        shown = nil
        closedAt = now
    }

    /// Reads the pictures of the busiest pages into memory, once the graph is up and off the pointer's path, so a hover
    /// finds them on the first frame. Local reads only (`HoverPictures.image`); a cap keeps memory bounded.
    func warm(_ candidates: [(id: String, picture: EntityPictureRef)], bank: String) {
        warmTask?.cancel()
        guard !candidates.isEmpty else { return }
        warmTask = Task(priority: .utility) {
            for (id, picture) in candidates {
                if Task.isCancelled { return }
                _ = await HoverPictures.image(id: id, picture: picture, bank: bank)
            }
        }
    }
}

/// The pictures a hover may read: memory first, then the stores' own disk copy and the local backend — the bytes Cicada
/// already keeps for the page. A third party's thumbnail is never fetched from here (`PictureURL.external`): it is drawn
/// only if something else already brought it.
enum HoverPictures {
    static func image(id: String, picture: EntityPictureRef, bank: String) async -> NSImage? {
        if let hit = PictureMemory.cached(id: id, picture: picture, bank: bank) { return hit }
        guard let raw = picture.url else { return nil }
        switch picture.source {
        case .logo:
            return await LogoStore.shared.image(entityId: id, bank: bank)
        case .upload, .contacts, .messages, .thumbnail, .profile:
            guard let url = PictureURL.parse(raw), case .api = url else { return nil }
            return await PictureStore.shared.image(url, bank: bank)
        case .initials:
            return nil
        }
    }
}

// MARK: - Placement (pure)

enum GraphHoverPlacement {
    /// The card's top-left in the canvas: beside the node, on its right unless that runs off the canvas, then its left;
    /// centred on the node's height and kept inside the canvas.
    static func origin(anchor: CGPoint, radius: CGFloat, size: CGSize, container: CGSize,
                       gap: CGFloat = 10, margin: CGFloat = 8) -> CGPoint {
        var x = anchor.x + radius + gap
        if x + size.width > container.width - margin { x = anchor.x - radius - gap - size.width }
        x = max(margin, min(x, container.width - margin - size.width))
        let y = max(margin, min(anchor.y - size.height / 2, container.height - margin - size.height))
        return CGPoint(x: x, y: y)
    }
}

private struct HoverCardLayout: Layout {
    let anchor: CGPoint
    let radius: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        proposal.replacingUnspecifiedDimensions()
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard let card = subviews.first else { return }
        let size = card.sizeThatFits(.unspecified)
        let origin = GraphHoverPlacement.origin(anchor: anchor, radius: radius, size: size, container: bounds.size)
        card.place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y), anchor: .topLeading,
                   proposal: ProposedViewSize(size))
    }
}

// MARK: - The card

/// Laid over the canvas, same frame as the web view. Never takes the pointer: the canvas under it keeps every click, drag
/// and hover (the card sits beside the node, not on it).
struct GraphHoverCardLayer: View {
    let model: GraphHoverModel
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            if let anchor = model.shown, let node = graphVM.node(anchor.id), let content = GraphHoverCardContent.make(node) {
                HoverCardLayout(anchor: CGPoint(x: anchor.x, y: anchor.y), radius: anchor.r) {
                    GraphHoverCard(node: node, content: content)
                }
                .transition(.opacity)
            }
        }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: model.shown == nil)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

private struct GraphHoverCard: View {
    let node: GraphNode
    let content: GraphHoverCardContent.Content
    @Environment(Store.self) private var store

    private static let pictureUnits: CGFloat = 48
    private var width: CGFloat { CicadaTheme.scaled(300) }

    var body: some View {
        let picture = store.picture(for: node.id, held: node.pictureRef)
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            if !EntityPictureLayout.isEmpty(node.type, picture: picture) {
                HoverPictureSlot(node: node, picture: picture, bank: store.bank, units: Self.pictureUnits)
                    .id("\(node.id)|\(picture?.url ?? "-")")
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(content.title)
                    .font(CicadaTheme.font(size: 14, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(2)
                if let line = content.line {
                    Text(line)
                        .font(CicadaTheme.font(size: 13))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: width, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }
}

/// The picture, drawn the way `EntityPicture` draws it (the same geometry, ring and fallback), but from memory only: a
/// miss reads the stores' own copy once, off the main thread, and never reaches a third party.
private struct HoverPictureSlot: View {
    let node: GraphNode
    let picture: EntityPictureRef?
    let bank: String
    let units: CGFloat
    @State private var loaded: NSImage?

    var body: some View {
        let image = loaded ?? PictureMemory.cached(id: node.id, picture: picture, bank: bank)
        let frame = EntityPictureLayout.frame(node.type, size: CicadaTheme.scaled(units))
        let drawn = EntityPictureLayout.drawnFrame(node.type, source: picture?.source, image: image?.size, well: frame)
        let shape = EntityPictureLayout.clip(node.type, height: drawn.height)
        ZStack {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: picture?.source == .logo ? .fit : .fill)
                    .frame(width: drawn.width, height: drawn.height)
            } else {
                EntityPictureFallback(type: node.type, name: node.shownName, units: units, frame: frame,
                                      chosenInitials: picture?.source == .initials)
            }
        }
        .frame(width: drawn.width, height: drawn.height)
        .clipShape(shape)
        .overlay {
            if EntityPictureLayout.ringed(picture?.source, hasImage: image != nil, type: node.type) {
                shape.stroke(CicadaTheme.ring(.resting), lineWidth: 1)
            }
        }
        .frame(width: frame.width, height: frame.height)
        .task {
            guard loaded == nil, image == nil, let picture else { return }
            loaded = await HoverPictures.image(id: node.id, picture: picture, bank: bank)
        }
    }
}
