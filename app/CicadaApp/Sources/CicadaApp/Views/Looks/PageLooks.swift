import AppKit
import SwiftUI

/// Looks on the page of the thing they show (owner rulings 2026-10-20: "the Looks page might be better not to have;
/// this should be ingrained in the markdown of a specific thing"). The page's markdown carries the `## Looks` section
/// (`design_refs`, the one writer); the card draws it from the looks themselves, not from that markdown, so the
/// article leaves it out (`WikiArticle.ownSurfaces`) and this section shows each look as a tile (DR-37's row of
/// pictures, never a card per look), opens one large in a sheet with its colours, type, note and the looks like it,
/// and adds one in the two ways the owner chose: paste a website link (the link is saved and the person's own agent
/// captures its look for this page — the site-capture path, G166/ruling 25), or drop a picture anywhere on the page.
/// Applies DR-9 (rings), DR-32 (never blank: words for an empty state), DR-37, DR-39 (the empty section is a
/// remembered disclosure), DR-40 (neutral buttons, no primary on the card), DR-41, DR-43, DR-53 (glyphs), DR-58
/// (days in words), DR-59 (copy), DR-76 (the app's field).
enum PageLooks {
    /// A pasted link Cicada can ask an agent to capture: an http(s) address with a host, trimmed; else nil.
    static func link(_ raw: String) -> String? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: text), let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = url.host, !host.isEmpty else { return nil }
        return text
    }

    /// Where a look is, in words: the page it is on (by name when the graph knows it), else "Not on a page".
    static func place(_ ref: DesignRefSummary, names: [String: String]) -> String {
        guard let entity = ref.entity else { return Copy.Looks.notOnAPage }
        return Copy.Looks.onPage(names[entity] ?? entity)
    }

    /// A picture dropped on a page, shrunk and posted with the page as its subject; the server's sentence on a refusal.
    @MainActor
    static func drop(_ image: NSImage, on entityId: String, via: String = "drop",
                     cache given: LooksCache? = nil) async -> String {
        let cache = given ?? .shared
        guard let prepared = DesignImageShrink.prepare(image) else { return Copy.Looks.saveLookFailed }
        let upload = DesignUpload(image: prepared.data, ext: prepared.ext, url: nil, title: nil, note: nil, via: via,
                                  entity: entityId)
        guard await cache.save(upload) != nil else { return cache.writeError ?? Copy.Looks.saveLookFailed }
        return Copy.Looks.dropped
    }
}

/// The card's Looks: the tiles when the page shows looks, else a remembered disclosure holding only the ways to add.
struct PageLooksSection: View {
    let entityId: String
    var navigate: (String) -> Void = { _ in }
    @Environment(Store.self) private var store
    @Environment(GraphViewModel.self) private var graphVM: GraphViewModel?
    @AppStorage(CardSections.looksKey) private var emptyOpen = false
    @State private var opened: DesignRefSummary?
    private var cache: LooksCache { .shared }

    var body: some View {
        PageLooksBlock(refs: cache.looks(on: entityId), unplaced: cache.unplaced, entityId: entityId,
                       emptyOpen: $emptyOpen, onOpen: { opened = $0 })
            .sheet(item: $opened) { ref in
                PageLookSheet(summary: ref, names: names, onClose: { opened = nil },
                              onOpenPage: { id in opened = nil; navigate(id) })
            }
            .task { await cache.refresh() }
            .onChange(of: store.version) { old, new in
                guard LooksRefresh.shouldRevalidate(old: old, new: new) else { return }
                Task { await cache.refresh() }
            }
    }

    private var names: [String: String] {
        Dictionary((graphVM?.entities ?? []).map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a })
    }
}

/// The section, pure over its inputs (the card feeds it the cache; the review renders feed it fixtures).
struct PageLooksBlock: View {
    let refs: [DesignRefSummary]
    let unplaced: [DesignRefSummary]
    let entityId: String
    var tile: (DesignRefSummary) -> AnyView = { AnyView(LooksStoredImage(ref: $0)) }
    @Binding var emptyOpen: Bool
    let onOpen: (DesignRefSummary) -> Void

