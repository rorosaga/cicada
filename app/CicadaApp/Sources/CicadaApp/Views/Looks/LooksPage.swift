import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Design taste (owner, 2026-10-14) — the ninth rail page, ⌘9: a board of the looks the person likes. Each tile is a
/// screenshot with its colours under it; a click opens the reference beside the board (what they liked, the colours
/// with their share, the type, the snippets, where it came from). The eyebrow's field searches by words; a picture
/// dropped or pasted anywhere opens the composer, which saves it or finds the looks like it. Applies DR-22 (the rail),
/// DR-25 (the eyebrow), DR-37 (no card for one line), DR-40 (one primary action, in the composer), DR-41, DR-43
/// (never blank over good data), DR-44 (pills), DR-59 (copy). Looks polish (2026-10-15): a click on a picture enlarges
/// it over the board (`LooksZoom`; DR-60, DR-61, DR-66), and the Type section shows one specimen per family.
///
/// The app shrinks a capture before it leaves (`DesignImageShrink`) and posts bytes; the server reads the colours,
/// keeps the picture in the bank and embeds it (`api/routers/design.py`) — nothing here decodes or ranks.
struct LooksPage: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var cache = LooksCache()
    @State private var query = ""
    @State private var openId: String?
    @State private var composer: LooksComposerInput?

    var body: some View {
        LooksBoardView(
            refs: cache.visible, total: cache.board?.refs.count ?? 0, phase: cache.phase, vision: cache.board?.vision,
            searching: cache.ranking != nil, searchNote: cache.searchNote, query: $query,
            open: openId.flatMap { id in cache.board?.refs.first { $0.id == id } },
            detail: openId.flatMap { cache.refs[$0] }, writeError: cache.writeError,
            tile: { ref in AnyView(LooksStoredImage(ref: ref)) },
            onSubmit: { Task { await cache.search(query: query) } },
            onOpen: { ref in open(ref.id) }, onClose: { openId = nil },
            onRemove: { id in Task { await cache.remove(id); if openId == id { openId = nil } } },
            onTurnOn: { Task { await cache.turnOnPictureSearch() } },
            onAdd: { chooseFile() }, onImage: { image, via in present(image, via: via) },
            onRetry: { Task { await cache.refresh() } })
        .background(CicadaTheme.bgBase)
        .sheet(item: $composer) { input in
            LooksComposer(input: input, saving: cache.saving, error: cache.writeError,
                          onCancel: { composer = nil; cache.clearError() },
                          onFindSimilar: { upload in
                              composer = nil
                              query = ""
                              Task { await cache.search(query: "", image: upload.image, ext: upload.ext) }
                          },
                          onSave: { upload in
                              Task {
                                  if let ref = await cache.save(upload) {
                                      composer = nil
                                      openId = ref.summary.id
                                  }
                              }
                          })
        }
        .task { await cache.refresh() }
        // Say it once — Looks clicked again in the rail: the whole board, nothing open, no search.
        .onRailReselect(.looks, router: router) {
            router?.popToRoot(reduceMotion: reduceMotion) {
                openId = nil
                query = ""
                cache.clearSearch()
            }
        }
        .onChange(of: query) { _, text in if text.isEmpty { cache.clearSearch() } }
        .onChange(of: store.version) { old, new in
            guard LooksRefresh.shouldRevalidate(old: old, new: new) else { return }
            Task {
                await cache.refresh()
                if let openId { await cache.refreshRef(openId) }
            }
        }
        .onChange(of: store.bank) { _, _ in
            openId = nil
            cache.reset()
            Task { await cache.refresh() }
        }
        .task(id: cache.board?.vision.installing == true) {
            // While the image model downloads, ask again every few seconds (its progress rides the board's ETag).
            while cache.board?.vision.installing == true, !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                await cache.refresh()
            }
        }
    }

    private func open(_ id: String) {
        Instant.run { openId = id }
        Task { await cache.refreshRef(id) }
    }

    private func present(_ image: NSImage, via: String) {
        guard let prepared = DesignImageShrink.prepare(image) else { return }
        cache.clearError()
        composer = LooksComposerInput(image: image, data: prepared.data, ext: prepared.ext, via: via)
    }

    private func chooseFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg, .heic, .tiff, .webP, .image]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url, let image = NSImage(contentsOf: url) else { return }
        present(image, via: "drop")
    }
}

/// A screenshot the person handed the page, waiting for their note.
struct LooksComposerInput: Identifiable {
    let id = UUID()
    let image: NSImage
    let data: Data
    let ext: String
    let via: String
}

/// A tile's picture from Cicada's own API (`/design/{id}/image?v=…`), its colours standing in while it loads.
struct LooksStoredImage: View {
    let ref: DesignRefSummary

    var body: some View {
        StoredPreview(path: ref.image?.url) { LooksPaletteField(colours: ref.palette) }
    }
}

