import AppKit
import SwiftUI

/// Owner 2026-11-23: in every chat, app-wide, scrolling up from the newest message shows a round button with a down
/// arrow that takes you back to it. Each chat keeps its own scroll view and adds three things: `JumpToLatestAnchor` right
/// after its newest row, `.jumpToLatestSpace(_:)` on its scroll content, and `.jumpToLatest(anchorY:away:scroller:)` on
/// the scroll view, which draws the button over its bottom edge while the view sits above the newest message.
///
/// "Above" is how far the anchor sits below the scroll view's visible bottom, both read from AppKit — the anchor's own
/// `NSView` in the scroll view's document, and the clip's bounds — each time the view moves or its content changes
/// (`JumpToLatestScroller`), never from SwiftUI geometry. Two SwiftUI measures were tried and both failed in the
/// running app (2026-11-25): the anchor's place in the content against the scroll geometry's visible rectangle are not
/// one coordinate system while unmeasured lazy rows sit above (a constant 1,308 pt apart with the view at its very end,
/// so the button showed there); and an anchor that measures itself goes silent once the lazy stack drops it, so a move
/// back to the end in one step left the button showing. The document's end is not the measure either: the Reader draws
/// more under a conversation, and the newest message is where the anchor is. A lazy stack drops the anchor when it is
/// off screen; a chat that had one and has none now is away.
///
/// D (DESIGN_RULES §9): a circle in the other side's bubble fill with the strong ring, never a shadow (DR-9, DR-10) and
/// never the accent (DR-5); the glyph alone carries it, its words in `.help` and the accessibility label. Appearing and
/// the glide follow `CicadaMotion` (a click, never a key: DR-60), one frame under Reduce Motion.
enum JumpToLatest {
    static let diameter: CGFloat = 34
    /// How far above the newest message the view sits before the button shows.
    static let threshold: CGFloat = 80
    static let space = "chat.content"
    /// The button's distance from the chat's bottom edge (owner 2026-11-23: "a bit more up").
    static let lift: CGFloat = 32

    /// Whether a view whose visible bottom is `distanceFromEnd` points above the newest message's end sits away from it.
    static func isAway(distanceFromEnd: CGFloat) -> Bool {
        distanceFromEnd > CicadaTheme.scaled(threshold)
    }
}

/// Right after the chat's newest row: reports that a chat is laid out (`anchorY` non-nil; the button never shows over a
/// scroll view that draws no chat) and carries the `NSView` the scroller measures (`JumpToLatestAnchorProbe`). `away`
/// is the scroll view's to say (`JumpToLatestScroller`); the binding stays so every chat passes one pair.
struct JumpToLatestAnchor: View {
    @Binding var anchorY: CGFloat?
    @Binding var away: Bool

    var body: some View {
        Color.clear
            .frame(height: 1)
            .background(Probe().accessibilityHidden(true))
            .accessibilityHidden(true)
            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named(JumpToLatest.space)).minY } action: { y in
                if anchorY != y { anchorY = y }
            }
    }

    private struct Probe: NSViewRepresentable {
        func makeNSView(context: Context) -> JumpToLatestAnchorProbe { JumpToLatestAnchorProbe(frame: .zero) }
        func updateNSView(_ view: JumpToLatestAnchorProbe, context: Context) {}
    }
}

/// The anchor's own view inside the scroll view's document: where the newest message ends, in AppKit's coordinates. It
/// tells the scroller of its scroll view when it arrives, moves or leaves (a lazy stack dropped the anchor's row).
final class JumpToLatestAnchorProbe: NSView {
    private weak var listed: NSScrollView?

    override func viewDidMoveToSuperview() {
        super.viewDidMoveToSuperview()
        MainActor.assumeIsolated { relist() }
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        MainActor.assumeIsolated { relist() }
    }

