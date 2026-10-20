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
    @Environment(GraphViewModel.self) private var graphVM: GraphViewModel?
    @Environment(Store.self) private var store: Store?
    @State private var zoom = LooksZoom()
    @State private var saving = false
    private var cache: LooksCache { .shared }

    /// The look as the board has it now (a move or an edit in this sheet shows at once), else as it was opened.
    private var live: DesignRefSummary { cache.board?.refs.first { $0.id == summary.id } ?? summary }

    private var similar: [DesignRefSummary] {
        let byId = Dictionary((cache.board?.refs ?? []).map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return (cache.similar[summary.id] ?? []).compactMap { byId[$0] }.prefix(6).map { $0 }
    }

    var body: some View {
        LooksDetailColumn(summary: live, detail: cache.refs[summary.id], image: AnyView(LooksStoredImage(ref: live)),
                          onClose: onClose,
                          onRemove: { Task { await cache.remove(summary.id); onClose() } },
                          escapeCloses: !zoom.isPresented,
                          onEnlarge: { frame in enlarge(from: frame) },
                          extra: AnyView(extra))
            .frame(width: CicadaTheme.scaled(760), height: CicadaTheme.scaled(680))
            .coordinateSpace(.named(LooksZoom.space))
            .overlay {
                if zoom.isPresented {
                    LooksZoomOverlay(zoom: zoom, summary: live, onClose: shrink, onAppear: grow)
                        .transition(.opacity)
                }
            }
            .task(id: summary.id) {
                await cache.refreshRef(summary.id)
                await cache.loadSimilar(summary.id)
            }
    }

    private var extra: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PageLookEdit(summary: live, detail: cache.refs[summary.id], saving: saving) { title, url, note in
                saving = true
                Task {
                    if await cache.edit(summary.id, title: title, url: url, note: note) {
                        store?.toast = Copy.Looks.savedWords
                    } else {
                        store?.toast = cache.writeError
                    }
                    saving = false
                }
            }
            PageLookPlace(onPage: live.entity != nil, rank: { query in
                (graphVM?.clusterSearchIndex().rank(query) ?? []).filter { $0.id != live.entity }
                    .map { (id: $0.id, name: $0.name) }
            }, onPlace: { id in
                Task {
                    if await cache.attach(summary.id, to: id) { store?.toast = Copy.Looks.placed }
                    else { store?.toast = cache.writeError }
                }
            })
            PageLookExtra(similar: similar, names: names, onPage: live.entity != nil, onOpenPage: onOpenPage,
                          onTakeOff: { Task { if await cache.attach(summary.id, to: nil) { onClose() } } })
        }
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

// MARK: - Clusters' Looks tab and the sheet's own edits (review of #384)

