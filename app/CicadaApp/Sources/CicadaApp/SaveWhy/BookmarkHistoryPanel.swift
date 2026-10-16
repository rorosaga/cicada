import AppKit
import SwiftUI

/// G191 v3 — the menu bar's Bookmarks: a Maccy-like list under the status item — a search field at the top, the
/// newest bookmarks from every browser below (picture, title, the reasons as small words, when), ⌘1…⌘9 on the first
/// nine, ↑/↓ and Return, Esc or a click elsewhere to close. A row opens the app on that bookmark's page in the Feed
/// (the saved item's detail: its reasons to edit, and Remove) — the Store is warm, so nothing reloads.
///
/// Why the Feed's item and not the link's entity page: the Feed's detail is where a saved item already lives
/// (R-DL16, DR-30's landing rule — the palette and a source page land there by media entity id), it is a Store
/// domain the app holds in memory, and it shows the link itself (its preview, where it was saved from, what an agent
/// read). The entity page is the graph's view of the same page, one click away from it ("Show on graph").
@MainActor
@Observable
final class BookmarkHistoryModel {
    var query = ""
    var selection = 0
    @ObservationIgnored private var memo: (stamp: Date?, count: Int, rows: [BookmarkHistoryRow])?

    /// Every bookmark the Store holds, newest first — recomputed only when the snapshot moved.
    func all(_ store: Store) -> [BookmarkHistoryRow] {
        let items = store.sources.value ?? []
        let stamp = store.sources.loadedAt
        if let memo, memo.stamp == stamp, memo.count == items.count { return memo.rows }
        let rows = BookmarkHistory.rows(items, projectNames: projectNames(store))
        memo = (stamp, items.count, rows)
        return rows
    }

    func shown(_ store: Store) -> [BookmarkHistoryRow] {
        let matches = BookmarkHistory.search(all(store), query: query)
        return query.isEmpty ? Array(matches.prefix(BookmarkHistory.shown)) : matches
    }

    func move(_ delta: Int, count: Int) {
        guard count > 0 else { return }
        selection = min(max(selection + delta, 0), count - 1)
    }

    private func projectNames(_ store: Store) -> [String: String] {
        var out: [String: String] = [:]
        for node in store.graph.value?.nodes ?? [] where node.type == .project { out[node.id] = node.name }
        return out
    }
}

struct BookmarkHistoryView: View {
    let model: BookmarkHistoryModel
    let onOpen: (BookmarkHistoryRow) -> Void
    let onClose: () -> Void

    @Environment(Store.self) private var store
    @FocusState private var searchFocused: Bool

    static let width: CGFloat = 400
    static let height: CGFloat = 520

    var body: some View {
        @Bindable var model = model
        let rows = model.shown(store)
        let total = model.all(store).count
        VStack(spacing: 0) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField(Copy.Bookmarks.searchPrompt, text: $model.query)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.font(size: 13))
                    .focused($searchFocused)
                    .onSubmit { if rows.indices.contains(model.selection) { onOpen(rows[model.selection]) } }
                    .onChange(of: model.query) { _, _ in model.selection = 0 }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.scaled(10))
            Divider()
            if rows.isEmpty {
                Text(total == 0 ? Copy.Bookmarks.none : Copy.Bookmarks.noMatch)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                                BookmarkHistoryRowView(row: row, index: index, selected: index == model.selection)
                                    .id(row.id)
                                    .contentShape(Rectangle())
                                    .onTapGesture { onOpen(row) }
                                    .onHover { if $0 { model.selection = index } }
                                    .contextMenu {   // Looks v2 — "Save its look" (SaveLookAction.swift)
                                        Button(Copy.Looks.saveLook) {
                                            Task { await SaveLook.perform(mediaEntityId: row.mediaEntityId,
                                                                          url: row.url, store: store) }
                                        }
                                    }
                            }
                        }
                        .padding(.vertical, CicadaTheme.scaled(4))
                    }
                    .onChange(of: model.selection) { _, i in
                        if rows.indices.contains(i) { proxy.scrollTo(rows[i].id) }
                    }
                }
            }
            Divider()
            Text(Copy.Bookmarks.footer(total))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.vertical, CicadaTheme.scaled(8))
        }
        .frame(width: Self.width, height: Self.height)
        .background(CicadaTheme.bgMenu)
        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .onKeyPress(.downArrow) { model.move(1, count: rows.count); return .handled }
        .onKeyPress(.upArrow) { model.move(-1, count: rows.count); return .handled }
        .onKeyPress(.escape) { onClose(); return .handled }
        .background(shortcuts(rows))
        .onAppear { searchFocused = true }
    }

    /// ⌘1…⌘9: the first nine rows shown.
    private func shortcuts(_ rows: [BookmarkHistoryRow]) -> some View {
        ZStack {
            ForEach(1...9, id: \.self) { n in
                Button("") { if let row = BookmarkHistory.shortcut(n, in: rows) { onOpen(row) } }
                    .keyboardShortcut(KeyEquivalent(Character(String(n))), modifiers: .command)
            }
        }
        .opacity(0)
        .accessibilityHidden(true)
    }
}

