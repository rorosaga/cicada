import Foundation

/// What an opened Past sleeps card draws, pure so `RunItemsModelTests` holds every rule without a view (owner
/// 2026-11-24: "make it easy to see what was consolidated, an easy view to see the pages affected per source, if it was
/// an update, creation or deletion of entity pages").
///
/// The card nests like the Queue: the run holds one card per source, a source holds the conversations it fed, a
/// conversation holds the pages it fed. A page shows under every conversation that fed it. A page no conversation of the
/// run stands behind sits under the step that changed it (owner 2026-11-24: "what influenced this change?"), in a card
/// of its own per step, in plain words. A page whose facts only lost confidence to silence is `faded`: its own quiet
/// tab, never in All. An older backend sends no attribution (`device`, `pages`, `episodes`, `steps`): the conversations
/// then group by origin with no pages under them, and the pages sit in one group.
enum RunItemsModel {
    typealias Change = SleepConsolidated.Change

    // MARK: The machine filter

    /// Whether a conversation posted by `device` belongs to the machine the page is narrowed to: `nil` is every machine,
    /// `"server"` (`MachineStatus.id`) is this server's own conversations (they carry no device), anything else is a
    /// device id.
    static func matches(device: String?, machineId: String?) -> Bool {
        guard let machineId else { return true }
        return machineId == "server" ? device == nil : device == machineId
    }

    // MARK: What it fed

    /// Whether a conversation fed a page: the conversation names the page, or the page names the conversation.
    static func feeds(_ conversation: SleepConsolidated.Conversation, _ page: SleepConsolidated.Page) -> Bool {
        conversation.pages.contains(page.id) || page.episodes.contains(conversation.id)
    }

    /// Whether the wire says which conversation fed which page; an older backend's does not.
    static func isAttributed(_ items: SleepConsolidated) -> Bool {
        items.conversations.contains { !$0.pages.isEmpty } || items.pages.contains { !$0.episodes.isEmpty }
    }

    /// The conversations the page is narrowed to.
    static func conversations(_ items: SleepConsolidated, machineId: String?) -> [SleepConsolidated.Conversation] {
        machineId == nil ? items.conversations : items.conversations.filter { matches(device: $0.device, machineId: machineId) }
    }

    /// The pages that really changed, narrowed to the machine: with a machine selected, only the pages its
    /// conversations fed. Faded pages are not here (`allPages`): fading is not a change.
    static func pages(_ items: SleepConsolidated, machineId: String?) -> [SleepConsolidated.Page] {
        narrowed(items.pages, items, machineId: machineId)
    }

    /// Every listed page, faded ones last: what the Faded tab and the counts read.
    static func allPages(_ items: SleepConsolidated, machineId: String?) -> [SleepConsolidated.Page] {
        narrowed(items.pages + items.fadedPages, items, machineId: machineId)
    }

    private static func narrowed(_ pages: [SleepConsolidated.Page], _ items: SleepConsolidated, machineId: String?)
        -> [SleepConsolidated.Page] {
        guard machineId != nil else { return pages }
        let mine = conversations(items, machineId: machineId)
        return pages.filter { page in mine.contains { feeds($0, page) } }
    }

    /// Whether a run read anything from the selected machine (a run with none is not listed while the filter is on).
    static func hasConversations(_ items: SleepConsolidated, machineId: String?) -> Bool {
        !conversations(items, machineId: machineId).isEmpty
    }

    /// The filter the card draws by: the one picked while its kind is still among the tabs, else All. A machine change
    /// can leave the picked kind with no page (or hide the tabs altogether), and a filter nobody can see must not hold
    /// the card empty.
    static func effectiveFilter(_ filter: Change?, kinds: [Change], counts: [Change: Int] = [:]) -> Change? {
        if let filter, kinds.contains(filter) { return filter }
        // A run that changed nothing and only faded pages has no tab to choose: it draws its faded pages.
        return onlyFaded(counts) ? .faded : nil
    }

    /// Nothing really changed, and some pages faded: the card has only the quiet list.
    static func onlyFaded(_ counts: [Change: Int]) -> Bool {
        (counts[.faded] ?? 0) > 0 && changeKinds(counts).isEmpty
    }

    private static func changeKinds(_ counts: [Change: Int]) -> [Change] {
        Change.allCases.filter { $0 != .faded && (counts[$0] ?? 0) > 0 }
    }

    /// Whether a narrowed card's numbers are partial: the server caps each list, so with a machine selected the counts
    /// are tallied from what is listed, not from the run's whole counts.
    static func countsArePartial(_ items: SleepConsolidated, machineId: String?) -> Bool {
        machineId != nil && items.truncated
    }

    // MARK: The numbers

    /// How many pages of each kind: the server's whole counts for every machine, else what the narrowed lists hold.
    static func counts(_ items: SleepConsolidated, machineId: String?) -> [Change: Int] {
        var out: [Change: Int] = [:]
        if machineId == nil {
            out[.created] = items.count("created", items.created.count)
            out[.updated] = items.count("updated", items.updated.count)
            out[.archived] = items.count("archived", items.archived.count)
            out[.removed] = items.count("removed", items.removed.count)
            out[.faded] = items.count("faded", items.faded.count)
        } else {
            for page in allPages(items, machineId: machineId) { out[page.change ?? .updated, default: 0] += 1 }
        }
        return out
    }

