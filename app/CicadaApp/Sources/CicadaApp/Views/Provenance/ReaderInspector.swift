import SwiftUI

/// The Reader (G118 slice 2, design §4.4): a conversation, or a page's stored
/// text, opened beside whatever is on screen and scrolled to the sentence a
/// belief came from. A trailing `.inspector` on the main window's detail
/// column, so the entity card stays visible next to it — the belief and its
/// sentence side by side is the point of the feature.
///
/// Content, not chrome: no glass anywhere in here (R-M5, K12). Everything it
/// shows is fetched from the bank on demand and held in memory only — spans,
/// not copies (§4.9).
struct ReaderInspector: View {
    @Environment(ProvenanceRouter.self) private var router
    @Environment(ProvenanceCache.self) private var cache
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Phase {
        case loading
        case loaded(EpisodeText, ScalarText)
        case gone
        case failed
    }

    @State private var phase: Phase = .loading
    @State private var washVisible = false
    @State private var landingToken = 0
    @State private var conversations = ConversationsViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.background)
        .onExitCommand { router.close() }
        .task(id: router.current) { await load() }
    }

    // MARK: Loading

    private func load() async {
        guard let target = router.current else { return }
        phase = .loading
        washVisible = false
        let result = await cache.document(episode: target.episode, focus: target.query)
        // `.task(id:)` cancels a superseded load, but cancellation is
        // cooperative: a slow fetch for the previous target must never land
        // on the Reader after the person has moved on to another.
        guard !Task.isCancelled, router.current == target else { return }
        switch result {
        case let .loaded(doc):
            phase = .loaded(doc, ScalarText(doc.text))
            landingToken &+= 1
            if let id = doc.conversationId, !doc.isPage {
                await conversations.load(ids: [id])
            }
        case .gone:
            phase = .gone
        case .failed:
            phase = .failed
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                if router.canGoBack {
                    Button { router.back() } label: {
                        Image(systemName: "chevron.left").font(CicadaTheme.font(size: 12, weight: .semibold))
                    }
                    .buttonStyle(.cicadaPlain)
                    // ⌥⌘[ rather than ⌘[: the entity card beside the Reader
                    // already owns ⌘[ for its own back (plan R-PU9).
                    .keyboardShortcut("[", modifiers: [.command, .option])
                    .help(Copy.Provenance.back)
                    .accessibilityLabel(Copy.Provenance.back)
                }
                headerMark
                VStack(alignment: .leading, spacing: 2) {
                    // The track's one display-face moment (R-M3, ≥ 22 pt): the
                    // conversation's name, set like a page title.
                    Text(title)
                        .font(CicadaTheme.displayFont(size: 22))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                    if !meta.isEmpty {
                        Text(meta)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let id = conversationId, conversations.canResume(id) {
                    Button(Copy.Provenance.resume) {
                        Task { await act(await conversations.resume(id)) }
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
                }
                Button { router.close() } label: {
                    Image(systemName: "xmark").font(CicadaTheme.font(size: 11, weight: .semibold))
                }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textSecondary)
                .help(Copy.Provenance.close)
                .accessibilityLabel(Copy.Provenance.close)
            }
            if case let .loaded(doc, _) = phase, let line = ReaderHeader.captureLine(doc) {
                Label(line, systemImage: "info.circle")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
    }

    @ViewBuilder
    private var headerMark: some View {
        if case let .loaded(doc, _) = phase, doc.isPage {
            LogoImage(entityId: doc.episode, name: doc.title, type: .media, size: CicadaTheme.scaled(20))
        } else {
            OriginMark(origin: ReaderHeader.markOrigin(harness: loadedDoc?.harness ?? router.current?.knownHarness,
                                                        origin: loadedDoc?.origin),
                       size: CicadaTheme.scaled(20))
                .iconHover()
        }
    }

    private var loadedDoc: EpisodeText? {
        if case let .loaded(doc, _) = phase { return doc }
        return nil
    }

    private var title: String {
        let known = loadedDoc?.title ?? router.current?.knownTitle ?? ""
        return known.isEmpty ? Copy.Provenance.untitled : known
    }

    private var meta: String { loadedDoc.map { ReaderHeader.meta($0) } ?? "" }
    private var conversationId: String? { loadedDoc?.conversationId }

    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)”"
        case .gone: store.toast = "That conversation's transcript is gone — nothing to resume"
        case .failed(let message): store.toast = message
        }
    }

    // MARK: Body

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            placeholder
        case .gone:
            message(Copy.Provenance.gone, icon: "tray")
        case .failed:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                message(Copy.Provenance.failed, icon: "exclamationmark.triangle")
                Button(Copy.Provenance.retry) { Task { await load() } }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
            }
        case let .loaded(doc, scalars):
            if let target = router.current {
                document(doc, scalars: scalars, target: target)
            }
        }
    }

    /// Static lines, no shimmer (§4.2 — a placeholder is not an animation).
    private var placeholder: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(0..<4, id: \.self) { i in
                RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                    .fill(CicadaTheme.surfaceHover)
                    .frame(width: CicadaTheme.scaled(i == 3 ? 180 : 320), height: CicadaTheme.scaled(10))
            }
        }
        .padding(CicadaTheme.spacingMD)
        .accessibilityHidden(true)
    }

    private func message(_ text: String, icon: String) -> some View {
        Label(text, systemImage: icon)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingMD)
    }

    private func document(_ doc: EpisodeText, scalars: ScalarText, target: ReaderTarget) -> some View {
        let presentation = ReaderPresentation.resolve(target: target, doc: doc, textCount: scalars.count)
        let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: presentation.focus,
                                         focusStyle: presentation.focusStyle)
        let landingBlock = presentation.landing.flatMap { ReaderLayout.blockIndex(containing: $0, in: blocks) }
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    ForEach(presentation.banners, id: \.self) { banner in
                        ReaderBannerView(banner: banner)
                    }
                    if blocks.isEmpty {
                        message(Copy.Provenance.empty, icon: "text.bubble")
                    }
                    ForEach(blocks) { block in
                        ReaderTurnView(block: block, isLanding: block.index == landingBlock,
                                       revealed: washVisible)
                            .id(block.index)
                    }
                }
                .padding(CicadaTheme.spacingMD)
            }
            .accessibilityRotor("Cited passages") {
                ForEach(blocks.filter(\.holdsFocus)) { block in
                    AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
                                            id: block.index)
                }
            }
            .accessibilityRotor("Turns") {
                ForEach(blocks) { block in
                    AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
                                            id: block.index)
                }
            }
            .onChange(of: landingToken, initial: true) { _, _ in
                land(proxy: proxy, block: landingBlock, blocks: blocks, presentation: presentation)
            }
        }
    }

    /// Scroll to the cited turn after the first layout, fade the wash in over
    /// `spanReveal`, then say what was landed on (§4.4 Landing).
    private func land(proxy: ScrollViewProxy, block: Int?, blocks: [ReaderBlock],
                      presentation: ReaderPresentation) {
        Task { @MainActor in
            await Task.yield()
            if let block { proxy.scrollTo(block, anchor: .center) }
            withAnimation(CicadaMotion.spanReveal(reduceMotion: reduceMotion)) { washVisible = true }
            guard presentation.focus != nil, let hit = blocks.first(where: { $0.holdsFocus }),
                  let wash = hit.washes.first(where: { $0.style != .other }) else { return }
            let words = ScalarText(hit.text).slice(wash.range.lowerBound, wash.range.upperBound)
            AccessibilityNotification.Announcement(Copy.Provenance.citedPassage(String(words.prefix(120))))
                .post()
        }
    }
}