    var body: some View {
        Group {
            if refs.isEmpty {
                CardDisclosure(title: Copy.Looks.section, summary: Copy.Looks.noneYet, isOpen: $emptyOpen) {
                    PageLookAdd(entityId: entityId, unplaced: unplaced)
                }
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        SectionLabel(Copy.Looks.section)
                        Text(Copy.Looks.sectionCount(refs.count))
                            .font(CicadaTheme.metaFont).monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    PageLooksGrid(refs: refs, tile: tile, onOpen: onOpen)
                    PageLookAdd(entityId: entityId, unplaced: unplaced)
                        .padding(.top, CicadaTheme.spacingXS)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The page's looks as tiles — the screenshot, its name, its colours, the site and the day (`LooksTile`).
struct PageLooksGrid: View {
    let refs: [DesignRefSummary]
    var minimum: CGFloat = 180
    var tile: (DesignRefSummary) -> AnyView = { AnyView(LooksStoredImage(ref: $0)) }
    let onOpen: (DesignRefSummary) -> Void

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(minimum)), spacing: CicadaTheme.spacingMD)],
                  alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(refs) { ref in
                LooksTile(ref: ref, selected: false, image: tile(ref), onEnlarge: { _ in onOpen(ref) }) { onOpen(ref) }
            }
        }
    }
}

/// The two ways to add a look to this page, plus the looks saved before that are on no page yet.
struct PageLookAdd: View {
    let entityId: String
    let unplaced: [DesignRefSummary]
    @Environment(Store.self) private var store: Store?
    @State private var link = ""
    @State private var busy = false
    @State private var said: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField("", text: $link)
                    .cicadaField(prompt: Copy.Looks.linkPrompt, isEmpty: link.isEmpty)
                    .onSubmit { capture() }
                    .frame(maxWidth: CicadaTheme.scaled(340))
                NeutralButton(title: Copy.Looks.capture, size: .compact, isDisabled: busy || link.isEmpty,
                              help: Copy.Looks.captureHelp) { capture() }
                if !unplaced.isEmpty {
                    Menu {
                        ForEach(unplaced) { ref in
                            Button([ref.displayName, ref.site].compactMap { $0 }.joined(separator: " · ")) {
                                place(ref)
                            }
                        }
                    } label: {
                        Text(Copy.Looks.placeSaved).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                    .disabled(busy)
                    .help(Copy.Looks.placeSavedHelp)
                }
            }
            Text(said ?? Copy.Looks.dropHint)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func capture() {
        guard !busy else { return }
        guard let url = PageLooks.link(link) else {
            said = Copy.Looks.notALink
            return
        }
        busy = true
        Task {
            do {
                let answer = try await LooksCacheAPI.client.lookFromLink(url: url, subject: entityId)
                AppPasteboard.copy(answer.prompt)
                store?.toast = Copy.Looks.saveLookQueued
                said = nil
                link = ""
            } catch {
                said = LooksErrors.sentence(error)
            }
            busy = false
        }
    }

    private func place(_ ref: DesignRefSummary) {
        busy = true
        Task {
            if await LooksCache.shared.attach(ref.id, to: entityId) {
                store?.toast = Copy.Looks.placed
                said = nil
            } else {
                said = LooksCache.shared.writeError
            }
            busy = false
        }
    }
}

/// The API the page's add row talks to (a seam for previews and tests; the app's client by default).
enum LooksCacheAPI {
    @MainActor static var client: any DesignAPI = APIClient.shared
}

/// One look, opened large over the card: the screenshot (a click enlarges it further, `LooksZoom`), what was liked,
/// the colours and type, where it came from, the looks like it (each with the page it is on), and the two ways to
/// let go of it — off this page, or removed.
struct PageLookSheet: View {
    let summary: DesignRefSummary
    let names: [String: String]
    let onClose: () -> Void
    let onOpenPage: (String) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var zoom = LooksZoom()
    private var cache: LooksCache { .shared }