    override func setFrameOrigin(_ origin: NSPoint) {
        super.setFrameOrigin(origin)
        MainActor.assumeIsolated { JumpToLatestScroller.moved(in: enclosingScrollView) }
    }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    @MainActor private func relist() {
        let now = enclosingScrollView
        if let listed, listed !== now { JumpToLatestScroller.unlist(self, from: listed) }
        listed = now
        if let now { JumpToLatestScroller.list(self, in: now) }
    }
}

struct JumpToLatestButton: View {
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: "arrow.down")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textPrimary)
                .frame(width: CicadaTheme.scaled(JumpToLatest.diameter), height: CicadaTheme.scaled(JumpToLatest.diameter))
                .background(Circle().fill(hovering ? CicadaTheme.bgSelected : CicadaTheme.chatBubbleOtherFill))
                .overlay(Circle().strokeBorder(CicadaTheme.ring(.strong), lineWidth: 1))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .help(Copy.ChatPage.jumpToLatest)
        .accessibilityLabel(Copy.ChatPage.jumpToLatest)
    }
}

/// Drives the chat's own scroll view to its very end — the newest message and whatever the chat draws under it — with a
/// glide (`CicadaMotion.jumpToLatestDuration`), and in one frame under Reduce Motion. Held by the chat (`@State`), found
/// by `JumpToLatestLocator` inside its content. A lazy stack's height is an estimate until the rows on the way are
/// measured, so it settles on the measured end afterwards, at most a few short steps.
@MainActor
final class JumpToLatestScroller {
    weak var scrollView: NSScrollView? {
        didSet { if scrollView !== oldValue { watch() } }
    }
    /// The chat's `away`, told each time the view crosses the threshold (set by `.jumpToLatest`).
    var onAway: ((Bool) -> Void)? {
        didSet { told = nil; judgeSoon() }
    }
    private var gliding = false
    private let watching = Watching()
    private var pending = false
    private var told: Bool?
    /// A chat that had an anchor and has none now: its lazy stack dropped the row, so the view is not at it.
    private var hadAnchor = false

    // MARK: Which anchor and which scroller belong to a scroll view

    private struct Listed {
        weak var scrollView: NSScrollView?
        weak var probe: JumpToLatestAnchorProbe?
        weak var scroller: JumpToLatestScroller?
    }
    private static var listed: [ObjectIdentifier: Listed] = [:]

    private static func entry(_ scrollView: NSScrollView) -> Listed {
        let key = ObjectIdentifier(scrollView)
        if let found = listed[key], found.scrollView === scrollView { return found }
        listed = listed.filter { $0.value.scrollView != nil }      // an address reused by a new scroll view
        return Listed(scrollView: scrollView)
    }

    static func list(_ probe: JumpToLatestAnchorProbe, in scrollView: NSScrollView) {
        var found = entry(scrollView)
        found.probe = probe
        listed[ObjectIdentifier(scrollView)] = found
        found.scroller?.judgeSoon()
    }

    /// Only the anchor that is listed leaves: an old anchor dying after its replacement arrived changes nothing.
    static func unlist(_ probe: JumpToLatestAnchorProbe, from scrollView: NSScrollView) {
        var found = entry(scrollView)
        guard found.probe === probe else { return }
        found.probe = nil
        listed[ObjectIdentifier(scrollView)] = found
        found.scroller?.judgeSoon()
    }

    static func moved(in scrollView: NSScrollView?) {
        guard let scrollView else { return }
        entry(scrollView).scroller?.judgeSoon()
    }

    /// The observers, removed with the scroller (a plain class: its `deinit` needs no actor).
    private final class Watching {
        var tokens: [NSObjectProtocol] = []
        func clear() {
            tokens.forEach(NotificationCenter.default.removeObserver)
            tokens = []
        }
        deinit { clear() }
    }

