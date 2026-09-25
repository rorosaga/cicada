import AppKit
import Foundation

/// The quiet login start (round-4 phase B addendum; answers G143's open question; R-OB18) — how this launch began.
/// macOS marks a login-item launch on the 'oapp' Apple event itself: `keyAEPropData` carries
/// `keyAELaunchedAsLogInItem`. That event is current only while `applicationDidFinishLaunching` runs, so
/// `CicadaAppDelegate` asks there and nowhere else.
enum LaunchKind: Equatable, Sendable {
    case interactive, loginItem

    /// For the orchestrator's live check (`open -a Cicada --args -CicadaLaunchKind loginItem`). Read from this
    /// process's arguments, never from defaults — a stray `defaults write` would silence every launch — and it can
    /// only make a launch quieter.
    static let argument = "-CicadaLaunchKind"

    static func from(event: NSAppleEventDescriptor?) -> LaunchKind {
        guard let event,
              event.eventClass == AEEventClass(kCoreEventClass),
              event.eventID == AEEventID(kAEOpenApplication),
              event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue
                == OSType(keyAELaunchedAsLogInItem)
        else { return .interactive }
        return .loginItem
    }

    static func resolve(event: NSAppleEventDescriptor?, arguments: [String]) -> LaunchKind {
        if let i = arguments.firstIndex(of: argument), arguments.indices.contains(i + 1),
           arguments[i + 1] == "loginItem" {
            return .loginItem
        }
        return from(event: event)
    }
}

/// What the first window of this launch does (R-OB18). Unknown is never quiet: a window is closed only for a launch
/// macOS marked as a login item, and never once the person asked for it.
enum QuietLaunch {
    enum WindowAction: Equatable { case show, close }

    static func firstWindow(kind: LaunchKind?, userAsked: Bool) -> WindowAction {
        kind == .loginItem && !userAsked ? .close : .show
    }
}

/// The launch's one record. SwiftUI builds the window and the delegate hears the launch event in an order SwiftUI
/// owns, so both halves meet here: the window asks once (`firstWindowAction`), and a login record that arrives after
/// the window showed closes it (`record`). Closing the first window leaves the app exactly where closing its last
/// window does — the menu bar, the watchers, the sync engine and the Dock icon all stay (`.regular`, `CicadaApp.init`).
@MainActor
final class LaunchState {
    static let shared = LaunchState()

    private(set) var kind: LaunchKind?
    private(set) var userAsked = false
    private var firstWindowSeen = false
    private let activate: @MainActor () -> Void
    private let closeMainWindows: @MainActor () -> Void

    init(activate: @escaping @MainActor () -> Void = { NSApp?.activate(ignoringOtherApps: true) },
         closeMainWindows: @escaping @MainActor () -> Void = { MainWindow.closeVisible() }) {
        self.activate = activate
        self.closeMainWindows = closeMainWindows
    }

    /// `applicationDidFinishLaunching` — heard once. An interactive launch takes focus (the job `init()` used to do
    /// for every launch); a login launch takes none.
    func record(_ kind: LaunchKind) {
        guard self.kind == nil else { return }
        self.kind = kind
        switch kind {
        case .interactive: activate()
        case .loginItem: if firstWindowSeen && !userAsked { closeMainWindows() }
        }
    }

    /// The window's `.onAppear` asks once; every later window (a Dock click, Open Cicada) shows.
    func firstWindowAction() -> QuietLaunch.WindowAction {
        defer { firstWindowSeen = true }
        guard !firstWindowSeen else { return .show }
        return QuietLaunch.firstWindow(kind: kind, userAsked: userAsked)
    }

    func userAskedForWindow() { userAsked = true }
}

/// The main window, found by `AppRouter.isMainWindow`'s rule (never a panel, never a Settings window).
@MainActor
enum MainWindow {
    static func all() -> [NSWindow] {
        (NSApp?.windows ?? []).filter {
            AppRouter.isMainWindow(identifier: $0.identifier?.rawValue, title: $0.title,
                                   canBecomeKey: $0.canBecomeKey, isPanel: $0 is NSPanel)
        }
    }

    static func closeVisible() {
        for window in all() where window.isVisible { window.close() }
    }
}