/// The board, pure over its inputs — the page above feeds it the cache; an offscreen render feeds it fixtures.
struct LooksBoardView: View {
    let refs: [DesignRefSummary]
    let total: Int
    let phase: LooksCache.Phase
    let vision: DesignVision?
    let searching: Bool
    let searchNote: String?
    @Binding var query: String
    let open: DesignRefSummary?
    let detail: DesignRef?
    let writeError: String?
    let tile: (DesignRefSummary) -> AnyView
    var onSubmit: () -> Void = {}
    var onOpen: (DesignRefSummary) -> Void = { _ in }
    var onClose: () -> Void = {}
    var onRemove: (String) -> Void = { _ in }
    var onTurnOn: () -> Void = {}
    var onAdd: () -> Void = {}
    var onImage: (NSImage, String) -> Void = { _, _ in }
    /// DR-43 — a first read that failed says why and offers Retry, as every list page does (`ListErrorCard`).
    var onRetry: () -> Void = {}

    static let detailWidth: CGFloat = 380
    @State private var dropTargeted = false
    @State private var zoom = LooksZoom()
    @State private var frames = LooksFrameBook()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// The look whose picture is enlarged: the open one, or any on the board.
    private var zoomed: DesignRefSummary? {
        guard let id = zoom.refId else { return nil }
        return open?.id == id ? open : refs.first { $0.id == id }
    }

    private func enlarge(_ ref: DesignRefSummary, from frame: CGRect) {
        let style = LooksZoom.style(LooksZoom.currentTrigger(), reduceMotion: reduceMotion)
        switch style {
        case .instant, .zoom: Instant.run { zoom.present(ref.id, from: frame, style: style) }
        case .fade: withAnimation(CicadaMotion.fade) { zoom.present(ref.id, from: frame, style: style) }
        }
    }

    /// The zoom just appeared collapsed on its thumbnail: grow it on the next frame.
    private func grow() {
        guard zoom.isPresented, !zoom.expanded else { return }
        DispatchQueue.main.async {
            withAnimation(CicadaMotion.morph(reduceMotion: false)) { zoom.expanded = true }
        }
    }

    private func shrink(_ trigger: LooksZoom.Trigger) {
        guard let id = zoom.refId else { return }
        switch LooksZoom.style(trigger, reduceMotion: reduceMotion) {
        case .instant: Instant.run { zoom.dismiss() }
        case .fade: withAnimation(CicadaMotion.fade) { zoom.dismiss() }
        case .zoom:
            Instant.run { zoom.source = frames.frame(for: id, fallback: zoom.source) }
            withAnimation(CicadaMotion.morph(reduceMotion: false), completionCriteria: .logicallyComplete) {
                zoom.expanded = false
            } completion: {
                Instant.run { zoom.dismiss() }
            }
        }
    }

    private var eyebrow: String {
        if searching { return Eyebrow.text(Copy.Looks.page, Copy.Looks.matches(refs.count)) }
        return Eyebrow.text(Copy.Looks.page, total == 0 ? "" : Copy.Looks.eyebrowCount(total))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: eyebrow) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    CicadaSearchField(text: $query, prompt: Copy.Looks.find, width: CicadaTheme.scaled(280),
                                      onSubmit: onSubmit)
                        .help(Copy.Looks.searchHelp)
                    IconButton(systemName: "plus", help: Copy.Looks.addHelp, accessibilityLabel: Copy.Looks.add,
                               action: onAdd)
                }
            }
            if let vision, vision.supported, !vision.installed { pictureRow(vision) }
            if let note = searchNote ?? writeError {
                Text(note)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingGutter)
                    .padding(.bottom, CicadaTheme.spacingMD)
            }
            HStack(alignment: .top, spacing: 0) {
                content
                if let open {
                    LooksDetailColumn(summary: open, detail: detail, image: tile(open), onClose: onClose,
                                      onRemove: { onRemove(open.id) }, escapeCloses: !zoom.isPresented,
                                      onEnlarge: { frame in enlarge(open, from: frame) },
                                      onImageFrame: { frame in frames.detail = (open.id, frame) })
                        .frame(width: CicadaTheme.scaled(Self.detailWidth))
                        .columnEdge()   // DR-11: the one permitted rule, from the theme, never a hand-drawn line
                }
            }
        }
        .coordinateSpace(.named(LooksZoom.space))
        .overlay {
            if let zoomed {
                LooksZoomOverlay(zoom: zoom, summary: zoomed, onClose: shrink, onAppear: grow)
                    .transition(.opacity)
            }
        }
        .overlay {
            if dropTargeted {
                CicadaTheme.shape(CicadaTheme.radiusLarge)
                    .strokeBorder(CicadaTheme.borderLight, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
                    .padding(CicadaTheme.spacingMD)
                    .allowsHitTesting(false)
            }
        }
        .onDrop(of: [.image, .fileURL], isTargeted: $dropTargeted) { providers in
            LooksIntake.load(providers) { image in onImage(image, "drop") }
            return true
        }
        .onPasteCommand(of: [.png, .tiff, .jpeg, .image]) { providers in
            LooksIntake.load(providers) { image in onImage(image, "paste") }
        }
    }

    @ViewBuilder
    private var content: some View {
        if refs.isEmpty {
            Group {
                switch phase {
                case .loading, .idle where total == 0:
                    // DR-43 — the list pages' one first-read state: words over a still skeleton.
                    ListSkeleton(message: Copy.Looks.loading)
                        .padding(.horizontal, CicadaTheme.scaled(30))
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                case .failed(let why):
                    ListErrorCard(title: Copy.Looks.loadFailedTitle, message: why, retry: onRetry)
                        .frame(maxHeight: .infinity, alignment: .top)
                default:
                    if searching {
                        Text(Copy.Looks.noMatch).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    } else {
                        EmptyStateView(title: Copy.Looks.emptyTitle, message: Copy.Looks.emptyMessage,
                                       actionLabel: Copy.Looks.add, action: onAdd)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(220)),
                                             spacing: CicadaTheme.spacingLG)],
                          alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(refs) { ref in
                        LooksTile(ref: ref, selected: ref.id == open?.id, image: tile(ref),
                                  onEnlarge: { frame in
                                      if open?.id != ref.id { onOpen(ref) }
                                      enlarge(ref, from: frame)
                                  },
                                  onImageFrame: { frame in frames.tiles[ref.id] = frame }) { onOpen(ref) }
                    }
                }
                .padding(.horizontal, open == nil ? CicadaTheme.spacingGutter : CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.scaled(72))
            }
            .frame(maxWidth: .infinity)
        }
    }

    /// DR-37 — one line, so a row, never a card: what understanding images is for, its download size (both parts when
    /// the meaning part isn't here yet), and the click.
    private func pictureRow(_ vision: DesignVision) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: "photo.on.rectangle.angled")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(vision.installing ? (vision.step.isEmpty ? Copy.Looks.saving : vision.step)
                 : "\(Copy.Looks.pictureOff) \(Copy.Looks.pictureDownload(vision.downloadBytes, includesMeaning: vision.includesText))")
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
            Spacer(minLength: CicadaTheme.spacingSM)
            if !vision.installing {
                NeutralButton(title: Copy.Looks.turnOn, size: .compact, action: onTurnOn)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingGutter)
        .padding(.bottom, CicadaTheme.spacingMD)
    }
}

