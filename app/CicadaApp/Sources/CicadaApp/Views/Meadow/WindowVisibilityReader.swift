import AppKit
import SwiftUI

/// C10 (R-HO7) — whether a living painting's window can be seen at all: occluded by another window, minimised, on
/// another Space or the app hidden all clear `.visible` (`NSWindow.occlusionState`). A scene nobody can see spends no
/// frames — the brief's performance requirement, and rationale-F's "paused when the window is occluded".
struct WindowVisibilityReader: NSViewRepresentable {
    let onChange: (Bool) -> Void

    func makeNSView(context: Context) -> ProbeView { ProbeView(onChange: onChange) }
    func updateNSView(_ view: ProbeView, context: Context) { view.onChange = onChange }

    final class ProbeView: NSView {
        var onChange: (Bool) -> Void
        private var token: NSObjectProtocol?

        init(onChange: @escaping (Bool) -> Void) {
            self.onChange = onChange
            super.init(frame: .zero)
        }

        required init?(coder: NSCoder) { return nil }

        override func hitTest(_ point: NSPoint) -> NSView? { nil }

        override func viewWillMove(toWindow newWindow: NSWindow?) {
            super.viewWillMove(toWindow: newWindow)
            if let token { NotificationCenter.default.removeObserver(token) }
            token = nil
        }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard let window else { return }
            report(window)
            token = NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification,
                                                           object: window, queue: .main) { [weak self, weak window] _ in
                MainActor.assumeIsolated { if let window { self?.report(window) } }
            }
        }

        /// Deferred a turn, so SwiftUI state is never written during a view update.
        private func report(_ window: NSWindow) {
            let visible = window.occlusionState.contains(.visible)
            DispatchQueue.main.async { [onChange] in onChange(visible) }
        }
    }
}
