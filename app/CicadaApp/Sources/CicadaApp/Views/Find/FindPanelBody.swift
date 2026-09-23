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
                // Design §3.6: a hairline while the server tier is out, drawn as an
                // overlay on the divider so it takes no layout — as a VStack child it
                // pushed every shown row down on each pause and pulled them back when
                // the server answered, breaking §3.2's "nothing shown moves" (S-ui
                // final review). Under Reduce Motion there is no indeterminate bar —
                // the footer's "Searching conversations…" is its text twin.
                Divider().background(CicadaTheme.border)
                    .overlay(alignment: .top) {
                        if model.mode == .find, model.serverPhase == .searching, !reduceMotion {
                            ProgressView().progressViewStyle(.linear).controlSize(.mini).accessibilityHidden(true)
                        }
                    }
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

    private var field: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: model.mode == .find ? "magnifyingglass" : "sparkle.magnifyingglass")
                .font(CicadaTheme.font(size: 15))
                .foregroundStyle(CicadaTheme.accent)
                .accessibilityHidden(true)
            TextField(model.mode == .find ? (prompt ?? "Search your memory") : "Ask your memory",
                      text: Binding(get: { model.fieldText }, set: { model.setFieldText($0) }))
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 15))
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
            if model.mode == .ask, model.ask.isAsking { ProgressView().controlSize(.small) }
            Picker("Find or ask", selection: Binding(get: { model.mode }, set: { newMode in
                withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) { model.setMode(newMode) }
            })) {
                Text("Find").tag(FindMode.find)
                Text("Ask").tag(FindMode.ask)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            if placement == .palette {
                Button(action: close) {
                    Image(systemName: "xmark.circle.fill")
                        .font(CicadaTheme.font(size: 14))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel("Close")
            }
        }
        .padding(CicadaTheme.spacingLG)
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
                    if let hint = model.hint {
                        Text(hint).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                            .padding(.horizontal, CicadaTheme.spacingMD)
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
        if case .settings(let section) = row.destination {
            // A menu item that promised Settings and only set the hint was a
            // lie (final review, finding 2): the one view that opens the
            // scene is the item here.
            SettingsSectionLink(section: section, label: "Open in Settings")
        } else {
            Button(FindRowText.primaryVerb(row.destination)) {
                if let destination = model.activate(row.key) { run(destination) }
            }
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
