import SwiftUI

/// The palette's body — field, Find/Ask switch, and the grouped rows or the
/// Ask answer (G136; round-3 design §3). Exposed on its own so the upcoming
/// Home page (Track I, decision 12) hosts the same search field in-page; the
/// overlay chrome is `FindPalette`'s. `open` runs what a row navigates to —
/// the host owns the tabs, the sheets and the router.
///
/// Track I part b (R-IB6) hosts it on Home with three additive parameters
/// whose defaults keep the palette byte for byte: `prompt` (Home's own
/// placeholder), `focusRequest` (a nonce whose change focuses the field — ⌘K
/// and ⌘1 on Home) and `submitOverride` (⏎ saves a pasted link, R-IB7; it
/// returns true when it handled the submit). On a page, Esc runs
/// `model.escape()` and never closes anything — `close` stays a no-op there.
struct FindPanelBody: View {
    enum Placement { case palette, page }

    let model: FindPaletteModel
    var placement: Placement = .palette
    let open: (FindDestination) -> Void
    var close: () -> Void = {}
    var prompt: String? = nil
    var focusRequest: Int = 0
    var submitOverride: (() -> Bool)? = nil

    @FocusState private var fieldFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// R-IB6 — the palette always shows its rows; a page shows only its field until
    /// there is something to show (the first keystroke, or Ask). Design H2: the
    /// first keystroke replaces Home's cards.
    static func showsBody(placement: Placement, query: String, mode: FindMode) -> Bool {
        placement == .palette || mode == .ask || !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            field
            if Self.showsBody(placement: placement, query: model.query, mode: model.mode) {
                // Design §3.6 / DR-43 (round 3, 2026-10-20): while the server tier is out the footer says so in words
                // ("Searching conversations…", the live region) — no indeterminate bar over the divider, which was the
                // palette's own spinner. Nothing shown moves (§3.2): the rows already standing stay put.
                Divider().background(CicadaTheme.border)
                Group {
                    if model.mode == .ask {
                        AskPanel(onSelectEntity: { run(.entity(id: $0)) }, hostedViewModel: model.ask)
                    } else {
                        rows
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .background(CicadaTheme.surface)   // R-SU17: opaque content, no glass on glass
                footer
            }
        }
        .onExitCommand { if model.escape() { close() } }
        .defaultFocus($fieldFocused, true)
        .task { fieldFocused = true }
        .onChange(of: focusRequest) { _, _ in fieldFocused = true }
    }

    /// ROR-118 (round 1, Home) — on Home the field is the page's one lead: 17 pt type and 6 pt more air above and below
    /// than the palette's 15 pt field (`.page` placement only; the palette is unchanged).
    private var fieldSize: CGFloat { placement == .page ? 17 : 15 }

    private var field: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            // Home review #10 (DR-5) — a field glyph is not one of the accent's six uses.
            Image(systemName: model.mode == .find ? "magnifyingglass" : "sparkle.magnifyingglass")
                .font(CicadaTheme.font(size: fieldSize))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            TextField(model.mode == .find ? (prompt ?? "Search your memory") : "Ask your memory",
                      text: Binding(get: { model.fieldText }, set: { model.setFieldText($0) }))
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: fieldSize))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($fieldFocused)
                .onSubmit {
                    if submitOverride?() == true { return }
                    if let destination = model.submit() { run(destination) }
                }
                .onKeyPress(phases: .down) { press in
                    handle(FindKeymap.action(key: press.key, modifiers: press.modifiers, mode: model.mode))
                }
                .accessibilityLabel(model.mode == .find ? "Search your memory" : "Ask your memory")
            // Home review #10 — DR-45 text tabs inside the field (26 pt, `bgSelected` when active), never the native
            // segmented control, whose selected segment paints the accent (DR-5). One mode is always on: tapping the
            // active tab keeps it. The switch is instant (DR-60/61): ⌘⏎ and a click share this path.
            if placement == .page {
                FindModeSwitch(mode: Binding(get: { model.mode }, set: { model.setMode($0) }))
            } else {
                TextTabs(tabs: [TextTab(id: FindMode.find, label: "Find"), TextTab(id: FindMode.ask, label: "Ask")],
                         selection: Binding(get: { model.mode }, set: { if let mode = $0 { model.setMode(mode) } }),
                         showsCounts: false)
                    .fixedSize()
                    .accessibilityLabel("Find or ask")
            }
            if placement == .palette {
                Button(action: close) {
                    Image(systemName: "xmark.circle.fill")
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel("Close")
            }
        }
        .padding(.horizontal, CicadaTheme.spacingLG)
        .padding(.vertical, CicadaTheme.spacingLG + (placement == .page ? CicadaTheme.scaled(6) : 0))
    }

    private var rows: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    if model.results.rowCount == 0 { emptyMessage }
                    ForEach(model.sections) { section in
                        if section.group != .ask { header(section) }
                        ForEach(section.rows) { row in
                            FindRowView(row: row, selected: row.key == model.selection)
                                .id(row.key)
                                .onTapGesture { if let destination = model.activate(row.key) { run(destination) } }
                                .contextMenu { menu(for: row) }
                        }
                        if let more = section.more { moreRow(section.group, more) }
                    }
                    if model.offersSearchDeeper {
                        Button { model.searchDeeper() } label: {
                            Label("Search deeper", systemImage: "sparkle.magnifyingglass").font(CicadaTheme.captionFont)
                        }
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .help("Also find things that mean the same, not only the same words")
                    }
                }
                .padding(CicadaTheme.spacingSM)
            }
            .onChange(of: model.selection) { _, key in
                guard let key else { return }
                proxy.scrollTo(key)
                if let text = model.selectionAnnouncement { AccessibilityNotification.Announcement(text).post() }
            }
        }
    }

    private var emptyMessage: some View {
        let trimmed = model.query.trimmingCharacters(in: .whitespacesAndNewlines)
        return Text(trimmed.isEmpty
                    // Only what a search actually reaches (final review,
                    // finding 4): conversations and beliefs arrive with the
                    // server tier (G136 S4), so they are named now.
                    ? "Type to find anything Cicada remembers — people, projects, conversations, beliefs, saved links, questions and settings."
                    : "Nothing matches “\(trimmed)”.")
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingMD)
    }

    private func header(_ section: FindSection) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: section.group.glyph)
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .iconHover()
            SectionLabel(section.group.title)
            Spacer()
            if let count = section.headerCount {
                Text(count).font(CicadaTheme.font(size: 10).monospacedDigit())
            }
        }
        .foregroundStyle(CicadaTheme.textTertiary)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.top, CicadaTheme.spacingSM)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private func moreRow(_ group: FindGroupID, _ more: FindCount) -> some View {
        Button {
            withAnimation(CicadaMotion.groupExpand(reduceMotion: reduceMotion)) { model.toggleExpanded(group) }
        } label: {
            Text(FindRowText.moreLabel(more)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.accent)
        }
        .buttonStyle(.cicadaPlain)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .accessibilityLabel("\(FindRowText.moreLabel(more)) in \(group.title)")
    }

    @ViewBuilder
    private func menu(for row: FindRow) -> some View {
        Button(FindRowText.primaryVerb(row.destination)) {
            if let destination = model.activate(row.key) { run(destination) }
        }
        if let verb = FindRowText.secondaryVerb(row.secondary) {
            Button(verb) { if let destination = model.activate(row.key, secondary: true) { run(destination) } }
        }
    }

    private var footer: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(model.footerText)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityAddTraits(.updatesFrequently)
            Spacer()
            Text(model.mode == .find ? "↑↓ move · ⏎ open · ⌥⏎ more · ⌘⏎ ask · esc close"
                                     : "⏎ ask · esc back to find")
                .font(CicadaTheme.font(size: 10))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
        }
        .padding(.horizontal, CicadaTheme.spacingLG)
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    private func handle(_ action: FindKeyAction) -> KeyPress.Result {
        switch action {
        case .none: return .ignored
        case .move(let step): model.move(step)
        case .secondary:
            if let key = model.selection, let destination = model.activate(key, secondary: true) { run(destination) }
        case .askNow: model.askNow()
        case .escape: if model.escape() { close() }
        }
        return .handled
    }

    private func run(_ destination: FindDestination) {
        open(destination)
        if placement == .palette { close() }
    }
}

/// ROR-118 round 2 (Home; DR-45's text tabs, one level up) — Home's Find / Ask switch: two words in a recessed trough
/// with the active one raised (`bgButton` in dark, white in light, the resting ring, primary ink), so which mode is on reads at a glance; the
/// palette keeps its `TextTabs`. One mode is always on and the switch is instant (DR-60/61): a click and ⌘⏎ share
/// `model.setMode`.
struct FindModeSwitch: View {
    @Binding var mode: FindMode

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(2)) {
            segment("Find", .find)
            segment("Ask", .ask)
        }
        .padding(CicadaTheme.scaled(3))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall + 3).fill(CicadaTheme.bgRail))
        .padding(.leading, CicadaTheme.spacingSM)
        .fixedSize()
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Find or ask")
    }

    private func segment(_ label: String, _ value: FindMode) -> some View {
        let active = mode == value
        return Button { mode = value } label: {
            Text(label)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(active ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.scaled(12))
                .frame(height: CicadaTheme.scaled(26))
                .background {
                    if active {
                        CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                            .fill(CicadaTheme.mode == .dark ? CicadaTheme.bgButton : CicadaTheme.bgFocus)
                            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(active ? [.isSelected] : [])
    }
}
