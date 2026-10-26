import SwiftUI

// G61 (owner 2026-10-26) — the "Reading in your browser" area's quick add and its list. The owner: "the ones that are
// reading in my browser — I should be able to quickly add more, like manually add a link. An agent can also do this
// ('add this source'); I told the agent and they added it here, and we can check there. This has a lot to do with
// sources of update for entity pages."
//
// One field: paste a link, optionally pick the page it is where to check (search by name, never creating one), Add. With
// a page, it is that page's source, the person's own (`POST /entities/{id}/sources`, trusted by the person); with no
// page, it is saved as a link (`POST /sources/save`) for Sleep to read — the existing writers, one per store. Below,
// every page's sources the person and their agents added (`GET /sources/where-to-check`), who and when, each removable
// as the person (`POST /entities/{id}/sources/change`, action remove — remembered, so no writer puts it back).
//
// Not a Store domain: the list is on demand, kept here in memory with its ETag (a 304 keeps it), and read again after
// every write — no `VersionVector` mapping (CLAUDE.md, Sync).
//
// DR-40 (one neutral Add; removal an icon button with its help), DR-46 (the page search is a field inside this form,
// not a third search), DR-50 (the empty list said in words), DR-53 (icon buttons carry help), DR-76 (the app's field).

/// One row of `GET /sources/where-to-check`.
struct AddedSourceRow: Codable, Equatable, Identifiable, Sendable {
    var entityId: String
    var entityName: String
    var entityType: String = ""
    /// `you` | `agent`
    var who: String
    /// The agent's name, for `who == "agent"`.
    var agent: String?
    var addedBy: String
    var ref: String
    var kind: String
    var predicate: String?
    var addedAt: String = ""
    var proposed: Bool = false

    var id: String { "\(entityId)\u{1}\(ref)\u{1}\(predicate ?? "")" }
    var isYours: Bool { who == "you" }

    /// The entry as the page's change route names it (its key is `(ref, predicate)`).
    var source: EntitySource {
        EntitySource(ref: ref, kind: kind, predicate: predicate, addedBy: addedBy, addedAt: addedAt)
    }
}

struct AddedSourcesResponse: Codable, Equatable, Sendable {
    var items: [AddedSourceRow]
    var total: Int
}

/// The pure decisions: what the field accepts, which pages a name finds, and the line under each row.
enum AddedSourcesLogic {
    /// A pasted link as the source keeps it: `http(s)` only, a bare `example.com/page` read as https. nil for anything
    /// that is not a web link (a path, words) — those are a page's own source, added on the page.
    static func link(_ text: String) -> String? {
        var raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty, !raw.contains(" ") else { return nil }
        if !raw.lowercased().hasPrefix("http://"), !raw.lowercased().hasPrefix("https://") {
            guard !raw.contains("://") else { return nil }
            raw = "https://" + raw
        }
        guard let url = URL(string: raw), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = url.host, host.contains(".") else { return nil }
        return raw
    }

    /// Live pages whose name holds the words, those starting with them first, then by name; at most `limit`. Never a
    /// facet or a hub: a source belongs to a page. Empty words find nothing — the field never guesses a page.
    static func pages(matching words: String, in nodes: [GraphNode], limit: Int = 6) -> [GraphNode] {
        let query = words.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !query.isEmpty else { return [] }
        let found = nodes.filter { node in
            !node.isFacet && !node.isHub && node.status != .archived && node.status != .dropped
                && node.name.lowercased().contains(query)
        }
        return Array(found.sorted { a, b in
            let pa = a.name.lowercased().hasPrefix(query), pb = b.name.lowercased().hasPrefix(query)
            if pa != pb { return pa }
            return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
        }.prefix(limit))
    }

    /// "You · Oct 20" or "Claude Code · Oct 24", with the fact it is for when it names one.
    static func credit(_ row: AddedSourceRow, today: ISODay) -> String {
        let who = row.isYours ? Copy.QuickSources.you : (row.agent ?? Copy.QuickSources.anAgent)
        let when = ISODay(row.addedAt).map { RelativeDay.phrase($0, today: today) } ?? ""
        let fact = row.predicate.map { $0.replacingOccurrences(of: "-", with: " ") } ?? ""
        return Eyebrow.text(who, when, fact, row.proposed ? Copy.QuickSources.waiting : "")
    }

    /// The link without its scheme, for the row's title.
    static func shown(_ ref: String) -> String {
        var text = ref
        for prefix in ["https://", "http://"] where text.lowercased().hasPrefix(prefix) {
            text = String(text.dropFirst(prefix.count))
        }
        if text.hasPrefix("www.") { text = String(text.dropFirst(4)) }
        return text.hasSuffix("/") ? String(text.dropLast()) : text
    }
}

/// The area's state with no view in it. Every call goes through `Deps`, so tests run with no network.
@MainActor
@Observable
final class AddedSourcesModel {
    struct Deps {
        var fetch: @MainActor (String?) async throws -> Conditional<AddedSourcesResponse>
        var addSource: @MainActor (String, String) async throws -> Void
        var saveLink: @MainActor (String) async throws -> Void
        var remove: @MainActor (AddedSourceRow) async throws -> Void

        @MainActor static var live: Deps {
            Deps(fetch: { try await APIClient.shared.fetchWhereToCheck(etag: $0) },
                 addSource: { entity, ref in _ = try await APIClient.shared.addEntitySource(entityId: entity, ref: ref) },
                 saveLink: { _ = try await APIClient.shared.saveURL($0) },
                 remove: { row in
                     _ = try await APIClient.shared.changeEntitySource(entityId: row.entityId, source: row.source,
                                                                       change: .remove)
                 })
        }
    }