    /// Every way the distance from the end changes: the view scrolled (the clip's bounds), the content grew or was
    /// re-measured (the document's frame), the window resized (the clip's frame).
    private func watch() {
        watching.clear()
        told = nil
        hadAnchor = false
        guard let scrollView else { return }
        var found = Self.entry(scrollView)
        found.scroller = self
        Self.listed[ObjectIdentifier(scrollView)] = found
        let clip = scrollView.contentView
        clip.postsBoundsChangedNotifications = true
        clip.postsFrameChangedNotifications = true
        var watched: [(NSNotification.Name, NSView)] = [(NSView.boundsDidChangeNotification, clip),
                                                        (NSView.frameDidChangeNotification, clip)]
        if let document = scrollView.documentView {
            document.postsFrameChangedNotifications = true
            watched.append((NSView.frameDidChangeNotification, document))
        }
        for (name, view) in watched {
            watching.tokens.append(NotificationCenter.default.addObserver(forName: name, object: view, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.judgeSoon() }
            })
        }
        judgeSoon()
    }

    /// Once per turn of the main queue, after everything in it moved: content that grows and is scrolled to its end
    /// in the same pass (a new line in a chat pinned to the bottom) is judged where it came to rest, so the button
    /// never flashes, and SwiftUI state is never written during a layout pass.
    private func judgeSoon() {
        guard !pending else { return }
        pending = true
        DispatchQueue.main.async { [weak self] in self?.judge() }
    }

    private func judge() {
        pending = false
        guard let scrollView, let document = scrollView.documentView else { return }
        let clip = scrollView.contentView
        let away: Bool
        if let probe = Self.entry(scrollView).probe, probe.enclosingScrollView === scrollView {
            // The anchor's top edge in the document against the visible bottom (SwiftUI's document view is flipped).
            hadAnchor = true
            let anchor = probe.convert(probe.bounds, to: document)
            let below = document.isFlipped ? anchor.minY - clip.bounds.maxY : clip.bounds.minY - anchor.maxY
            away = JumpToLatest.isAway(distanceFromEnd: below)
        } else if hadAnchor {
            away = true
        } else {
            // No anchor yet (the chat is still laying out): the document's own end.
            away = JumpToLatest.isAway(distanceFromEnd: abs(Self.end(clip: clip, document: document) - clip.bounds.origin.y))
        }
        guard away != told else { return }
        told = away
        onAway?(away)
    }

    func jumpToEnd() {
        guard !gliding, let scrollView, let document = scrollView.documentView else { return }
        let clip = scrollView.contentView
        let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        let end = Self.end(clip: clip, document: document)
        let distance = abs(end - clip.bounds.origin.y)
        guard distance > 1 else { return }
        if reduceMotion {
            set(clip, y: end, in: scrollView)
            settle(scrollView, steps: 3, animated: false)
            return
        }
        // A long way down starts close to the end at once; the glide covers the rest.
        let glide = clip.bounds.height * CicadaMotion.jumpToLatestGlideScreens
        if distance > glide {
            set(clip, y: document.isFlipped ? end - glide : end + glide, in: scrollView)
        }
        gliding = true
        animate(clip, to: Self.end(clip: clip, document: document), in: scrollView,
                over: CicadaMotion.jumpToLatestDuration(distance: distance)) { [weak self] in
            self?.gliding = false
            self?.settle(scrollView, steps: 3, animated: true)
        }
    }

    /// The clip's origin at the document's end (SwiftUI's document view is flipped; an unflipped one ends at 0).
    private static func end(clip: NSClipView, document: NSView) -> CGFloat {
        document.isFlipped ? max(0, document.frame.height - clip.bounds.height) : 0
    }

    private func set(_ clip: NSClipView, y: CGFloat, in scrollView: NSScrollView) {
        clip.setBoundsOrigin(NSPoint(x: clip.bounds.origin.x, y: y))
        scrollView.reflectScrolledClipView(clip)
    }

    private func animate(_ clip: NSClipView, to y: CGFloat, in scrollView: NSScrollView, over seconds: TimeInterval,
                         done: @escaping @MainActor () -> Void) {
        NSAnimationContext.runAnimationGroup { context in
            context.duration = seconds
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            context.allowsImplicitAnimation = true
            clip.animator().setBoundsOrigin(NSPoint(x: clip.bounds.origin.x, y: y))
        } completionHandler: {
            Task { @MainActor in
                scrollView.reflectScrolledClipView(clip)
                done()
            }
        }
    }

    /// The rows the glide passed are measured now and the end may have moved: follow it, a frame at a time.
    private func settle(_ scrollView: NSScrollView, steps: Int, animated: Bool) {
        guard steps > 0 else { return }
        Task { @MainActor in
            await Task.yield()
            guard let document = scrollView.documentView else { return }
            let clip = scrollView.contentView
            let end = Self.end(clip: clip, document: document)
            guard abs(end - clip.bounds.origin.y) > 1 else { return }
            if animated {
                animate(clip, to: end, in: scrollView, over: CicadaMotion.jumpToLatestSettleDuration) { [weak self] in
                    self?.settle(scrollView, steps: steps - 1, animated: true)
                }
            } else {
                set(clip, y: end, in: scrollView)
                settle(scrollView, steps: steps - 1, animated: false)
            }
        }
    }
}

