import AppKit
import Foundation

enum FoundTurnOnResult: Equatable {
    /// On; the line is the row's new detail (a sync's own result), or nil for the default.
    case on(String?)
    /// Not run: these are the commands, to inspect (AgentConnectPolicy refused them).
    case refused([String])
    case failed(String)
    /// Full Disk Access opened; the row ticks itself when the grant lands (W5).
    case needsPermission
    /// Cursor asks the person itself; nothing more for Cicada to know.
    case openedApp
    case finishInSettings(SettingsSection)
    /// Re-probed and still not on, with nothing Cicada could run: no verdict of
    /// its own — the host clears its row so the fresh derived readiness shows
    /// (I-b final review, finding 1: a sticky `.failed` here outlived a later
    /// healthy probe for the rest of the session).
    case rechecked
}

/// R-OB9 — a source the APP turns on: Calendar, Apple Notes, Wispr Flow, Contacts and Chrome's open tab groups (seam 4,
/// one registration each). `FoundTurnOn` stays the one turn-on (Track I): it looks the driver up, so a new source is
/// one registration, never a second switch.
struct AppSourceDriver {
    /// Consent and the first read, together; returns the row's new line, or nil for its default.
    var start: @MainActor () async throws -> String?
    /// Untick (R-OB8): stop keeping up; what came in stays.
    var stop: @MainActor () async -> Void
    var isOn: @MainActor () -> Bool
    /// False for a one-time read (Apple Notes): nothing keeps running, so its row never unticks.
    var keepsUp = true
}

enum AppSourceDrivers {
    /// Plain strings, so `ImportCatalog` (nonisolated) can name them; `wispr`, `contacts` and `tabGroups` are
    /// `LocalSourceWatcher.wisprChannel`'s, `ContactsReader.channel`'s and `TabGroupWatcher.channel`'s values, pinned by
    /// `FoundTurnOnTests` — the row's run in `SyncActivity` and its light are keyed by that channel, so a drifted id
    /// would draw a row that never says "Syncing now".
    static let calendar = "calendar-local"
    static let notes = "notes"
    static let wispr = "wispr-flow"
    static let contacts = "contacts-local"
    static let tabGroups = "chrome-tab-groups"

    /// The live registrations. Each reader keeps its own rules (R-FA11's one prompt, the backend's Notes read, Wispr
    /// Flow's column whitelist); a driver only calls them. Missing collaborators register nothing.
    ///
    /// Wispr Flow's speaker names are never guessed here: the driver keeps the person's `ownerSpeakerNames` as they
    /// are (provenance never guesses who spoke; they are set in Settings → Integrations → Wispr Flow).
    ///
    /// Contacts and the tab groups default to nil so a host that has neither (the `+` strip, a test) keeps compiling
    /// and registers nothing for them — their rows then finish in Integrations, as any unregistered source does.
    @MainActor
    static func live(calendar: CalendarReader?, local: LocalSourceWatcher?, store: Store?,
                     contacts: ContactsReader? = nil, tabGroups: TabGroupWatcher? = nil) -> [String: AppSourceDriver] {
        var out: [String: AppSourceDriver] = [:]
        if let calendar {
            out[Self.calendar] = AppSourceDriver(
                start: {
                    await calendar.connect()
                    switch calendar.status {
                    case .synced(_, let events): return Copy.calendarSyncedSummary(events)
                    case .denied: throw BrowserImportActions.ImportActionError.failed(Copy.calendarDenied)
                    case .failed(let why): throw BrowserImportActions.ImportActionError.failed(why)
                    case .off, .syncing: return nil
                    }
                },
                stop: { calendar.disconnect() },
                isOn: { calendar.isEnabled })
        }
        if let local, let store {
            out[Self.notes] = AppSourceDriver(
                start: { try await ChannelActions.sync(Self.notes, store: store, local: local) },
                stop: {},
                isOn: { store.channels.value?.first { $0.id == Self.notes }?.connected == true },
                keepsUp: false)
        }
        if let local {
            out[Self.wispr] = AppSourceDriver(
                start: {
                    var settings = local.wisprSettings
                    settings.enabled = true
                    try await local.setWispr(settings)
                    if let error = local.wisprError { throw error }
                    return nil
                },
                stop: {
                    var settings = local.wisprSettings
                    settings.enabled = false
                    try? await local.setWispr(settings)
                },
                isOn: { local.wisprSettings.enabled })
        }
        if let contacts {
            // G154 — Connect is the one macOS prompt and the first read, together. An empty book is not a failure
            // (nothing to post, R-SR8's never-an-empty-post), so it is the row's line; a refusal is said in the
            // reader's own words, which name where to turn access back on.
            out[Self.contacts] = AppSourceDriver(
                start: {
                    await contacts.connect()
                    switch contacts.status {
                    case .denied: throw BrowserImportActions.ImportActionError.failed(Copy.contactsDenied)
                    case .failed(let why): throw BrowserImportActions.ImportActionError.failed(why)
                    case .empty: return Copy.contactsEmpty
                    // The reader keeps no summary of its last post; the channel's count line fills the row in.
                    case .off, .syncing, .watching: return nil
                    }
                },
                stop: { contacts.disconnect() },
                isOn: { contacts.enabled })
        }
        if let tabGroups {
            // G160 — its own consent (R-SR3), never folded into Chrome's bookmark tick: the sub-row's tick is the
            // switch. No Sessions file yet is not a failure — the switch stays on and the watch catches the first one.
            out[Self.tabGroups] = AppSourceDriver(
                start: {
                    await tabGroups.enable()
                    switch tabGroups.status {
                    case .failed(let why): throw BrowserImportActions.ImportActionError.failed(why)
                    case .missing: return Copy.tabGroupsNoneYet
                    case .off, .syncing, .watching: return TabGroupRows.countLine(tabGroups.groups)
                    }
                },
                stop: { tabGroups.disable() },
                isOn: { tabGroups.enabled })
        }
        return out
    }
}