    private(set) var rows: [AddedSourceRow] = []
    private(set) var total = 0
    private(set) var loaded = false
    private(set) var busy = false
    /// The last write's sentence, or why a read failed (the list keeps what it had).
    private(set) var note: String?
    @ObservationIgnored private var etag: String?
    @ObservationIgnored private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    func load() async {
        do {
            let answer = try await deps.fetch(etag)
            if let value = answer.value {
                rows = value.items
                total = value.total
            }
            etag = answer.etag ?? etag
            loaded = true
        } catch {
            note = Copy.QuickSources.couldNotRead
        }
    }

    /// The person's Add. Returns whether it landed (the field clears then).
    @discardableResult
    func add(_ text: String, page: GraphNode?) async -> Bool {
        guard let link = AddedSourcesLogic.link(text) else { note = Copy.QuickSources.notALink; return false }
        busy = true
        defer { busy = false }
        do {
            if let page {
                try await deps.addSource(page.id, link)
                note = Copy.QuickSources.added(page.name)
            } else {
                try await deps.saveLink(link)
                note = Copy.QuickSources.savedAsLink
            }
        } catch {
            note = Self.describe(error)
            return false
        }
        await load()
        return true
    }

    func remove(_ row: AddedSourceRow) async {
        busy = true
        defer { busy = false }
        let before = rows
        rows.removeAll { $0.id == row.id }   // optimistic; rolled back on failure (CLAUDE.md, Sync)
        do {
            try await deps.remove(row)
            note = Copy.QuickSources.removed
        } catch {
            rows = before
            note = Self.describe(error)
            return
        }
        await load()
    }

    static func describe(_ error: Error) -> String {
        if case APIError.httpError(_, let body) = error, let detail = ServerDetail.sentence(body) { return detail }
        return Copy.QuickSources.failed
    }
}

/// The server's `detail` sentence from an error body, when it sent one.
enum ServerDetail {
    static func sentence(_ body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] as? String, !detail.isEmpty else { return nil }
        return detail
    }
}

struct AddedSourcesSection: View {
    /// The list's own scroll height: the switches below it stay in reach.
    var listHeight: CGFloat = 168
    @Environment(Store.self) private var store
    @State private var model = AddedSourcesModel()
    @State private var linkText = ""
    @State private var pageText = ""
    @State private var page: GraphNode?
    @FocusState private var focus: Field?

    private enum Field: Hashable { case link, page }

    private var today: ISODay { ISODay.today(now: .now, calendar: .autoupdatingCurrent) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.QuickSources.title)
            Text(Copy.QuickSources.intro).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            form
            if let note = model.note {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ScrollView { list.frame(maxWidth: .infinity, alignment: .leading) }
                .frame(maxHeight: CicadaTheme.scaled(listHeight))
        }
        .task { await model.load() }
    }

    // MARK: - The form

    private var form: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField("", text: $linkText)
                    .focused($focus, equals: .link)
                    .cicadaField(isFocused: focus == .link, prompt: Copy.QuickSources.linkPrompt,
                                 isEmpty: linkText.isEmpty)
                    .onSubmit { add() }
                if let page {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Text(page.name).font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        IconButton(systemName: "xmark", help: Copy.QuickSources.clearPage,
                                   accessibilityLabel: Copy.QuickSources.clearPage) { self.page = nil }
                    }
                    .frame(maxWidth: CicadaTheme.scaled(180), alignment: .leading)
                } else {
                    TextField("", text: $pageText)
                        .focused($focus, equals: .page)
                        .cicadaField(isFocused: focus == .page, prompt: Copy.QuickSources.pagePrompt,
                                     isEmpty: pageText.isEmpty)
                        .frame(width: CicadaTheme.scaled(180))
                }
                NeutralButton(title: Copy.QuickSources.add, size: .compact,
                              isDisabled: linkText.trimmingCharacters(in: .whitespaces).isEmpty || model.busy,
                              help: page == nil ? Copy.QuickSources.addHelpNoPage : Copy.QuickSources.addHelp) { add() }
            }
            if page == nil {
                let found = AddedSourcesLogic.pages(matching: pageText, in: store.graph.value?.nodes ?? [])
                if !found.isEmpty {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(found, id: \.id) { node in
                            Button {
                                page = node
                                pageText = ""
                            } label: {
                                Text(Eyebrow.text(node.name, node.type.rawValue))
                                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                                    .lineLimit(1)
                                    .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.menuItem),
                                           alignment: .leading)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.cicadaPlain)
                        }
                    }
                    .padding(.leading, CicadaTheme.spacingSM)
                } else if !pageText.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(Copy.QuickSources.noPage).font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
    }

    private func add() {
        let text = linkText
        let chosen = page
        Task {
            if await model.add(text, page: chosen) {
                linkText = ""
                page = nil
                pageText = ""
            }
        }
    }

    // MARK: - The list

    @ViewBuilder
    private var list: some View {
        if model.loaded && model.rows.isEmpty {
            Text(Copy.QuickSources.empty).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(model.rows) { row in rowView(row) }
            }
            if model.total > model.rows.count {
                Text(Copy.QuickSources.more(model.total - model.rows.count)).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func rowView(_ row: AddedSourceRow) -> some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: 2) {
                Text(AddedSourcesLogic.shown(row.ref)).font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1).truncationMode(.middle)
                    .help(row.ref)
                Text(Eyebrow.text(row.entityName, AddedSourcesLogic.credit(row, today: today)))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            IconButton(systemName: "xmark", help: Copy.QuickSources.removeHelp(row.entityName),
                       accessibilityLabel: Copy.QuickSources.remove) {
                Task { await model.remove(row) }
            }
            .disabled(model.busy)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }
}
