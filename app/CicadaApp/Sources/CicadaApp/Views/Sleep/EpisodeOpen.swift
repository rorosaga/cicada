import AppKit
import SwiftUI

/// Owner 2026-11-23 — "when I right click on a specific episode, I'd like the option for it to take me to that
/// app/website/claude code session": where a queued episode's original opens, decided with no view in it
/// (`EpisodeOpenTests`). The backend names the place (`openKind` / `openValue`); a stored value is data, whoever sent
/// it, so every one is checked again here before anything opens (`ItemPlaceOpen`'s rules for a link and a note).
///
/// Nothing runs until the person picks the menu item: a link opens in the browser it was saved from when that browser
/// is installed (else the default one), a note through Notes' own `show`, a Claude Code session through the resume
/// route and the terminal (the Automation prompt is that click's), a file is revealed in Finder. A chat has no address
/// in the bank — only a hash — so it opens its app, and the menu says so ("Open Messages", never "Open in").
enum EpisodeOpen {
    enum Target: Equatable {
        /// A link, and the bundle id of the browser it was saved from when the source is one.
        case web(URL, browser: String?)
        case session(String)
        case note(String)
        case file(URL)
        /// Nothing names the original: the source's own app.
        case app(bundleId: String)
    }

    static func target(_ item: EpisodeQueueItem) -> Target? {
        let value = item.openValue ?? ""
        switch item.openKind {
        case "web":
            guard let url = ItemPlaceOpen.webURL(value) else { return nil }
            return .web(url, browser: browser(for: item.origin))
        case "session":
            return UUID(uuidString: value) != nil ? .session(value) : nil
        case "note":
            return ItemPlaceOpen.noteID(value).map(Target.note)
        case "file":
            guard value.hasPrefix("/"), !value.unicodeScalars.contains(where: { $0.value < 32 }) else { return nil }
            return .file(URL(fileURLWithPath: value))
        default:
            return OriginIconography.appBundleId(for: item.origin).map { Target.app(bundleId: $0) }
        }
    }

    /// A link opens in the browser it was saved from: only a source that is a browser names one.
    static func browser(for origin: String) -> String? {
        guard origin.hasSuffix("-bookmark") || origin.hasSuffix("-tab-group") || origin.hasSuffix("-tab") else { return nil }
        return OriginIconography.appBundleId(for: origin)
    }

    /// The menu item's words. `appName` answers an installed app's own name for a bundle id, nil when it is not here.
    static func label(_ target: Target, appName: (String) -> String?) -> String? {
        switch target {
        case .web(_, let browser):
            browser.flatMap(appName).map(Copy.EpisodeOpen.openIn) ?? Copy.Place.inBrowser
        case .session: Copy.EpisodeOpen.openIn(Copy.EpisodeOpen.claudeCode)
        case .note: Copy.Place.inNotes
        case .file: Copy.EpisodeOpen.showInFinder
        case .app(let bundleId): appName(bundleId).map(Copy.EpisodeOpen.openApp)
        }
    }

    /// An installed app's own name ("Google Chrome"), nil when no app has that bundle id on this Mac.
    @MainActor
    static func installedAppName(_ bundleId: String) -> String? {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) else { return nil }
        return FileManager.default.displayName(atPath: url.path).replacingOccurrences(of: ".app", with: "")
    }

    /// Opens it. Runs only on the person's click; returns the words to show (a problem, or what happened for a
    /// session), nil when it simply opened.
    @MainActor
    static func open(_ target: Target) async -> String? {
        switch target {
        case .web(let url, let browser):
            if let browser, let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: browser) {
                _ = try? await NSWorkspace.shared.open([url], withApplicationAt: app, configuration: .init())
            } else {
                NSWorkspace.shared.open(url)
            }
            return nil
        case .session(let id):
            return await ConversationsViewModel().resume(id).toast
        case .note(let id):
            return AppleNotesReader.showProblem(await AppleNotesReader.runShow(id, AppleNotesReader.showTimeout))
        case .file(let url):
            guard FileManager.default.fileExists(atPath: url.path) else { return Copy.EpisodeOpen.fileGone }
            NSWorkspace.shared.activateFileViewerSelecting([url])
            return nil
        case .app(let bundleId):
            guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) else {
                return Copy.Place.notFound
            }
            _ = try? await NSWorkspace.shared.openApplication(at: app, configuration: .init())
            return nil
        }
    }
}
