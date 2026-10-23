import AppKit
import QuartzCore

/// Owner 2026-10-23 — on the *Meet your bookworm* step's Continue, the worm "appears in the taskbar": it shrinks and
/// flies from the step to its place in the menu bar, and the real status item takes over where it lands.
///
/// **Why a panel.** The main window cannot draw outside its own frame, and the menu bar sits above every normal
/// window, so a SwiftUI animation inside the step could only shrink the worm toward the window's top edge. A transient
/// borderless `NSPanel` can be placed anywhere on screen and one level above the menu bar (the ask-why panel's level,
/// `.mainMenu + 3`, still under menus): it is born exactly over the step's big worm, its frame is animated by AppKit to
/// the status item's button frame, and it is ordered out when the real item is shown under it. It never activates the
/// app, never takes a click (`ignoresMouseEvents`), has no shadow (depth is a ring, DR-9/DR-10), and draws the sprite
/// through a layer with nearest-neighbour filters, so every frame of the shrink stays crisp pixel art.
@MainActor
final class MenuBarFlight {
    static let level = NSWindow.Level(rawValue: NSWindow.Level.mainMenu.rawValue + 3)

    private var panel: NSPanel?

    /// A `size` × `size` square centred in `frame` (the status item's sprite inside its wider button).
    nonisolated static func centred(size: CGFloat, in frame: CGRect) -> CGRect {
        CGRect(x: frame.midX - size / 2, y: frame.midY - size / 2, width: size, height: size)
    }

    func fly(image: CGImage, from start: CGRect, to end: CGRect, completion: @escaping @MainActor () -> Void) {
        let panel = FlightPanel(contentRect: start, styleMask: [.borderless, .nonactivatingPanel],
                                backing: .buffered, defer: false)
        panel.level = Self.level
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle, .transient]

        let view = NSView(frame: CGRect(origin: .zero, size: start.size))
        view.autoresizingMask = [.width, .height]
        view.wantsLayer = true
        let layer = CALayer()
        layer.contents = image
        layer.contentsGravity = .resize
        layer.magnificationFilter = .nearest
        layer.minificationFilter = .nearest
        view.layer = layer
        panel.contentView = view
        panel.setFrame(start, display: true)
        panel.orderFrontRegardless()
        self.panel = panel

        NSAnimationContext.runAnimationGroup { context in
            context.duration = CicadaMotion.wormFlightDuration
            let c = CicadaMotion.wormFlightCurve
            context.timingFunction = CAMediaTimingFunction(controlPoints: c.0, c.1, c.2, c.3)
            panel.animator().setFrame(end, display: true)
        } completionHandler: { [weak self] in
            MainActor.assumeIsolated {
                completion()
                // One turn later, so the real item has drawn under the panel before the panel goes. The panel is held
                // here, not through `self`: the owner may drop this flight in `completion` (seen live 2026-10-23: a
                // weak `self` left the 18 pt panel on screen).
                DispatchQueue.main.async {
                    panel.orderOut(nil)
                    self?.panel = nil
                }
            }
        }
    }

    /// Whether a landing rect is on a screen's top band — the menu bar. A full menu bar (a notch with many items)
    /// keeps a status item off every screen while its frame still reads as a rect; the worm is then just shown.
    nonisolated static func landsOnMenuBar(_ rect: CGRect, screens: [CGRect]) -> Bool {
        screens.contains { screen in
            screen.contains(CGPoint(x: rect.midX, y: rect.midY)) && rect.maxY >= screen.maxY - 48
        }
    }
}

/// AppKit keeps windows below the menu bar; this one lands on it.
private final class FlightPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}