    private var similar: [DesignRefSummary] {
        let byId = Dictionary((cache.board?.refs ?? []).map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return (cache.similar[summary.id] ?? []).compactMap { byId[$0] }.prefix(6).map { $0 }
    }

    var body: some View {
        LooksDetailColumn(summary: summary, detail: cache.refs[summary.id], image: AnyView(LooksStoredImage(ref: summary)),
                          onClose: onClose,
                          onRemove: { Task { await cache.remove(summary.id); onClose() } },
                          escapeCloses: !zoom.isPresented,
                          onEnlarge: { frame in enlarge(from: frame) },
                          extra: AnyView(extra))
            .frame(width: CicadaTheme.scaled(760), height: CicadaTheme.scaled(680))
            .coordinateSpace(.named(LooksZoom.space))
            .overlay {
                if zoom.isPresented {
                    LooksZoomOverlay(zoom: zoom, summary: summary, onClose: shrink, onAppear: grow)
                        .transition(.opacity)
                }
            }
            .task(id: summary.id) {
                await cache.refreshRef(summary.id)
                await cache.loadSimilar(summary.id)
            }
    }

    private var extra: some View {
        PageLookExtra(similar: similar, names: names, onPage: summary.entity != nil, onOpenPage: onOpenPage,
                      onTakeOff: { Task { if await cache.attach(summary.id, to: nil) { onClose() } } })
    }

    // The board's zoom rules (looks polish; DR-60, DR-61, DR-66): a key is instant, Reduce Motion fades, a pointer zooms.
    private func enlarge(from frame: CGRect) {
        let style = LooksZoom.style(LooksZoom.currentTrigger(), reduceMotion: reduceMotion)
        switch style {
        case .instant, .zoom: Instant.run { zoom.present(summary.id, from: frame, style: style) }
        case .fade: withAnimation(CicadaMotion.fade) { zoom.present(summary.id, from: frame, style: style) }
        }
    }

    private func grow() {
        guard zoom.isPresented, !zoom.expanded else { return }
        DispatchQueue.main.async {
            withAnimation(CicadaMotion.morph(reduceMotion: false)) { zoom.expanded = true }
        }
    }

    private func shrink(_ trigger: LooksZoom.Trigger) {
        switch LooksZoom.style(trigger, reduceMotion: reduceMotion) {
        case .instant: Instant.run { zoom.dismiss() }
        case .fade: withAnimation(CicadaMotion.fade) { zoom.dismiss() }
        case .zoom:
            withAnimation(CicadaMotion.morph(reduceMotion: false), completionCriteria: .logicallyComplete) {
                zoom.expanded = false
            } completion: {
                Instant.run { zoom.dismiss() }
            }
        }
    }
}

/// The sheet's own part, pure: the looks like this one (each saying the page it is on; a click opens that page) and
/// "Take it off this page".
struct PageLookExtra: View {
    let similar: [DesignRefSummary]
    let names: [String: String]
    let onPage: Bool
    var tile: (DesignRefSummary) -> AnyView = { AnyView(LooksStoredImage(ref: $0)) }
    let onOpenPage: (String) -> Void
    let onTakeOff: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Looks.similar)
            if similar.isEmpty {
                Text(Copy.Looks.noSimilar).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(150)), spacing: CicadaTheme.spacingSM)],
                          alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(similar) { ref in
                        VStack(alignment: .leading, spacing: 0) {
                            LooksTile(ref: ref, selected: false, image: tile(ref),
                                      onEnlarge: { _ in if let id = ref.entity { onOpenPage(id) } }) {
                                if let id = ref.entity { onOpenPage(id) }
                            }
                            Text(PageLooks.place(ref, names: names))
                                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                .lineLimit(1)
                                .padding(.horizontal, CicadaTheme.spacingSM)
                        }
                    }
                }
            }
            if onPage {
                NeutralButton(title: Copy.Looks.takeOff, size: .compact, help: Copy.Looks.takeOffHelp, action: onTakeOff)
                    .padding(.top, CicadaTheme.spacingSM)
            }
        }
    }
}