    /// The pages that really changed — what "All" counts. Fading is its own count (`counts[.faded]`).
    static func changed(_ counts: [Change: Int]) -> Int { changeKinds(counts).map { counts[$0] ?? 0 }.reduce(0, +) }

    /// Conversations read: the whole count for every machine, else the narrowed list's.
    static func conversationCount(_ items: SleepConsolidated, machineId: String?) -> Int {
        machineId == nil ? items.count("conversations", items.conversations.count)
                         : conversations(items, machineId: machineId).count
    }

    /// The card's one summary line, from what the items say.
    static func summary(_ items: SleepConsolidated, machineId: String?, locale: Locale = .autoupdatingCurrent) -> String {
        let counts = counts(items, machineId: machineId)
        return Copy.RunCard.summary(conversations: conversationCount(items, machineId: machineId),
                                    created: counts[.created] ?? 0, updated: counts[.updated] ?? 0,
                                    archived: counts[.archived] ?? 0, removed: counts[.removed] ?? 0,
                                    faded: counts[.faded] ?? 0, locale: locale)
    }

    /// The filter's tabs: only the kinds that happened, and none at all when there is just one kind (nothing to
    /// choose). Faded is the trailing tab (owner 2026-11-24), shown beside a change kind and never alone.
    static func filterKinds(_ counts: [Change: Int]) -> [Change] {
        let real = changeKinds(counts)
        let faded = (counts[.faded] ?? 0) > 0
        if real.isEmpty { return [] }
        if real.count == 1 && !faded { return [] }
        return real + (faded ? [.faded] : [])
    }

    // MARK: The sources a card marks

    /// The origins a card's marks show: each origin the narrowed conversations came from once, the one it read most
    /// first (ties keep the conversations' order).
    static func origins(_ items: SleepConsolidated?, machineId: String? = nil) -> [String] {
        guard let items else { return [] }
        var counts: [String: Int] = [:]
        var order: [String] = []
        for c in conversations(items, machineId: machineId) {
            if counts[c.origin] == nil { order.append(c.origin) }
            counts[c.origin, default: 0] += 1
        }
        return order.enumerated()
            .sorted { (counts[$0.element] ?? 0, -$0.offset) > (counts[$1.element] ?? 0, -$1.offset) }
            .map(\.element)
    }

    /// The pages a closed card names, in reading order (new, updated, archived, removed), and how many in all.
    static func preview(_ items: SleepConsolidated?, machineId: String? = nil)
        -> (pages: [SleepConsolidated.Page], total: Int) {
        guard let items else { return ([], 0) }
        let pages = pages(items, machineId: machineId)
        let total = changed(counts(items, machineId: machineId))
        return (pages, max(total, pages.count))
    }

    // MARK: The body

    struct Row: Equatable, Identifiable {
        let conversation: SleepConsolidated.Conversation
        let pages: [SleepConsolidated.Page]
        var id: String { conversation.id }
    }

    struct Source: Equatable, Identifiable {
        let origin: String
        let rows: [Row]
        var id: String { origin }
    }

    /// The pages a step changed with no conversation of the run behind them (owner 2026-11-24).
    struct StepGroup: Equatable, Identifiable {
        let step: SleepConsolidated.Step
        let pages: [SleepConsolidated.Page]
        var id: String { "step.\(step.rawValue)" }
    }

    struct Body: Equatable {
        var sources: [Source]
        /// The pages no conversation of the run stands behind, under the step that changed each: the biggest first.
        var steps: [StepGroup] = []
        /// Pages nobody and no step stands behind — an older backend's, which cannot say; a group of its own.
        var leftover: [SleepConsolidated.Page]
        /// Pages a conversation of the run fed that the server did not list (it caps each list): not upkeep, so never in
        /// `leftover`, and with no conversation row to sit under, a group of their own.
        var unlisted: [SleepConsolidated.Page] = []
        /// False for an older backend: the leftover is then every page, and says so in its name.
        var attributed: Bool
        var isEmpty: Bool { sources.isEmpty && steps.isEmpty && leftover.isEmpty && unlisted.isEmpty }
    }

    /// The step a page sits under: the first the backend names that is not the bare reading (a page restored by a
    /// later batch carries decay, then reading — decay is what changed it), else the first, else `other`.
    static func primaryStep(_ page: SleepConsolidated.Page) -> SleepConsolidated.Step {
        page.steps.first { $0 != .reading && $0 != .other } ?? page.steps.first ?? .other
    }

    /// The steps of `page` that are not the `parent` group's own: what a page's panel adds ("also changed by").
    static func otherSteps(_ page: SleepConsolidated.Page, parent: SleepConsolidated.Step?) -> [SleepConsolidated.Step] {
        var seen = Set<SleepConsolidated.Step>()
        return page.steps.filter { $0 != parent && seen.insert($0).inserted }
    }

