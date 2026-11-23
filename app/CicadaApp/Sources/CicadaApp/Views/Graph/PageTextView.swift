import AppKit
import SwiftUI

// MARK: - The article's text engine (owner 2026-11-23: "ok rebuild"; DESIGN_RULES §9)
//
// A run of the article is one `NSTextView` on TextKit 2. A chip and the source cluster are text attachments whose views
// are the SwiftUI views the page always drew; the engine gives every Mac text behaviour for free: dragging across words,
// chips and quiet links and from one paragraph into the next, double and triple click, shift-click, ⌘C, Look Up and
// Services. What is copied is the prose (`PageText.plainKey`).

/// What an attachment draws.
enum PageAttachmentContent: Equatable {
    case chip(PageLinkChip.Face, URL)
    case cluster(SourceClusterModel, [CiteKey])
}

/// What the hosted views need from the SwiftUI environment they cannot inherit (an attachment's view lives inside an
/// AppKit view), and the one measure cache of their sizes. One per run, owned by its coordinator.
@MainActor
final class PageAttachmentContext {
    var store: Store?
    var router: ProvenanceRouter?
    var openURL: OpenURLAction?
    var entityId: String?
    weak var textView: PageTextView?
    private var sizes: [String: CGSize] = [:]

    /// The gap before the cluster: the breathing room the flow gave it after the last word.
    static var clusterLead: CGFloat { CicadaTheme.scaled(5) }

    func root(_ content: PageAttachmentContent) -> AnyView {
        var view: AnyView
        switch content {
        case .chip(let face, let url):
            view = AnyView(PageLinkChip(face: face, url: url, entityId: entityId))
        case .cluster(let model, let keys):
            view = entityId.map { id in
                AnyView(SourceCluster(model: model, keys: keys, entityId: id).padding(.leading, Self.clusterLead))
            } ?? AnyView(EmptyView())
        }
        view = AnyView(view.environment(store).environment(router))
        if let openURL { view = AnyView(view.environment(\.openURL, openURL)) }
        return view
    }

    /// What decides a view's size apart from its content: the picture a chip wears and the type scale.
    func key(_ content: PageAttachmentContent) -> String {
        let scale = CicadaTheme.uiScale
        switch content {
        case .chip(.page(let target), let url):
            let picture = store.map { !EntityPictureLayout.isEmpty(target.type, picture: $0.picture(for: target.id)) } ?? false
            return "p|\(target.id)|\(target.name)|\(picture)|\(url.absoluteString)|\(scale)"
        case .chip(.web(let label), let url):
            return "w|\(label)|\(PageChipMark.bundled(url: url) ?? "")|\(url.host ?? "")|\(scale)"
        case .cluster(let model, _):
            return "c|\(model.marks.joined(separator: ","))|\(model.more)|\(model.total)|\(scale)"
        }
    }

    func size(of content: PageAttachmentContent) -> CGSize {
        let key = key(content)
        if let size = sizes[key] { return size }
        var size = analytic(content) ?? NSHostingView(rootView: root(content)).fittingSize
        size.width = ceil(size.width)
        size.height = ceil(size.height)
        sizes[key] = size
        return size
    }

    /// A page chip's size from its parts — the picture's well, the name set in the body face, the padding
    /// `PageLinkChip` gives them — so a page of chips costs no view to measure. A web chip's picture can arrive later
    /// (`resized`), so it is measured by its view. One point of slack keeps the name from truncating on a rounding.
    private func analytic(_ content: PageAttachmentContent) -> CGSize? {
        guard case .chip(.page(let target), _) = content, let store else { return nil }
        let font = NSFont.systemFont(ofSize: CicadaTheme.scaled(14))
        let text = (target.name as NSString).size(withAttributes: [.font: font])
        let hasPicture = !EntityPictureLayout.isEmpty(target.type, picture: store.picture(for: target.id))
        let side = CicadaTheme.scaled(16)
        let lead = hasPicture ? EntityPictureLayout.frame(target.type, size: side).width + CicadaTheme.scaled(8)
                              : CicadaTheme.scaled(6)
        let line = font.ascender - font.descender + font.leading
        return CGSize(width: lead + text.width + CicadaTheme.scaled(6) + 1, height: line)
    }

    /// A hosted view grew or shrank (a picture arrived): remember it and lay the text out again.
    func resized(_ content: PageAttachmentContent, to size: CGSize) {
        let key = key(content)
        guard sizes[key] != size else { return }
        sizes[key] = size
        textView?.attachmentsChanged()
    }
}

