import SwiftUI

/// The palette's body — field, Find/Ask switch, and the grouped rows or the
/// Ask answer (G136; round-3 design §3). Exposed on its own so the upcoming
/// Home page (Track I, decision 12) hosts the same search field in-page; the
/// overlay chrome is `FindPalette`'s. `open` runs what a row navigates to —
/// the host owns the tabs, the sheets and the router.
struct FindPanelBody: View {
    enum Placement { case palette, page }

    let model: FindPaletteModel
    var placement: Placement = .palette
    let open: (FindDestination) -> Void
    var close: () -> Void = {}

    @FocusState private var fieldFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            field
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
        .onExitCommand { if model.escape() { close() } }
        .defaultFocus($fieldFocused, true)
        .task { fieldFocused = true }
    }

    private var field: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: model.mode == .find ? "magnifyingglass" : "sparkle.magnifyingglass")
                .font(CicadaTheme.font(size: 15))
                .foregroundStyle(CicadaTheme.accent)
                .accessibilityHidden(true)
            TextField(model.mode == .find ? "Search your memory" : "Ask your memory",
                      text: Binding(get: { model.fieldText }, set: { model.setFieldText($0) }))
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 15))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($fieldFocused)
                .onSubmit { if let destination = model.submit() { run(destination) } }
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
                    ? "Type to find anything Cicada remembers — people, projects, conversations, saved links."
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
            Text(section.group.title.uppercased())
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .tracking(1.2)
            Spacer()
            if let count = section.headerCount {
                Text(count).font(CicadaTheme.font(size: 10, design: .monospaced))
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
                .font(CicadaTheme.font(size: 10, design: .monospaced))
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