    /// Groups pages by their primary step: the biggest group first, ties in the step's own order.
    static func stepGroups(_ pages: [SleepConsolidated.Page]) -> [StepGroup] {
        var by: [SleepConsolidated.Step: [SleepConsolidated.Page]] = [:]
        for page in pages { by[primaryStep(page), default: []].append(page) }
        let order = SleepConsolidated.Step.allCases
        return by.keys
            .sorted { (by[$0]?.count ?? 0, -(order.firstIndex(of: $0) ?? 0)) > (by[$1]?.count ?? 0, -(order.firstIndex(of: $1) ?? 0)) }
            .map { StepGroup(step: $0, pages: by[$0] ?? []) }
    }

    /// The sources, largest first (ties keep the conversations' order), each with its conversations and their pages.
    /// `filter` keeps only the pages of one kind, and then only the conversations that fed one.
    static func body(_ items: SleepConsolidated, filter: Change?, machineId: String?) -> Body {
        let attributed = isAttributed(items)
        let kept = allPages(items, machineId: machineId).filter { filter == nil ? $0.change != .faded : $0.change == filter }
        let mine = conversations(items, machineId: machineId)
        var rows: [Row] = []
        for c in mine {
            let fed = attributed ? kept.filter { feeds(c, $0) } : []
            if filter != nil && fed.isEmpty { continue }
            rows.append(Row(conversation: c, pages: fed))
        }
        var order: [String] = []
        var byOrigin: [String: [Row]] = [:]
        for row in rows {
            if byOrigin[row.conversation.origin] == nil { order.append(row.conversation.origin) }
            byOrigin[row.conversation.origin, default: []].append(row)
        }
        let sources = order.enumerated()
            .sorted { (byOrigin[$0.element]?.count ?? 0, -$0.offset) > (byOrigin[$1.element]?.count ?? 0, -$1.offset) }
            .map { Source(origin: $0.element, rows: byOrigin[$0.element] ?? []) }
        // A page with nobody behind it: with every machine shown, those no listed conversation fed (or all of them from
        // an older backend); with one machine selected there is no such group — its conversations' pages only.
        // A run past the server's cap lists some of its conversations only: a page that names a conversation the list
        // lacks was fed by someone, so it is no upkeep (`unlisted`).
        var leftover: [SleepConsolidated.Page]
        var unlisted: [SleepConsolidated.Page] = []
        if machineId != nil {
            leftover = []
        } else if attributed {
            leftover = kept.filter { page in !items.conversations.contains { feeds($0, page) } }
            if items.truncated {
                unlisted = leftover.filter { !$0.episodes.isEmpty }
                leftover = leftover.filter { $0.episodes.isEmpty }
            }
        } else {
            leftover = kept
        }
        // The backend says which step changed a page (items-6): a page nobody of the run fed sits under that step. A page
        // with no step is only an older backend's — unless the backend names steps on its other pages, where the
        // step it could not name is `other`.
        let namesSteps = items.pages.contains { !$0.steps.isEmpty } || items.fadedPages.contains { !$0.steps.isEmpty }
        var stepped: [StepGroup] = []
        if namesSteps {
            stepped = stepGroups(leftover)
            leftover = []
        }
        return Body(sources: sources, steps: stepped, leftover: leftover, unlisted: unlisted, attributed: attributed)
    }

    // MARK: A conversation row

    /// The mark a conversation row wears when it is not the source's own (owner 2026-11-24: the Queue's priority — a
    /// saved link's site, then the meeting's call app, then the origin; the origin already heads the source's card, so a
    /// row draws it no more, DR-38).
    enum RowMark: Equatable {
        case site(String)
        case callApp(String)
    }

    static func rowMark(_ c: SleepConsolidated.Conversation) -> RowMark? {
        if SavedLinkMarkModel.applies(site: c.site), let site = c.site { return .site(site) }
        if let app = MeetingApp.origin(for: c.meeting?.app) { return .callApp(app) }
        return nil
    }

    /// Whether a saved link's site mark has anything to draw in a run's row: its fetched icon or a family's bundled
    /// mark — never `SiteIcon`'s monogram rung (owner: no letter or glyph stands in for a picture). A row with none
    /// draws no slot at all.
    static func siteMarkDraws(site: String, favicon: Bool,
                              markExists: (String) -> Bool = LogoImage.exists(name:)) -> Bool {
        SiteIconLayout.rung(favicon: favicon, site: site, markExists: markExists) != .monogram
    }

    /// The row's quiet meta: the machine's name when it is not this one, and the day when it is not the run's own.
    static func rowMeta(machineName: String?, day: String?) -> String? {
        let parts = [machineName, day].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    // MARK: The questions line

    /// The raised and settled questions, raised first, each marked.
    static func questions(_ items: SleepConsolidated) -> [(question: SleepConsolidated.Question, settled: Bool)] {
        items.questionsRaised.map { ($0, false) } + items.questionsSettled.map { ($0, true) }
    }

    static func questionCounts(_ items: SleepConsolidated) -> (raised: Int, settled: Int) {
        (items.count("questions_raised", items.questionsRaised.count),
         items.count("questions_settled", items.questionsSettled.count))
    }
}