/// An inline view in the text: a chip or the cluster.
final class PageInlineAttachment: NSTextAttachment {
    let content: PageAttachmentContent
    let font: NSFont
    let context: PageAttachmentContext

    init(content: PageAttachmentContent, font: NSFont, context: PageAttachmentContext) {
        self.content = content
        self.font = font
        self.context = context
        super.init(data: nil, ofType: nil)
    }

    required init?(coder: NSCoder) { fatalError("PageInlineAttachment is never decoded") }

    override func viewProvider(for parentView: NSView?, location: NSTextLocation,
                               textContainer: NSTextContainer?) -> NSTextAttachmentViewProvider? {
        let provider = PageAttachmentProvider(textAttachment: self, parentView: parentView,
                                              textLayoutManager: textContainer?.textLayoutManager, location: location)
        provider.tracksTextAttachmentViewBounds = true
        return provider
    }
}

/// A hosting view that says when its content changes size (a picture arrives after the chip was measured).
final class PageAttachmentHost: NSHostingView<AnyView> {
    var onResize: ((CGSize) -> Void)?

    override func invalidateIntrinsicContentSize() {
        super.invalidateIntrinsicContentSize()
        guard let onResize else { return }
        let size = CGSize(width: ceil(fittingSize.width), height: ceil(fittingSize.height))
        DispatchQueue.main.async { onResize(size) }
    }
}

final class PageAttachmentProvider: NSTextAttachmentViewProvider {
    private var attachment: PageInlineAttachment? { textAttachment as? PageInlineAttachment }

    override func loadView() {
        guard let attachment else { return }
        let host = PageAttachmentHost(rootView: MainActor.assumeIsolated { attachment.context.root(attachment.content) })
        host.onResize = { [weak attachment] size in
            guard let attachment else { return }
            MainActor.assumeIsolated { attachment.context.resized(attachment.content, to: size) }
        }
        view = host
    }

    override func attachmentBounds(for attributes: [NSAttributedString.Key: Any], location: NSTextLocation,
                                   textContainer: NSTextContainer?, proposedLineFragment: CGRect,
                                   position: CGPoint) -> CGRect {
        guard let attachment else { return .zero }
        return MainActor.assumeIsolated {
            let size = attachment.context.size(of: attachment.content)
            // The view's text baseline sits `descent` above its bottom edge, so it lands on the line's own baseline.
            let descent: CGFloat
            switch attachment.content {
            case .chip: descent = -attachment.font.descender
            case .cluster: descent = size.height / 2 - CicadaTheme.scaled(4)
            }
            return CGRect(x: 0, y: -descent, width: size.width, height: size.height)
        }
    }
}

/// A quote's paragraph draws its rule at the leading edge, the height of its lines.
final class PageLayoutFragment: NSTextLayoutFragment {
    var quote = false

    private var rule: CGRect {
        guard let first = textLineFragments.first, let last = textLineFragments.last else { return .zero }
        return CGRect(x: 0, y: first.typographicBounds.minY, width: 3,
                      height: last.typographicBounds.maxY - first.typographicBounds.minY)
    }

    override var renderingSurfaceBounds: CGRect {
        quote ? super.renderingSurfaceBounds.union(rule) : super.renderingSurfaceBounds
    }

    override func draw(at point: CGPoint, in context: CGContext) {
        if quote {
            context.setFillColor(NSColor(CicadaTheme.ring(.strong)).cgColor)
            context.fill(rule.offsetBy(dx: point.x, dy: point.y))
        }
        super.draw(at: point, in: context)
    }
}

/// The article's text: selectable, never editable, copies prose.
final class PageTextView: NSTextView {
    var document: PageTextDocument?
    /// The width the height was last measured at, and that height.
    private var measured: (width: CGFloat, height: CGFloat)?
    /// Told when the rows' frames change (the 🔗 buttons follow them).
    var onRowFrames: (([Int: CGRect]) -> Void)?
    var watchedRows: Set<Int> = []
    var onHoverRow: ((Int?) -> Void)?
    var onMenu: ((Int) -> NSMenu?)?
    private var hoveredGroup: Int?
    private var lastFrames: [Int: CGRect] = [:]

