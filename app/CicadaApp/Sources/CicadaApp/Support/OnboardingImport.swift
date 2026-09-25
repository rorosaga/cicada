import Foundation

// Named OnboardingImport.swift, not ImportCatalog.swift: `Views/Capture/Sheets/ImportCatalog.swift` (the `+` sheet's
// tiles, G71 §4.1) already owns that basename, and SwiftPM cannot build two objects of one name in a module.

/// R-OB9 and the owner's decision 2 — F-02's categories, Browsers first, then the rest; *Your chat history* is the
/// drop zone and the provider rows, drawn by the page itself.
enum ImportCategory: Int, CaseIterable, Identifiable {
    case browsers, calendarAndContacts, notesAndFiles, voiceAndMeetings, chatHistory
    var id: Int { rawValue }

    /// A label never promises a row it has not got: "Calendar" unless a Contacts entry is in the table (seam 4 added
    /// it, so the catalog's own table reads "Calendar & contacts").
    func title(entries: [ImportEntry]) -> String {
        switch self {
        case .browsers: Copy.importBrowsers
        case .calendarAndContacts:
            entries.contains { $0.category == self && $0.id != .app(AppSourceDrivers.calendar) }
                ? Copy.importCalendarAndContacts : Copy.importCalendar
        case .notesAndFiles: Copy.importNotesAndFiles
        case .voiceAndMeetings: Copy.importVoice
        case .chatHistory: Copy.gsChatHistory
        }
    }
}

/// One row of F-02. A tick starts `id` through `FoundTurnOn` (the one turn-on); `parent` puts a sub-row under
/// another (Chrome's open tab groups, seam 4) and is never drawn without it; `keepsUp` false means a one-time read with
/// no untick (R-OB8).
struct ImportEntry: Identifiable, Equatable {
    let id: FoundItemID
    let category: ImportCategory
    let title: String
    /// An `OriginIconography` key: the installed app's icon, else the bundled mark (DR-52).
    let origin: String
    var meta: String? = nil
    /// What the row says before anyone ticks it — never a count (R-IB12: nothing is read before the tick).
    var idleLine: String? = nil
    var parent: FoundItemID? = nil
    var keepsUp = true
}

struct ImportContext: Equatable {
    var browsers: BrowserInventory = .empty
    var wisprInstalled = false
    /// The person's own Wispr Flow dictation setting, which the driver keeps as it is — so the row's meta says whether
    /// dictation comes in rather than promising it stays off (seam-4 final review).
    var wisprDictation = false
}

enum ImportCatalog {
    /// Only connections known to work (decision 2): supported, installed browsers, with Chrome's open tab groups as a
    /// sub-row under Chrome; the Mac's Calendar and Contacts; Apple Notes; Wispr Flow once it is on this Mac. No
    /// Obsidian row, no social media (untested). Contacts and the tab groups are one entry each (seam 4), each started
    /// by its own `AppSourceDriver`.
    static func entries(_ context: ImportContext) -> [ImportEntry] {
        var out: [ImportEntry] = []
        for spec in context.browsers.supported {
            guard let channel = spec.bookmarksChannel else { continue }
            out.append(ImportEntry(id: .browser(channel), category: .browsers, title: spec.name, origin: spec.origin,
                                   meta: BrowserInventory.readsLine(spec), idleLine: Copy.importTickToBringIn))
            // G160 — the open tab groups are their own consent (R-SR3), so their own tick, under the browser they come
            // from. Only Chrome's are read today; the sub-row exists only with its parent (never an orphan).
            if spec.tabGroupsChannel == AppSourceDrivers.tabGroups {
                out.append(ImportEntry(id: .app(AppSourceDrivers.tabGroups), category: .browsers,
                                       title: Copy.tabGroupsTitle, origin: "chrome-tab-group",
                                       meta: Copy.importTabGroupsMeta, idleLine: Copy.importTabGroupsIdle,
                                       parent: .browser(channel)))
            }
        }
        out.append(ImportEntry(id: .app(AppSourceDrivers.calendar), category: .calendarAndContacts,
                               title: Copy.importCalendar, origin: "calendar-local", meta: Copy.importCalendarMeta,
                               idleLine: Copy.importCalendarIdle))
        // G154 — one macOS prompt; it only fills in people Cicada already knows and never makes a page (R-SR8).
        out.append(ImportEntry(id: .app(AppSourceDrivers.contacts), category: .calendarAndContacts,
                               title: Copy.contactsTitle, origin: "contacts-local", meta: Copy.importContactsMeta,
                               idleLine: Copy.importContactsIdle))
        out.append(ImportEntry(id: .app(AppSourceDrivers.notes), category: .notesAndFiles, title: Copy.importNotes,
                               origin: "apple-notes", meta: Copy.importNotesMeta, idleLine: Copy.importNotesIdle,
                               keepsUp: false))
        if context.wisprInstalled {
            out.append(ImportEntry(id: .app(AppSourceDrivers.wispr), category: .voiceAndMeetings, title: Copy.importWispr,
                                   origin: "wispr-flow",
                                   meta: context.wisprDictation ? Copy.importWisprMetaDictation : Copy.importWisprMeta,
                                   idleLine: Copy.importTickToBringIn))
        }
        return ordered(out)
    }