/// Everything a turn-on touches, injected (FoundTurnOnTests), all main-actor
/// because the live ones read `LocalInventory`, `BrowserWatcher` and the router.
struct FoundTurnOnDeps {
    var wiring: @MainActor () -> AgentWiringResponse?
    var installRoot: URL
    var connect: @MainActor ([AgentWiringStep], URL, Set<String>) async -> AgentConnectOutcome
    var syncBrowser: @MainActor (String) async throws -> String
    var readiness: @MainActor (FoundItemID) -> FoundItem.Readiness?
    var open: @MainActor (URL) -> Void
    var commitDrop: @MainActor (String) async -> IntakeOutcome?
    var refresh: @MainActor () async -> Void
    /// R-OB9 — app-side sources by id; empty in a caller that has none. Stored after `refresh` so every memberwise
    /// call keeps compiling.
    var apps: [String: AppSourceDriver] = [:]
    /// R-OB8 — untick on a browser row.
    var disableBrowser: @MainActor (String) -> Void = { _ in }

    /// The app-side collaborators default to nil, so a host that has none (the `+` strip) registers no app source
    /// and its `.app` rows still finish in Integrations.
    @MainActor
    static func live(inventory: LocalInventory, watcher: BrowserWatcher, intake: IntakeRouter,
                     calendar: CalendarReader? = nil, local: LocalSourceWatcher? = nil,
                     store: Store? = nil, contacts: ContactsReader? = nil,
                     tabGroups: TabGroupWatcher? = nil) -> FoundTurnOnDeps {
        var deps = FoundTurnOnDeps(
            wiring: { inventory.wiring },
            installRoot: BackendProcess.installRoot(),
            connect: { steps, root, binaries in await AgentConnect.run(steps, installRoot: root, binaries: binaries) },
            syncBrowser: { try await watcher.syncNow($0) },
            readiness: { id in inventory.items.first { $0.id == id }?.readiness },
            open: { NSWorkspace.shared.open($0) },
            commitDrop: { await intake.commitWelcomeDrop($0) },
            refresh: { await inventory.refresh() })
        deps.apps = AppSourceDrivers.live(calendar: calendar, local: local, store: store, contacts: contacts,
                                          tabGroups: tabGroups)
        deps.disableBrowser = { watcher.disable($0) }
        return deps
    }
}