    convenience init() {
        self.init(usingTextLayoutManager: true)
        isEditable = false
        isSelectable = true
        isRichText = true
        importsGraphics = false
        allowsUndo = false
        drawsBackground = false
        isVerticallyResizable = false
        isHorizontallyResizable = false
        textContainerInset = .zero
        textContainer?.lineFragmentPadding = 0
        textContainer?.widthTracksTextView = true
        linkTextAttributes = [:]
        isAutomaticLinkDetectionEnabled = false
        isAutomaticSpellingCorrectionEnabled = false
        usesFontPanel = false
        setAccessibilityRole(.staticText)
    }

    // MARK: Size

    /// The height of the whole run at `width`: laid out once, here.
    func height(for width: CGFloat) -> CGFloat {
        if let measured, measured.width == width { return measured.height }
        textContainer?.size = NSSize(width: width, height: .greatestFiniteMagnitude)
        guard let layout = textLayoutManager else { return 0 }
        layout.ensureLayout(for: layout.documentRange)
        let height = ceil(layout.usageBoundsForTextContainer.height)
        measured = (width, height)
        return height
    }

    func invalidateMeasure() { measured = nil }

    /// An attachment's view changed size: lay the text out again and say so to SwiftUI.
    func attachmentsChanged() {
        guard let layout = textLayoutManager else { return }
        invalidateMeasure()
        layout.invalidateLayout(for: layout.documentRange)
        invalidateIntrinsicContentSize()
        needsLayout = true
        scheduleRowFrames()
    }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        scheduleRowFrames()
    }

    // MARK: Rows

    private var framesScheduled = false

    func scheduleRowFrames() {
        guard !watchedRows.isEmpty, !framesScheduled else { return }
        framesScheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.framesScheduled = false
            self.reportRowFrames()
        }
    }

    private func reportRowFrames() {
        guard let document, let layout = textLayoutManager, let storage = textContentStorage else { return }
        var frames: [Int: CGRect] = [:]
        for row in document.rows where watchedRows.contains(row.id) {
            guard let start = storage.location(storage.documentRange.location, offsetBy: row.range.location),
                  let end = storage.location(start, offsetBy: max(row.range.length, 1)),
                  let range = NSTextRange(location: start, end: end) else { continue }
            var rect = CGRect.null
            layout.enumerateTextSegments(in: range, type: .standard, options: []) { _, frame, _, _ in
                rect = rect.union(frame)
                return true
            }
            if !rect.isNull { frames[row.id] = rect }
        }
        guard frames != lastFrames else { return }
        lastFrames = frames
        onRowFrames?(frames)
    }

    // MARK: Copy

    private func prose(_ range: NSRange) -> String { document?.plain(range) ?? "" }

    override var writablePasteboardTypes: [NSPasteboard.PasteboardType] { [.string] }

    override func writeSelection(to pboard: NSPasteboard, types: [NSPasteboard.PasteboardType]) -> Bool {
        let range = selectedRange()
        guard range.length > 0 else { return false }
        pboard.declareTypes([.string], owner: nil)
        return pboard.setString(prose(range), forType: .string)
    }

    override func copy(_ sender: Any?) {
        let range = selectedRange()
        guard range.length > 0 else { return }
        AppPasteboard.copy(prose(range))
    }

    /// A selection leaves when the person selects in another run, not lingering greyed out beside the new one.
    override func resignFirstResponder() -> Bool {
        let resigned = super.resignFirstResponder()
        if resigned, selectedRange().length > 0 { setSelectedRange(NSRange(location: selectedRange().location, length: 0)) }
        return resigned
    }

    // MARK: Pointer

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas where area.owner === self { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow,
                                                               .inVisibleRect], owner: self))
    }

    override func mouseMoved(with event: NSEvent) {
        super.mouseMoved(with: event)
        let index = characterIndex(for: event)
        let group = index.flatMap { i in
            (textStorage?.attribute(PageText.groupKey, at: i, effectiveRange: nil) as? Int)
        }
        setHovered(group: group)
        onHoverRow?(index.flatMap { document?.row(at: $0) })
    }

    override func mouseExited(with event: NSEvent) {
        super.mouseExited(with: event)
        setHovered(group: nil)
        onHoverRow?(nil)
    }

    private func characterIndex(for event: NSEvent) -> Int? {
        let point = convert(event.locationInWindow, from: nil)
        guard bounds.contains(point), let layout = textLayoutManager, let storage = textContentStorage else { return nil }
        guard let fragment = layout.textLayoutFragment(for: point) else { return nil }
        var local = point
        local.x -= fragment.layoutFragmentFrame.minX
        local.y -= fragment.layoutFragmentFrame.minY
        for line in fragment.textLineFragments where line.typographicBounds.contains(local) {
            let inLine = line.characterIndex(for: CGPoint(x: local.x - line.typographicBounds.minX,
                                                           y: local.y - line.typographicBounds.minY))
            guard inLine != NSNotFound else { return nil }
            let base = storage.offset(from: storage.documentRange.location, to: fragment.rangeInElement.location)
            return base + inLine
        }
        return nil
    }

    /// The words of the link under the pointer take the soft fill together (`bgHover`), as the quiet link always did.
    private func setHovered(group: Int?) {
        guard group != hoveredGroup, let storage = textStorage, let document else { return }
        storage.beginEditing()
        if let old = hoveredGroup {
            for range in document.groups[old] ?? [] { storage.removeAttribute(.backgroundColor, range: range) }
        }
        if let group {
            for range in document.groups[group] ?? [] {
                storage.addAttribute(.backgroundColor, value: NSColor(CicadaTheme.bgHover), range: range)
            }
        }
        storage.endEditing()
        hoveredGroup = group
    }

    // MARK: Menu

    override func menu(for event: NSEvent) -> NSMenu? {
        let base = super.menu(for: event)
        guard let index = characterIndex(for: event), let row = document?.row(at: index), let extra = onMenu?(row),
              extra.numberOfItems > 0 else { return base }
        let menu = base ?? NSMenu()
        menu.insertItem(.separator(), at: 0)
        for item in extra.items.reversed() {
            extra.removeItem(item)
            menu.insertItem(item, at: 0)
        }
        return menu
    }
}

