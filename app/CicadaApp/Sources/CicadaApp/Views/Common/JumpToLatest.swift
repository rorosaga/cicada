import AppKit
import SwiftUI

/// Owner 2026-11-23: in every chat, app-wide, scrolling up from the newest message shows a round button with a down
/// arrow that takes you back to it. Each chat keeps its own scroll view and adds three things: `JumpToLatestAnchor` right
/// after its newest row, `.jumpToLatestSpace(_:)` on its scroll content, and `.jumpToLatest(anchorY:away:scroller:)` on
/// the scroll view, which draws the button over its bottom edge while the view sits above the newest message.
///
/// "Above" is the anchor's laid-out position in the content against the visible rectangle's bottom, both in the content's
/// own coordinates — never the scroll's content height: a lazy stack's height is an estimate that can sit hundreds of
/// points past the real end, so a height test never sees the bottom (measured on a meeting). A lazy stack drops the
/// anchor when it is far off screen; its last position stands, and it is far below, so the button shows.
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

    /// Whether a view whose visible bottom is `visibleBottom` sits away from an anchor at `anchorY` (same coordinates).
    static func isAway(anchorY: CGFloat?, visibleBottom: CGFloat) -> Bool {
        guard let anchorY else { return false }
        return anchorY - visibleBottom > CicadaTheme.scaled(threshold)
    }
}

/// Right after the chat's newest row: reports where it sits in the chat's content (`JumpToLatest.space`). Before macOS
/// 15 (no scroll geometry) its leaving the lazy stack sets `away` instead.
struct JumpToLatestAnchor: View {
    @Binding var anchorY: CGFloat?
    @Binding var away: Bool

    var body: some View {
        Color.clear
            .frame(height: 1)
            .accessibilityHidden(true)
            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named(JumpToLatest.space)).minY } action: { y in
                if anchorY != y { anchorY = y }
            }
            .modifier(Fallback(away: $away))
    }

    private struct Fallback: ViewModifier {
        @Binding var away: Bool
        func body(content: Content) -> some View {
            if #available(macOS 15, *) {
                content
            } else {
                content.onAppear { away = false }.onDisappear { away = true }
            }
        }
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
    weak var scrollView: NSScrollView?
    private var gliding = false

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

    /// The chat's scroll view: while the view sits above `anchorY` (macOS 15+, from its geometry; `away` before), the
    /// button over its bottom edge glides it to its very end.
    /// `willJump` runs first: a scroll view whose position is bound (`scrollPosition(id:)`) lets go of it there, or SwiftUI
    /// puts the view back on the bound row while it glides.
    func jumpToLatest(anchorY: CGFloat?, away: Binding<Bool>, scroller: JumpToLatestScroller,
                      willJump: (() -> Void)? = nil) -> some View {
        modifier(JumpToLatestModifier(anchorY: anchorY, away: away, jump: {
            willJump?()
            scroller.jumpToEnd()
        }))
    }
}
private struct JumpToLatestModifier: ViewModifier {
    let anchorY: CGFloat?
    @Binding var away: Bool
    let jump: () -> Void

    func body(content: Content) -> some View {
        tracked(content)
            .overlay(alignment: .bottom) {
                if away {
                    JumpToLatestButton(action: jump)
                        .padding(.bottom, CicadaTheme.scaled(JumpToLatest.lift))
                }
            }
    }

    @ViewBuilder
    private func tracked(_ content: Content) -> some View {
        if #available(macOS 15, *) {
            content.onScrollGeometryChange(for: Bool.self) { geo in
                JumpToLatest.isAway(anchorY: anchorY, visibleBottom: geo.visibleRect.maxY)
            } action: { _, isAway in
                if isAway != away { away = isAway }
            }
        } else {
            content
        }
    }
}

