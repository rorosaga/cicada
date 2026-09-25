import AppKit
import Foundation

/// What Cicada reads from a browser — the words a row's meta line says (`Copy.browserReads`).
enum BrowserReadable: String, Sendable, CaseIterable {
    case bookmarks, readingList, favorites, recentlySaved, tabGroups
}

/// Round 4 C9 — one browser Cicada knows by bundle id. `supported` means its sync works end to end today
/// (R-SR2); an unsupported browser is named, never offered a switch (decision 2: only connections known to work).
struct BrowserSpec: Equatable, Identifiable, Sendable {
    enum Engine: Sendable { case chromium, safari, other }

    let id: String
    let name: String
    let bundleId: String
    let engine: Engine
    let supported: Bool
    let reads: [BrowserReadable]
    /// The bundled PNG Track L fetched, when there is one; the installed app's icon always wins (R-L1).
    var logo: String? = nil
    var symbol: String = "globe"

    var bookmarksChannel: String? { supported ? "\(id)-bookmarks" : nil }
    var tabGroupsChannel: String? { reads.contains(.tabGroups) ? "\(id)-tab-groups" : nil }
    /// The G9 origin its items carry — an `OriginIconography` key, so `OriginMark` draws its installed icon.
    var origin: String { "\(id)-bookmark" }
}

/// Round 4 C9 — which browsers are on this Mac, detected by bundle id, never by name and never by opening a file
/// (Track I T7: detect, don't ask). Pure over the catalog and an injected probe; `live()` is the one call that asks
/// Launch Services. Phase B's onboarding builds its Browsers category on this.
struct BrowserInventory: Equatable, Sendable {
    let installed: [BrowserSpec]
    var supported: [BrowserSpec] { installed.filter(\.supported) }
    var unsupported: [BrowserSpec] { installed.filter { !$0.supported } }

    static let empty = BrowserInventory(installed: [])

    /// In display order. Bundle ids and default-profile paths verified from public sources (the round-4 sources
    /// plan; no profile read). Arc keeps its own sidebar file and Firefox a SQLite store — each needs its own
    /// parser; Edge and Opera are Chromium but their paths are unverified (G119). A browser whose bundle id is not
    /// verified is not listed at all — never guessed (R-SR2).
    static let catalog: [BrowserSpec] = [
        BrowserSpec(id: "chrome", name: "Chrome", bundleId: "com.google.Chrome", engine: .chromium, supported: true,
                    reads: [.bookmarks, .tabGroups], logo: "chrome"),
        BrowserSpec(id: "safari", name: "Safari", bundleId: "com.apple.Safari", engine: .safari, supported: true,
                    reads: [.bookmarks, .readingList, .favorites, .recentlySaved], symbol: "safari"),
        BrowserSpec(id: "brave", name: "Brave", bundleId: "com.brave.Browser", engine: .chromium, supported: true,
                    reads: [.bookmarks], logo: "brave"),
        BrowserSpec(id: "vivaldi", name: "Vivaldi", bundleId: "com.vivaldi.Vivaldi", engine: .chromium, supported: true,
                    reads: [.bookmarks]),
        BrowserSpec(id: "comet", name: "Comet", bundleId: "ai.perplexity.comet", engine: .chromium, supported: true,
                    reads: [.bookmarks]),
        BrowserSpec(id: "dia", name: "Dia", bundleId: "company.thebrowser.dia", engine: .chromium, supported: true,
                    reads: [.bookmarks]),
        BrowserSpec(id: "arc", name: "Arc", bundleId: "company.thebrowser.Browser", engine: .other, supported: false,
                    reads: []),
        BrowserSpec(id: "firefox", name: "Firefox", bundleId: "org.mozilla.firefox", engine: .other, supported: false,
                    reads: [], logo: "firefox"),
        BrowserSpec(id: "edge", name: "Edge", bundleId: "com.microsoft.edgemac", engine: .chromium, supported: false,
                    reads: []),
        BrowserSpec(id: "opera", name: "Opera", bundleId: "com.operasoftware.Opera", engine: .chromium, supported: false,
                    reads: []),
    ]