/// One look on the board: the screenshot, its name, its colours as one strip, the site and the day. A click on the
/// screenshot enlarges it (and opens the look beside the board); a click on its name opens the look.
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
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius)
            .fill(selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
        .onHover { hovering = $0 }
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

/// The open reference, beside the board.
struct LooksDetailColumn: View {
    let summary: DesignRefSummary
    let detail: DesignRef?
    let image: AnyView
    let onClose: () -> Void
    let onRemove: () -> Void
    /// Esc closes the column — except while its picture is enlarged, when Esc closes that first.
    var escapeCloses = true
    var onEnlarge: (CGRect) -> Void = { _ in }
    var onImageFrame: (CGRect) -> Void = { _ in }
    @State private var imageFrame: CGRect = .zero

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                DetailHeader(title: summary.displayName, closeHelp: Copy.Looks.closeHelp,
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

/// The composer: the picture the person dropped or pasted, the page it came from, what they liked.
struct LooksComposer: View {
    let input: LooksComposerInput
    let saving: Bool
    let error: String?
    let onCancel: () -> Void
    let onFindSimilar: (DesignUpload) -> Void
    let onSave: (DesignUpload) -> Void
    @State private var link = ""
    @State private var title = ""
    @State private var note = ""

    private var upload: DesignUpload {
        DesignUpload(image: input.data, ext: input.ext, url: link.trimmingCharacters(in: .whitespaces),
                     title: title.trimmingCharacters(in: .whitespaces), note: note, via: input.via)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.Looks.composerTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Image(nsImage: input.image)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: .infinity, maxHeight: CicadaTheme.scaled(220))
                .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            TextField(Copy.Looks.linkField, text: $link).textFieldStyle(.roundedBorder)
            TextField(Copy.Looks.titleField, text: $title).textFieldStyle(.roundedBorder)
            TextField(Copy.Looks.noteField, text: $note, axis: .vertical)
                .lineLimit(3...6)
                .textFieldStyle(.roundedBorder)
            if let error {
                Text(error).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            LooksComposerActions(saving: saving, onCancel: onCancel, onFindSimilar: { onFindSimilar(upload) },
                                 onSave: { onSave(upload) })
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(460))
        .background(CicadaTheme.bgPane)
    }
}

/// The composer's actions (DR-40): Cancel and Find similar neutral, *Save to Looks* the surface's one primary action —
/// the accent fill (glass-prominent on macOS 26).
struct LooksComposerActions: View {
    let saving: Bool
    let onCancel: () -> Void
    let onFindSimilar: () -> Void
    let onSave: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            NeutralButton(title: Copy.Looks.cancel, shortcut: .cancelAction, action: onCancel)
            Spacer()
            NeutralButton(title: Copy.Looks.findSimilar, action: onFindSimilar)
            PrimaryActionButton(title: saving ? Copy.Looks.saving : Copy.Looks.save, action: onSave)
                .disabled(saving)
        }
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