/// Track I part b — the ONE turn-on (part a's `OnThisMacStrip.turnOn`, hoisted):
/// the `+` strip, the Welcome's Start and Getting started's Turn on / Retry all
/// run this, so an agent is wired, a browser consented and an export committed
/// the same way from every host (design §3.8: one component, many hosts).
@MainActor
enum FoundTurnOn {
    static func run(_ id: FoundItemID, deps: FoundTurnOnDeps) async -> FoundTurnOnResult {
        switch id {
        case .agent("cursor"):
            // An empty `repo` (a trimmed payload decodes to "") must not build a
            // deep link against "/api/.venv/bin/python" (part a final review).
            let wiring = deps.wiring()
            let repo = wiring.map(\.repo).flatMap { $0.isEmpty ? nil : $0 } ?? deps.installRoot.path
            guard let url = AgentSetupCatalog.all(home: repo, memoryRoot: wiring?.memory)
                .first(where: { $0.id == "cursor" })?.deeplink?.url else { return .failed(Copy.intakeFailed) }
            deps.open(url)
            return .openedApp
        case .agent("claude-desktop"):
            return .finishInSettings(.agents)
        case .agent(let agentId):
            guard let wiring = deps.wiring(), let agent = wiring.agents.first(where: { $0.id == agentId }) else {
                return .failed(Copy.foundBackendDown)
            }
            if agent.connect.isEmpty {
                // No steps: usually a probe that timed out (`unknown`), so the
                // row reads "couldn't check". Its Retry is a re-probe, as part
                // a's strip was (`AgentConnect.run([])` → `.done` → refresh):
                // ask again, and let the fresh answer decide — never a
                // `.failed` that a later healthy probe cannot clear.
                if Self.isOn(agent) { return .on(nil) }
                await deps.refresh()
                let fresh = deps.wiring()?.agents.first { $0.id == agentId }
                return fresh.map(Self.isOn) == true ? .on(nil) : .rechecked
            }
            let outcome = await deps.connect(agent.connect, deps.installRoot, Set(wiring.agents.compactMap(\.binary)))
            await deps.refresh()
            switch outcome {
            case .done: return .on(nil)
            case .refused(let lines): return .refused(lines)
            case .failed(let why): return .failed(why)
            }
        case .browser(let channel):
            if deps.readiness(id) == .needsPermission {
                deps.open(BrowserFileError.fullDiskAccessURL)
                return .needsPermission
            }
            do {
                let line = try await deps.syncBrowser(channel)
                await deps.refresh()
                return .on(line)
            } catch where SyncCancellation.isCancellation(error) {
                // The row's × (final review, finding 1): syncNow already
                // recorded consent, so the browser IS on — the stop is said as
                // a stop (R-SR11), never as "Swift.CancellationError error 1".
                return .on(Copy.syncStopped)
            } catch BrowserImportActions.ImportActionError.busy {
                // An earlier sync of this bank is still saving (a 409, finding 2): consented, not failed.
                return .on(Copy.bookmarkSyncBusy)
            } catch {
                return .failed(AddSourceSheet.friendlyError(error))
            }
        case .dropped(let dropId):
            guard let outcome = await deps.commitDrop(dropId) else { return .failed(Copy.intakeFailed) }
            if outcome.total == 0, let first = outcome.failures.first { return .failed(first) }
            return .on(IntakeSummary.headline(outcome))
        case .app(let appId):
            // R-OB9 — a registered source turns on here; anything else still finishes in Integrations.
            guard let driver = deps.apps[appId] else { return .finishInSettings(.integrations) }
            do {
                let line = try await driver.start()
                await deps.refresh()
                return .on(line)
            } catch where SyncCancellation.isCancellation(error) {
                return .on(Copy.syncStopped)
            } catch {
                return .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }

    /// R-OB8 — untick: stop keeping up, keep what came in. An agent is disconnected in Settings → Agents, and a drop
    /// is never un-imported (`IntakeRouter.cancel`'s rule), so neither stops here.
    static func stop(_ id: FoundItemID, deps: FoundTurnOnDeps) async {
        switch id {
        case .browser(let channel): deps.disableBrowser(channel)
        case .app(let appId): await deps.apps[appId]?.stop()
        case .agent, .dropped: break
        }
    }

    private static func isOn(_ agent: AgentWiring) -> Bool { agent.recall == "on" && agent.autosave == "on" }
}