/// Inside the chat's scroll content (a background, so it is always laid out): hands the enclosing scroll view to the
/// chat's `JumpToLatestScroller`.
struct JumpToLatestLocator: NSViewRepresentable {
    let scroller: JumpToLatestScroller

    func makeNSView(context: Context) -> NSView { Probe(scroller: scroller) }
    func updateNSView(_ view: NSView, context: Context) {
        (view as? Probe)?.scroller = scroller
        if scroller.scrollView == nil { scroller.scrollView = view.enclosingScrollView }
    }

    private final class Probe: NSView {
        var scroller: JumpToLatestScroller
        init(scroller: JumpToLatestScroller) {
            self.scroller = scroller
            super.init(frame: .zero)
        }
        @available(*, unavailable) required init?(coder: NSCoder) { fatalError() }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            MainActor.assumeIsolated { scroller.scrollView = enclosingScrollView }
        }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
    }
}

extension View {
    /// The chat's scroll content, outermost inside its `ScrollView`: the space the anchor and the visible rectangle share,
    /// and where the scroller finds its scroll view.
    func jumpToLatestSpace(_ scroller: JumpToLatestScroller) -> some View {
        coordinateSpace(.named(JumpToLatest.space))
            .background(JumpToLatestLocator(scroller: scroller).accessibilityHidden(true))
    }

    /// The chat's scroll view: while it sits above its end (`scroller` says so, into `away`), the button over its
    /// bottom edge glides it there.
    /// `willJump` runs first: a scroll view whose position is bound (`scrollPosition(id:)`) lets go of it there, or SwiftUI
    /// puts the view back on the bound row while it glides.
    func jumpToLatest(anchorY: CGFloat?, away: Binding<Bool>, scroller: JumpToLatestScroller,
                      willJump: (() -> Void)? = nil) -> some View {
        modifier(JumpToLatestModifier(anchorY: anchorY, away: away, scroller: scroller, willJump: willJump))
    }
}
private struct JumpToLatestModifier: ViewModifier {
    let anchorY: CGFloat?
    @Binding var away: Bool
    let scroller: JumpToLatestScroller
    let willJump: (() -> Void)?

    func body(content: Content) -> some View {
        content
            .overlay(alignment: .bottom) {
                // `anchorY` nil: this scroll view draws no chat now (the Reader on a note), whatever a chat left behind.
                if away, anchorY != nil {
                    JumpToLatestButton {
                        willJump?()
                        scroller.jumpToEnd()
                    }
                    .padding(.bottom, CicadaTheme.scaled(JumpToLatest.lift))
                }
            }
            .onAppear {
                scroller.onAway = { isAway in
                    if away != isAway { away = isAway }
                }
            }
    }
}
