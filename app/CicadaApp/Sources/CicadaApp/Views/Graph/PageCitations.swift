import SwiftUI

// MARK: - The article carries the beliefs (ruling 48 (16), DR-80)
//
// A cited line ends with a quiet superscript per source, like an encyclopedia's citations. The numbers, and which line
// each source backs, are the server's (`page_citations`): decided when the page was written, never guessed here. A
// marker opens a popover — a floating surface (DR-10), never an inline expansion — with who said it, when and the
// located words (DR-18), and *Show in conversation* into the Reader (DR-31). Its details are read when it opens.
//
// Keys: every cited line keeps its sources in the focus order as small chips in its gutter (the 🔗's place, owner
// 2026-10-26: never only on hover), so Tab moves from marker to marker, ⏎ opens one, Esc closes it.

/// Which marker is open: a source as cited by the line ending at `at`, or by a belief sentence.
struct CiteKey: Hashable, Identifiable {
    let n: Int
    var at: Int? = nil
    var claim: String? = nil
    var inferred = false

    var id: String { "\(n)|\(at ?? -1)|\(claim ?? "")" }

    /// The marker's link inside a line of text: `cicada://cite/<n>?at=<offset>` (or `claim=<id>`).
    var url: URL? {
        var parts = URLComponents()
        parts.scheme = "cicada"
        parts.host = "cite"
        parts.path = "/\(n)"
        var query: [URLQueryItem] = []
        if let at { query.append(URLQueryItem(name: "at", value: String(at))) }
        if let claim { query.append(URLQueryItem(name: "claim", value: claim)) }
        if inferred { query.append(URLQueryItem(name: "inferred", value: "1")) }
        parts.queryItems = query.isEmpty ? nil : query
        return parts.url
    }

    init(n: Int, at: Int? = nil, claim: String? = nil, inferred: Bool = false) {
        self.n = n
        self.at = at
        self.claim = claim
        self.inferred = inferred
    }

    /// A marker link back to its key; nil for any other link.
    init?(url: URL) {
        guard url.scheme == "cicada", url.host == "cite",
              let n = Int(url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))) else { return nil }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        self.n = n
        at = items.first { $0.name == "at" }?.value.flatMap(Int.init)
        claim = items.first { $0.name == "claim" }?.value
        inferred = items.first { $0.name == "inferred" }?.value == "1"
    }
}

enum CitationMarks {
    /// The superscripts after a line: one per source, `labelFont`-sized, `textTertiary` (DR-80), each a link to its
    /// popover. A thin space keeps them off the full stop.
    static func text(_ keys: [CiteKey]) -> Text {
        guard !keys.isEmpty else { return Text(verbatim: "") }
        var out = AttributedString()
        for (i, key) in keys.enumerated() {
            var run = AttributedString((i == 0 ? "\u{2009}" : "\u{2009}") + String(key.n))
            run.font = CicadaTheme.labelFont
            run.baselineOffset = CicadaTheme.scaled(5)
            run.foregroundColor = CicadaTheme.textTertiary
            run.link = key.url
            out.append(run)
        }
        return Text(out)
    }

    /// A line's keys, in the order its sources were cited.
    static func keys(_ markers: [PageBlocks.Citations.Marker]) -> [CiteKey] {
        markers.flatMap { marker in marker.refs.map { CiteKey(n: $0, at: marker.at) } }
    }
}

/// Opens a marker clicked inside a line of text; every other link goes on to the card's own handler (wikilinks, the
/// web), so a line keeps its links.
struct CitationLinkHandler: ViewModifier {
    @Binding var open: CiteKey?
    @Environment(\.openURL) private var parent

    func body(content: Content) -> some View {
        content.environment(\.openURL, OpenURLAction { url in
            if let key = CiteKey(url: url) {
                open = key
                return .handled
            }
            parent(url)
            return .handled
        })
    }
}

/// VoiceOver (and any assistive client) opens a line's sources without hovering or finding the superscript: one named
/// action per source on the line itself ("Source 2"), the way a line's links are reached (`LineLinksAction`).
struct CitationActions: ViewModifier {
    let keys: [CiteKey]
    @Binding var open: CiteKey?

    func body(content: Content) -> some View {
        keys.reduce(AnyView(content)) { view, key in
            AnyView(view.accessibilityAction(named: Copy.Pages.citeSpoken(key.n)) { open = key })
        }
    }
}

/// A cited line's sources in its gutter: small focusable chips, shown on hover and while one holds focus. Hovering a
/// chip, clicking it, or ⏎ on it opens its popover.
struct CitationChips: View {
    let keys: [CiteKey]
    let entityId: String
    let visible: Bool
    @State private var open: CiteKey?
    @FocusState private var focused: CiteKey?

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(2)) {
            ForEach(keys) { key in
                Text(verbatim: String(key.n))
                    .font(CicadaTheme.labelFont.monospacedDigit())
                    .foregroundStyle(focused == key || open == key ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .frame(minWidth: CicadaTheme.scaled(18), minHeight: CicadaTheme.scaled(18))
                    .background(CicadaTheme.shape(CicadaTheme.radiusXS)
                        .fill(focused == key || open == key ? CicadaTheme.bgSelected : .clear))
                    .contentShape(Rectangle())
                    .focusable()
                    .focused($focused, equals: key)
                    .focusEffectDisabled()
                    .onTapGesture { open = key }
                    .onHover { if $0 { open = key } }
                    .onKeyPress(.return) {
                        open = key
                        return .handled
                    }
                    .help(Copy.Pages.citeHelp(key.n))
                    .accessibilityLabel(Copy.Pages.citeSpoken(key.n))
                    .accessibilityAddTraits(.isButton)
                    .accessibilityAction { open = key }
                    .popover(item: Binding(get: { open == key ? key : nil }, set: { if $0 == nil { open = nil } }),
                             arrowEdge: .bottom) { key in
                        CitationPopover(entityId: entityId, key: key)
                    }
            }
        }
        .opacity(visible || focused != nil || open != nil ? 1 : 0)
    }
}