/// The run as a SwiftUI view: one text view, sized to its width.
struct PageTextRunView: NSViewRepresentable {
    let paragraphs: [PageTextParagraph]
    /// What a rebuild also depends on: the type scale and the theme.
    let look: String
    let entityId: String?
    /// The rows whose frames the host wants (the ones that carry web links).
    let watched: Set<Int>
    var onRowFrames: ([Int: CGRect]) -> Void = { _ in }
    var onHoverRow: (Int?) -> Void = { _ in }
    var onMenu: (Int) -> NSMenu? = { _ in nil }

    @Environment(Store.self) private var store: Store?
    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @Environment(\.openURL) private var openURL

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate, NSTextLayoutManagerDelegate {
        let context = PageAttachmentContext()
        var paragraphs: [PageTextParagraph] = []
        var look = ""
        var openURL: OpenURLAction?

        func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
            guard let url = link as? URL ?? (link as? String).flatMap(URL.init(string:)) else { return false }
            openURL?(url)
            return true
        }

        func textLayoutManager(_ textLayoutManager: NSTextLayoutManager, textLayoutFragmentFor location: NSTextLocation,
                               in textElement: NSTextElement) -> NSTextLayoutFragment {
            let fragment = PageLayoutFragment(textElement: textElement, range: textElement.elementRange)
            if let paragraph = textElement as? NSTextParagraph, paragraph.attributedString.length > 0 {
                fragment.quote = paragraph.attributedString.attribute(PageText.quoteKey, at: 0, effectiveRange: nil) as? Bool == true
            }
            return fragment
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> PageTextView {
        let view = PageTextView()
        view.delegate = context.coordinator
        view.textLayoutManager?.delegate = context.coordinator
        context.coordinator.context.textView = view
        return view
    }

    func updateNSView(_ view: PageTextView, context: Context) {
        let coordinator = context.coordinator
        coordinator.openURL = openURL
        let env = coordinator.context
        env.store = store
        env.router = router
        env.openURL = openURL
        env.entityId = entityId
        view.onRowFrames = onRowFrames
        view.onHoverRow = onHoverRow
        view.onMenu = onMenu
        view.watchedRows = watched
        if coordinator.paragraphs != paragraphs || coordinator.look != look {
            coordinator.paragraphs = paragraphs
            coordinator.look = look
            let document = PageText.build(paragraphs, context: env)
            view.document = document
            view.invalidateMeasure()
            view.textStorage?.setAttributedString(document.text)
            view.invalidateIntrinsicContentSize()
            view.scheduleRowFrames()
        }
    }

    func sizeThatFits(_ proposal: ProposedViewSize, nsView: PageTextView, context: Context) -> CGSize? {
        let width = proposal.width.map { $0.isFinite ? $0 : 480 } ?? 480
        return CGSize(width: width, height: nsView.height(for: max(width, 1)))
    }
}