    /// Mirrors `bookmark_sync.CHROMIUM_BROWSERS` (the backend's one parser for these files).
    static var chromiumIds: [String] { catalog.filter { $0.engine == .chromium && $0.supported }.map(\.id) }

    static func detect(isInstalled: (String) -> Bool) -> BrowserInventory {
        BrowserInventory(installed: catalog.filter { isInstalled($0.bundleId) })
    }

    /// Off the main actor on purpose (task 3 review, round 1): ten Launch Services lookups each time Integrations
    /// appears. `urlForApplication(withBundleIdentifier:)` is safe from any thread; the caller hops back to assign.
    nonisolated static func live() -> BrowserInventory {
        detect { NSWorkspace.shared.urlForApplication(withBundleIdentifier: $0) != nil }
    }

    static func spec(id: String) -> BrowserSpec? { catalog.first { $0.id == id } }
    static func spec(forBookmarksChannel channel: String) -> BrowserSpec? {
        catalog.first { $0.bookmarksChannel == channel }
    }

    static func readsLine(_ spec: BrowserSpec) -> String { spec.reads.map(Copy.browserReads).joined(separator: " · ") }

    /// "Arc and Firefox aren't supported yet" — one line in the Browsers header, nil when every browser here syncs.
    static func unsupportedLine(_ specs: [BrowserSpec]) -> String? {
        let names = specs.filter { !$0.supported }.map(\.name)
        return names.isEmpty ? nil : Copy.browsersUnsupported(names)
    }
}

/// A browser as a `SourceRow` — pure (R-S19's rule: one projection, many renderings).
enum BrowserRows {
    /// `tryAgain` is the blocked row's one button: the Full Disk Access fix is the hint's own button under the row
    /// (R-D6), so the row offers the retry that hint cannot (task 3 review, round 1 — two buttons that both opened
    /// Settings left no way to re-read after granting access).
    enum Action: Equatable { case turnOn, tryAgain, syncNow, none }

    /// Installed supported browsers in catalog order, plus a supported one that already synced (its history stays
    /// visible after an uninstall). An unsupported browser is never a row.
    static func shown(inventory: BrowserInventory, channels: [SourceChannel]) -> [BrowserSpec] {
        let synced = Set(channels.filter(\.connected).map(\.id))
        return BrowserInventory.catalog.filter { spec in
            guard let channel = spec.bookmarksChannel else { return false }
            return inventory.installed.contains(spec) || synced.contains(channel)
        }
    }

    static func model(_ spec: BrowserSpec, channel: SourceChannel?, watch: BrowserWatchState?,
                      run: SyncActivity.Run?) -> SourceRowModel {
        let line: String?
        switch watch {
        case .absent?: line = spec.engine == .safari ? Copy.safariNothingYet : Copy.browserNothingYet(spec.name)
        case .off?: line = Copy.browserOffLine
        default: line = channel.flatMap { SourceRowText.countLine($0) }
        }
        // Off or absent says nothing on the right: the accessory (Turn on) is what to do, not a status.
        let quiet = (watch == .off || watch == .absent) && run == nil
        return SourceRowModel(id: spec.id, origin: spec.origin, title: spec.name, meta: BrowserInventory.readsLine(spec),
                              line: line,
                              status: quiet ? .idle : SourceRowText.status(channel: channel, watch: watch, run: run))
    }

    /// Safari is on every Mac, so an absent Safari file is far likelier to be one macOS hid than one that is not
    /// there: its absent row still offers Turn on, whose read either finds the file or lands on `.notReadable` and
    /// shows the Full Disk Access fix (task 3 review, round 1 — the row it replaced always had Sync now). The open
    /// probe (`BrowserFileAccess`) usually says blocked first; this is the path when it cannot tell.
    static func action(watch: BrowserWatchState?, engine: BrowserSpec.Engine? = nil) -> Action {
        switch watch {
        case .off?: .turnOn
        case .blocked?: .tryAgain
        case .absent?: engine == .safari ? .turnOn : .none
        case .syncing?: .none
        default: .syncNow
        }
    }
}
