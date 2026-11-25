import Foundation

// G245 (plan section 7; owner 2026-11-24: "make sure the notch message appears correctly and works to connect the source
// correctly when I'm inside the app or website") — the notch's Yes goes through the one connect plan, the same
// `SourceConnect.plan` the page's switch and the root card's Connect run. Before this a site's Yes only set a per-Mac
// flag the page never read, and a Mac app's Yes only opened a page; now it does what the page's own Connect does, and the
// panel says only what is true: the write returns before anything is confirmed ("Turned on"), and "will ask why" is said
// only when the site really will (a save control, its noticing on, Accessibility granted).
//
// Pure over injected closures, so every outcome is tested without a window, a reader or the network.

@MainActor
struct NotchConnector {
    /// The catalogue entry a target is (`ConnectSuggestApps.entry`): an app's own id, a site's key.
    var entry: (String) -> SourceCatalogEntry?
    /// This Mac and the memory as the plan reads them, loaded fresh (the acknowledgement is the backend's now).
    var state: (SourceCatalogEntry) async -> SourceConnect.State
    var deps: SourceConnect.Deps
    /// Whether the Accessibility grant is given (a preflight, never a prompt).
    var accessibilityGranted: () -> Bool
    /// Whether this Mac now notices saves on the site (`SiteSavePrefs`).
    var noticing: (String) -> Bool
    /// A permission macOS gives only in Settings (Full Disk Access for Safari, Messages, WhatsApp): its row, with the drag
    /// helper, is where the Yes lands.
    var openPermission: (MacPermission) -> Void

    /// `target` is `ConnectSuggestApps.Target.entryId`: an app's catalogue id, or `site-save:<key>`.
    func connect(_ target: String) async -> ConnectSuggestResult {
        let id = ConnectSuggestApps.siteKey(entryId: target) ?? target
        guard let entry = entry(id) else {
            // A site the catalogue does not list: noticing its saves is still the whole of what the Yes can do.
            guard SiteSaveSite.named(id) != nil else { return .failed(nil) }
            deps.noticeSaves(id)
            return turnedOn(id)
        }
        let plan = SourceConnect.plan(entry, await state(entry))
        if case .needsChoice(.permission(let permission)) = plan {
            openPermission(permission)
            return .openedPage
        }
        // The offer said what will be read and the person pressed Yes: that is the acknowledgement, so no page opens
        // for it (owner 2026-11-25) and the panel goes on to its ring and check.
        switch await SourceConnect.run(plan, entry: id, deps: deps, yesIsConsent: true) {
        case .turnedOn: return turnedOn(id)
        case .openedPage: return .openedPage
        case .failed(let note): return .failed(note)
        }
    }

    /// What a turned-on source can honestly promise. A site with a save control asks why on a save only while this Mac
    /// notices its saves and Accessibility lets it see them; without the grant the words say so (and offer the setting).
    private func turnedOn(_ id: String) -> ConnectSuggestResult {
        guard SiteSaveSite.named(id) != nil, noticing(id) else {
            return .turnedOn(asksWhy: false, needsAccessibility: false)
        }
        let granted = accessibilityGranted()
        return .turnedOn(asksWhy: granted, needsAccessibility: !granted)
    }
}