    /// Stable, with each child right after its parent; a child whose parent is not in the table is dropped, so a
    /// sub-row is never drawn on its own.
    static func ordered(_ entries: [ImportEntry]) -> [ImportEntry] {
        let children = entries.filter { $0.parent != nil }
        return entries.filter { $0.parent == nil }.flatMap { top in [top] + children.filter { $0.parent == top.id } }
    }

    /// The page's categories in order, each with its rows; a category with no row is not drawn (chat history is the
    /// page's own and always is).
    static func grouped(_ entries: [ImportEntry]) -> [ImportGroup] {
        ImportCategory.allCases.filter { $0 != .chatHistory }.compactMap { category in
            let rows = entries.filter { $0.category == category }
            return rows.isEmpty ? nil : ImportGroup(category: category, entries: rows)
        }
    }
}

struct ImportGroup: Identifiable, Equatable {
    let category: ImportCategory
    let entries: [ImportEntry]
    var id: Int { category.id }
}

/// A row's control: a checkbox that starts (or, for a source that keeps up, stops) it; a one-time read that is
/// running (`locked` — checked, disabled) or done (a ✓).
enum ImportControl: Equatable { case tick(on: Bool), locked, done }

enum ImportRows {
    /// A row nobody started says what a tick does; a started row reads the one projection (R-OB4), with the
    /// entry's own title and what it reads.
    static func model(_ entry: ImportEntry, snapshot: SetupRowSnapshot?) -> SourceRowModel {
        guard let snapshot, snapshot.phase != .off else {
            return SourceRowModel(id: entry.id.key, origin: entry.origin, title: entry.title, meta: entry.meta,
                                  line: entry.idleLine, status: .idle)
        }
        return SourceRowModel(id: entry.id.key, origin: entry.origin, title: entry.title, meta: entry.meta,
                              line: snapshot.model.line, status: snapshot.model.status)
    }

    /// R-OB6 / R-OB8 — never ticked for the person; ticked while it runs or keeps up; a finished one-time read is a ✓.
    /// A row that needs the person (Allow…, a failure) is unticked: its tick is the Allow… or the retry (R-OB7).
    static func control(_ entry: ImportEntry, phase: SetupRowPhase?) -> ImportControl {
        switch phase {
        case nil, .off?, .needsYou?: .tick(on: false)
        case .comingIn?: entry.keepsUp ? .tick(on: true) : .locked
        case .done?: entry.keepsUp ? .tick(on: true) : .done
        }
    }
}

enum ImportTicks {
    /// R-OB7 (W5 kept) — the Allow… click stated the intent: when the grant lands, that row starts, once.
    static func startsAfterGrant(items: [FoundItem], allowRequested: Set<FoundItemID>,
                                 started: Set<FoundItemID>) -> [FoundItemID] {
        items.filter { allowRequested.contains($0.id) && !started.contains($0.id) && $0.readiness == .ready }.map(\.id)
    }
}