/// Every look the person saved, on a page or not, as tiles — Clusters' Looks tab (owner 2026-10-20: "we can filter
/// looks inside the entities page"). Pure over its inputs. Words search on ⏎ (`LooksCache.search`); a picture dropped
/// or pasted here finds the looks like it. Each tile says the page it is on; a click opens the look (`PageLookSheet`).
/// DR-25 (the field in its row), DR-32/DR-43 (words for empty and first reads), DR-37 (tiles), DR-46 (the find field).
struct LooksGallery: View {
    let refs: [DesignRefSummary]
    let total: Int
    let phase: LooksCache.Phase
    let names: [String: String]
    let searching: Bool
    let note: String?
    @Binding var query: String
    var gutter: CGFloat = CicadaTheme.spacingGutter
    var tile: (DesignRefSummary) -> AnyView = { AnyView(LooksStoredImage(ref: $0)) }
    var onSubmit: () -> Void = {}
    var onOpen: (DesignRefSummary) -> Void = { _ in }
    var onImage: (NSImage) -> Void = { _ in }
    var onRetry: () -> Void = {}
    @State private var dropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                // ⌘F stays the page's own find.
                CicadaSearchField(text: $query, prompt: Copy.Looks.galleryFind, findEnabled: false,
                                  width: CicadaTheme.scaled(320), onSubmit: onSubmit)
                Text(searching ? Copy.Looks.matches(refs.count) : Copy.Looks.galleryCount(total))
                    .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                Spacer(minLength: 0)
            }
            if let note {
                Text(note).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            content
        }
        .padding(.horizontal, gutter)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .overlay {
            if dropTargeted {
                CicadaTheme.shape(CicadaTheme.radiusLarge)
                    .strokeBorder(CicadaTheme.borderLight, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
                    .padding(CicadaTheme.spacingMD)
                    .allowsHitTesting(false)
            }
        }
        .onDrop(of: [.image, .fileURL], isTargeted: $dropTargeted) { providers in
            LooksIntake.load(providers) { onImage($0) }
            return true
        }
        .onPasteCommand(of: [.png, .tiff, .jpeg, .image]) { providers in LooksIntake.load(providers) { onImage($0) } }
    }

    @ViewBuilder
    private var content: some View {
        if refs.isEmpty {
            switch phase {
            case .idle, .loading:
                ListSkeleton(message: Copy.Looks.loading)
            case .failed(let why):
                ListErrorCard(title: Copy.Looks.loadFailedTitle, message: why, retry: onRetry)
            case .loaded:
                Text(searching ? Copy.Looks.galleryNoMatch : Copy.Looks.galleryEmpty)
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        } else {
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(220)), spacing: CicadaTheme.spacingLG)],
                          alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(refs) { ref in
                        VStack(alignment: .leading, spacing: 0) {
                            LooksTile(ref: ref, selected: false, image: tile(ref), onEnlarge: { _ in onOpen(ref) }) {
                                onOpen(ref)
                            }
                            Text(PageLooks.place(ref, names: names))
                                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                .lineLimit(1)
                                .padding(.horizontal, CicadaTheme.spacingSM)
                        }
                    }
                }
                .padding(.bottom, CicadaTheme.scaled(72))
            }
        }
    }
}

/// The person's own words on a look: its name, its link and what they liked — the note is theirs once saved here
/// ("What you liked"); an agent's note is never put in their mouth, so the field starts empty over one.
struct PageLookEdit: View {
    let summary: DesignRefSummary
    let detail: DesignRef?
    var saving = false
    let onSave: (_ title: String, _ url: String, _ note: String) -> Void
    @State private var title = ""
    @State private var url = ""
    @State private var note = ""
    @State private var filled = false

    private var theirNote: String { summary.noteIsTheirs ? (detail?.note ?? summary.notePreview) : "" }
    private var changed: Bool {
        title != summary.title || url != (summary.url ?? "") || note != theirNote
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Looks.yourWords)
            TextField("", text: $title).cicadaField(prompt: Copy.Looks.titleField, isEmpty: title.isEmpty)
            TextField("", text: $url).cicadaField(prompt: Copy.Looks.linkField, isEmpty: url.isEmpty)
            TextField("", text: $note, axis: .vertical)
                .lineLimit(3...6)
                .cicadaField(prompt: Copy.Looks.noteField, isEmpty: note.isEmpty)
            NeutralButton(title: saving ? Copy.Looks.saving : Copy.Looks.saveWords, size: .compact,
                          isDisabled: saving || !changed) { onSave(title, url, note) }
        }
        .onAppear { fill() }
        .onChange(of: detail?.note) { _, _ in if !changed || !filled { filled = false; fill() } }
    }

    private func fill() {
        guard !filled else { return }
        title = summary.title
        url = summary.url ?? ""
        note = theirNote
        filled = detail != nil || !summary.noteIsTheirs
    }
}

/// Put a look on a page, or move it to another: a find field over the graph's own names (`clusterSearchIndex`).
struct PageLookPlace: View {
    let onPage: Bool
    let rank: (String) -> [(id: String, name: String)]
    let onPlace: (String) -> Void
    @State private var query = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(onPage ? Copy.Looks.moveTo : Copy.Looks.placeOn)
            TextField("", text: $query).cicadaField(prompt: Copy.Looks.findPage, isEmpty: query.isEmpty)
                .frame(maxWidth: CicadaTheme.scaled(340))
            let hits = query.trimmingCharacters(in: .whitespaces).isEmpty ? [] : Array(rank(query).prefix(6))
            ForEach(hits, id: \.id) { hit in
                TextButton(title: hit.name, inline: true) { onPlace(hit.id); query = "" }
            }
        }
    }
}