/// A marker's popover: the kind and who · when, the located words with the cited span (DR-18) or, for a line written
/// from a conversation with no quote located, the conversation's title; then *Show in conversation* (DR-31).
struct CitationPopover: View {
    let entityId: String
    let key: CiteKey
    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @State private var phase: Phase = .loading

    enum Phase: Equatable {
        case loading
        case loaded(PageCitationDetail)
        case failed
        /// The page was renumbered since this marker was drawn (409): its line no longer cites this source.
        case stale
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            switch phase {
            case .loading:
                Text(Copy.Pages.readingSource).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            case .failed:
                Text(Copy.Pages.sourceUnavailable).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            case .stale:
                Text(Copy.Pages.sourceMoved).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            case .loaded(let detail):
                loaded(detail)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(340), alignment: .leading)
        .task(id: key) { await load() }
    }

    @ViewBuilder
    private func loaded(_ d: PageCitationDetail) -> some View {
        let today = ISODay.today()
        let when = PageWords.refWhen(first: d.first, last: d.last, today: today)
        let place = d.kind == "conversation"
            ? ProvenanceSummary.placeName(harness: d.harness, origin: d.origin) : nil
        HStack(spacing: CicadaTheme.scaled(6)) {
            Text(PageWords.popoverKind(d, inferred: key.inferred))
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text([when, place.map { $0.prefix(1).uppercased() + $0.dropFirst() }].compactMap { $0 }
                .joined(separator: " · "))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: 0)
            Text(verbatim: String(d.n)).font(CicadaTheme.labelFont).foregroundStyle(CicadaTheme.textTertiary)
        }
        if let span = d.span, !span.excerpt.isEmpty {
            let parts = QuoteBlock.parts(excerpt: span.excerpt, mentionOffsets: span.mentionOffsets)
            QuoteBlock(before: parts.before, span: parts.span, after: parts.after, kind: span.displayKind,
                       label: nil, caption: span.stale ? Copy.Provenance.staleCaption : nil,
                       style: span.stale ? .plain : .wash, lineLimit: 6)
        }
        HStack(spacing: CicadaTheme.spacingSM) {
            if let title = d.title, !title.isEmpty {
                Text(title).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            if router != nil, target(d) != nil {
                TextButton(title: Copy.Pages.showInConversation + " ›") { open(d) }
                    .fixedSize()
            }
        }
    }

    private func target(_ d: PageCitationDetail) -> ReaderTarget? {
        if let span = d.span {
            return ReaderTarget.best(span, subjectId: entityId, knownTitle: d.title, knownHarness: d.harness)
        }
        guard let episode = d.episodeId, d.kind != "page" else { return nil }
        return ReaderTarget(episode: episode, focus: .inferred, subjectId: entityId, knownTitle: d.title,
                            knownHarness: d.harness)
    }

    private func open(_ d: PageCitationDetail) {
        guard let router, let target = target(d) else { return }
        router.open(target)
    }

    private func load() async {
        let cacheKey = "\(entityId)|\(key.id)"
        if let held = CitationDetailCache.shared.held[cacheKey] {
            phase = .loaded(held)
            return
        }
        phase = .loading
        do {
            let detail = try await APIClient.shared.fetchCitation(entityId: entityId, n: key.n, at: key.at,
                                                                  claim: key.claim)
            guard !Task.isCancelled else { return }
            CitationDetailCache.shared.held[cacheKey] = detail
            phase = .loaded(detail)
        } catch APIError.httpError(409, _) {
            if !Task.isCancelled { phase = .stale }
        } catch {
            if !Task.isCancelled { phase = .failed }
        }
    }
}

/// Popovers already read, by page and marker — in memory, a few hundred at most. A page's are dropped whenever its
/// blocks change (`track`: a re-read after a write, an agent's edit, Sleep's push) as well as on its next open, so a
/// renumbered page never shows an old source. Not a Store domain.
@MainActor
final class CitationDetailCache {
    static let shared = CitationDetailCache()
    var held: [String: PageCitationDetail] = [:]
    /// The blocks each page's held popovers were read under.
    private var under: [String: PageBlocks] = [:]

    /// The card's page now has `blocks`: anything held from other blocks is forgotten.
    func track(_ entityId: String, blocks: PageBlocks?) {
        guard let blocks else { return }
        if let previous = under[entityId], previous == blocks { return }
        if under[entityId] != nil { forget(entityId) }
        under[entityId] = blocks
        if under.count > 64 { under = [entityId: blocks] }
    }

    func forget(_ entityId: String) {
        held = held.filter { !$0.key.hasPrefix(entityId + "|") }
        if held.count > 400 { held.removeAll() }
    }
}