/// One turn: the speaker line, then the words with their washes. Selectable
/// text; the landing turn reads in the primary colour, the rest secondary.
struct ReaderTurnView: View {
    let block: ReaderBlock
    let isLanding: Bool
    let revealed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if !block.speaker.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if let mark = block.mark {
                        OriginMark(origin: mark, size: CicadaTheme.scaled(12))
                    }
                    Text(block.speaker)
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text("· \(Copy.Provenance.turn(block.index))")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    if let time = block.time {
                        Text(time)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            Text(ReaderText.attributed(block, revealed: revealed))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(isLanding ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.leading, CicadaTheme.spacingSM)
        .overlay(alignment: .leading) {
            if block.washes.contains(where: { $0.style == .focus }) {
                Rectangle().fill(CicadaTheme.dandelion).frame(width: 2)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(block.speaker.isEmpty
                            ? block.text
                            : "\(block.speaker), \(Copy.Provenance.turn(block.index)): \(block.text)")
    }
}

enum ReaderText {
    /// The cited span's wash (§4.2/§4.4) — emphasis, not a data encoding, so
    /// the one nature token allowed on content (K13).
    static let focusOpacity = 0.35
    /// Other spans the same entity cites: present, quieter, no margin bar.
    static let otherOpacity = 0.15

    /// The turn's text with its washes applied. Offsets are SCALAR offsets
    /// (§4.1), converted through `unicodeScalars` exactly as
    /// `ExcerptText.attributed` does; a range that does not fit is skipped,
    /// never trapped on. `revealed == false` is the frame before the wash
    /// fades in (`spanReveal`) — and the only frame under Reduce Motion is
    /// the revealed one, because the animation is nil there.
    static func attributed(_ block: ReaderBlock, revealed: Bool) -> AttributedString {
        var out = AttributedString(block.text)
        let scalars = block.text.unicodeScalars
        let count = scalars.count
        for wash in block.washes {
            guard wash.range.lowerBound >= 0, wash.range.upperBound <= count, !wash.range.isEmpty else { continue }
            let lower = scalars.index(scalars.startIndex, offsetBy: wash.range.lowerBound)
            let upper = scalars.index(scalars.startIndex, offsetBy: wash.range.upperBound)
            guard let a = AttributedString.Index(lower, within: out),
                  let b = AttributedString.Index(upper, within: out) else { continue }
            switch wash.style {
            case .focus:
                out[a..<b].backgroundColor = CicadaTheme.dandelionFill.opacity(revealed ? focusOpacity : 0)
            case .mention:
                out[a..<b].inlinePresentationIntent = .stronglyEmphasized
            case .other:
                out[a..<b].backgroundColor = CicadaTheme.dandelionFill.opacity(revealed ? otherOpacity : 0)
            }
        }
        return out
    }
}

/// One honest sentence above the text (§4.4 States). The icon is decoration;
/// the words carry the meaning.
struct ReaderBannerView: View {
    let banner: ReaderBanner

    var body: some View {
        Label(text, systemImage: icon)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surfaceHover)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private var text: String {
        switch banner {
        case .stale: Copy.Provenance.stale
        case .grown: Copy.Provenance.grown
        case .inferred: Copy.Provenance.inferred
        case .derived: Copy.Provenance.derived
        case .notFound: Copy.Provenance.notFound
        case .truncated: Copy.Provenance.truncated
        }
    }

    private var icon: String {
        switch banner {
        case .stale: "exclamationmark.triangle"
        case .grown: "arrow.down.to.line"
        case .inferred: "lightbulb"
        case .derived: "text.magnifyingglass"
        case .notFound: "magnifyingglass"
        case .truncated: "scissors"
        }
    }
}