struct BookmarkHistoryRowView: View {
    let row: BookmarkHistoryRow
    let index: Int
    let selected: Bool

    static let picture: CGFloat = 36

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            picture
                .frame(width: Self.picture, height: Self.picture)
                .clipShape(CicadaTheme.shape(CicadaTheme.radiusXS + 2))
                .ringed(in: CicadaTheme.shape(CicadaTheme.radiusXS + 2))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(row.title)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Text(Copy.Bookmarks.secondLine(row))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: CicadaTheme.spacingXS)
            VStack(alignment: .trailing, spacing: CicadaTheme.scaled(2)) {
                HStack(spacing: CicadaTheme.scaled(4)) {
                    if let left = row.leftLine {
                        // G191 v4: the quiet mark — the bookmark left its browser; Cicada kept it.
                        Image(systemName: "bookmark.slash")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .help(left)
                            .accessibilityLabel(left)
                    }
                    Text(BookmarkHistory.age(row.when))
                    .font(CicadaTheme.captionFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                }
                if index < 9 {
                    Text("⌘\(index + 1)")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.scaled(6))
        // G191 v4: a bookmark no longer in its browser reads dimmed — still there to open, quieter.
        .opacity(row.leftLine == nil ? 1 : BookmarkHistory.leftOpacity)
        .background(selected ? CicadaTheme.bgSelected : Color.clear)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }

    @ViewBuilder
    private var picture: some View {
        switch row.picture {
        case .capture(let path), .preview(let path):
            StoredPreview(path: path) { monogram }
        case .monogram:
            monogram
        }
    }

    private var monogram: some View {
        ZStack {
            CicadaTheme.bgHover
            Text(BookmarkHistory.monogram(row.host.isEmpty ? row.title : row.host))
                .font(CicadaTheme.font(size: 15, weight: .semibold))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }
}

/// The panel that holds the list: a borderless panel under the status item that takes the keyboard (the search field)
/// without activating the app, closed by Esc, a click elsewhere, or opening a row.
final class BookmarkHistoryNSPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class BookmarkHistoryController {
    private var panel: BookmarkHistoryNSPanel?
    private var monitors: [Any] = []
    private let model = BookmarkHistoryModel()

    var isShowing: Bool { panel != nil }

    /// Show under `anchor` (the status item's button frame, screen coordinates), or close when already open.
    func toggle(store: Store, anchor: NSRect?, onOpen: @escaping (BookmarkHistoryRow) -> Void) {
        if panel != nil { close(); return }
        model.query = ""
        model.selection = 0
        let view = BookmarkHistoryView(model: model, onOpen: { [weak self] row in
            self?.close()
            onOpen(row)
        }, onClose: { [weak self] in self?.close() })
            .environment(store)
        let panel = BookmarkHistoryNSPanel(contentRect: .zero, styleMask: [.nonactivatingPanel, .borderless],
                                           backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = .popUpMenu
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        let host = NSHostingView(rootView: view)
        panel.contentView = host
        let size = CGSize(width: BookmarkHistoryView.width, height: BookmarkHistoryView.height)
        panel.setFrame(Self.frame(size: size, anchor: anchor, screen: NSScreen.main?.visibleFrame), display: false)
        panel.makeKeyAndOrderFront(nil)
        self.panel = panel
        if let global = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: {
            [weak self] _ in Task { @MainActor in self?.close() }
        }) { monitors.append(global) }
    }

    /// Under the anchor, its right edge kept on the screen; the screen's top right without one.
    nonisolated static func frame(size: CGSize, anchor: NSRect?, screen: NSRect?) -> NSRect {
        let visible = screen ?? NSRect(x: 0, y: 0, width: 1440, height: 876)
        let top = anchor?.minY ?? visible.maxY
        var x = (anchor?.midX ?? visible.maxX) - size.width / 2
        x = min(max(x, visible.minX + 8), visible.maxX - size.width - 8)
        return NSRect(x: x.rounded(), y: (top - size.height - 4).rounded(), width: size.width, height: size.height)
    }

    func close() {
        monitors.forEach(NSEvent.removeMonitor)
        monitors.removeAll()
        panel?.orderOut(nil)
        panel = nil
    }
}
