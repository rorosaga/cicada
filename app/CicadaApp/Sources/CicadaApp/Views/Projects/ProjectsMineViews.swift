import SwiftUI

// Projects v2 (TODO ruling 45) — the person's own list and what Cicada suggests, the editable header, and the
// "project knowledge" side panel (Q7, DESIGN_RULES §9 2026-10-27). Direction D: SF only, depth is a ring (DR-9),
// grouped blocks on `bgOption`, both suggestion buttons neutral (DR-40), folds remembered (DR-39), one text field
// (DR-76), one labelled add button (DR-75), one primary action per sheet (DR-40).

// MARK: - Suggested

/// The list's Suggested fold, under Fading: each suggestion with where it came from, "Add to my projects" and "Not
/// mine" (both neutral, DR-40); dismissed ones behind "N dismissed · Show". Nothing here deletes anything.
struct ProjectsSuggestedSection: View {
    let suggested: [SuggestedProject]
    let isOpen: Bool
    @Binding var showDismissed: Bool
    let blocked: Bool
    let toggle: () -> Void
    let accept: (SuggestedProject) -> Void
    let dismiss: (SuggestedProject) -> Void
    /// The narrow triage column: every row stacks its buttons under its words (never a truncated label).
    var compact = false

    private var live: [SuggestedProject] { suggested.filter { !$0.dismissed } }
    private var gone: [SuggestedProject] { suggested.filter(\.dismissed) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            DisclosureHeader(title: Copy.ProjectsMine.suggested, summary: UsageFormat.count(live.count),
                             summaryWhenOpen: true, isOpen: isOpen, help: Copy.ProjectsMine.suggestedHelp,
                             fillsWidth: true, toggle: toggle)
                .padding(.horizontal, CicadaTheme.scaled(10))
            if isOpen {
                Text(Copy.ProjectsMine.suggestedIntro)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.scaled(10))
                ForEach(live) { s in
                    SuggestedProjectRow(suggestion: s, blocked: blocked, accept: { accept(s) },
                                        dismiss: { dismiss(s) }, compact: compact)
                }
                if !gone.isEmpty {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Text(Copy.ProjectsMine.dismissedCount(gone.count))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        TextButton(title: showDismissed ? Copy.ProjectsMine.hide : Copy.ProjectsMine.show,
                                   action: { showDismissed.toggle() })
                    }
                    .padding(.horizontal, CicadaTheme.scaled(10))
                    if showDismissed {
                        ForEach(gone) { s in
                            SuggestedProjectRow(suggestion: s, blocked: blocked, accept: { accept(s) }, dismiss: nil,
                                                compact: compact)
                        }
                    }
                }
            }
        }
    }
}

/// One suggestion: its name, the reason with its glyph (a repository, the person's located sentence, an agent's
/// proposal, a provider's project, a fallback page), and the two neutral buttons.
struct SuggestedProjectRow: View {
    let suggestion: SuggestedProject
    let blocked: Bool
    let accept: () -> Void
    let dismiss: (() -> Void)?
    /// Always the stacked layout (the narrow column); otherwise beside when it fits.
    var compact = false

    private var glyph: some View {
        Image(systemName: Copy.ProjectsMine.reasonGlyph(suggestion.whyKind))
            .font(CicadaTheme.icon(.inline))
            .foregroundStyle(CicadaTheme.textTertiary)
            .frame(width: CicadaTheme.scaled(16))
            .padding(.top, CicadaTheme.scaled(2))
    }

    private var words: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
            Text(suggestion.name)
                .font(CicadaTheme.rowFont)
                .foregroundStyle(suggestion.dismissed ? CicadaTheme.textSecondary : CicadaTheme.textPrimary)
                .lineLimit(1)
            Text(suggestion.why)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            if let quote = suggestion.quote, !quote.isEmpty {
                Text("“\(quote)”")   // count-lint:ok — the person's sentence, no number
                    .font(CicadaTheme.metaFont.italic())
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2)
            }
        }
    }

    /// The words over the buttons; the reason wraps, a label never truncates.
    private var stacked: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            glyph
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                words
                buttons.fixedSize()
            }
            Spacer(minLength: 0)
        }
    }

    private var buttons: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            NeutralButton(title: Copy.ProjectsMine.addToMine, size: .compact, isDisabled: blocked,
                          disabledHelp: Copy.Projects.sleepBusy, action: accept)
            if let dismiss {
                NeutralButton(title: Copy.ProjectsMine.notMine, size: .compact, isDisabled: blocked,
                              help: Copy.ProjectsMine.notMineHelp, disabledHelp: Copy.Projects.sleepBusy,
                              action: dismiss)
            }
        }
    }

    var body: some View {
        // A row wide enough holds the buttons beside the words; the narrow triage column puts them under the words,
        // never truncated.
        Group {
            if compact {
                stacked
            } else {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                        glyph
                        words.fixedSize(horizontal: true, vertical: false)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        buttons.fixedSize()
                    }
                    stacked
                }
            }
        }
        .padding(CicadaTheme.scaled(10))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .accessibilityElement(children: .contain)
    }
}

// MARK: - New project / name it

/// New project (DR-75's one add button opens it): a name and a description, both `cicadaField` (DR-76), one primary
/// Create (DR-40). A provider grouping's accept reuses it with the name alone.
struct ProjectNameSheet: View {
    let title: String
    var message: String? = nil
    var asksDescription = true
    var confirm = Copy.ProjectsMine.create
    let submit: (String, String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var description = ""
    @FocusState private var focus: Int?

    private var ready: Bool { !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(title).font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22)).foregroundStyle(CicadaTheme.textPrimary)
            if let message {
                Text(message).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            TextField("", text: $name)
                .focused($focus, equals: 0)
                .cicadaField(isFocused: focus == 0, prompt: Copy.ProjectsMine.namePlaceholder, isEmpty: name.isEmpty)
                .accessibilityLabel(Copy.ProjectsMine.nameField)
                .onSubmit { if asksDescription { focus = 1 } else { send() } }
            if asksDescription {
                TextField("", text: $description, axis: .vertical)
                    .lineLimit(1...4)
                    .focused($focus, equals: 1)
                    .cicadaField(isFocused: focus == 1, prompt: Copy.ProjectsMine.descriptionPlaceholder,
                                 isEmpty: description.isEmpty)
                    .accessibilityLabel(Copy.ProjectsMine.descriptionField)
                    .onSubmit { send() }
            }
            HStack {
                Spacer()
                NeutralButton(title: Copy.ProjectsMine.cancel, shortcut: .cancelAction) { dismiss() }
                PrimaryActionButton(title: confirm) { send() }
                    .disabled(!ready)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(440))
        .background(CicadaTheme.bgBase)
        .onAppear { focus = 0 }
    }

    private func send() {
        guard ready else { return }
        submit(name.trimmingCharacters(in: .whitespacesAndNewlines),
               description.trimmingCharacters(in: .whitespacesAndNewlines))
        dismiss()
    }
}

// MARK: - The header

/// The project's head (DR-74's focus-card head line): the name as the 22 pt H1 and the person's description as body
/// prose, both edited in place on a click (⏎ saves, Esc cancels), then one meta line: how it came to be theirs and who
/// last set the description, with that agent's mark (DR-52).
struct ProjectHeaderEditor: View {
    let ref: ProjectRef
    let blocked: Bool
    let save: (_ name: String?, _ description: String?) -> Void

    @State private var editing: Field?
    @State private var draft = ""
    @FocusState private var focused: Bool

    enum Field { case name, description }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            if editing == .name {
                field(prompt: Copy.ProjectsMine.namePlaceholder, font: CicadaTheme.rowFont)
            } else {
                Text(ref.name)
                    .font(CicadaTheme.displayFont(size: 22))
                    .tracking(CicadaTheme.displayTracking(size: 22))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .onTapGesture { begin(.name, ref.name) }
                    .help(blocked ? Copy.Projects.sleepBusy : Copy.ProjectsMine.editNameHelp)
                    .accessibilityAddTraits(.isHeader)
            }
            if editing == .description {
                field(prompt: Copy.ProjectsMine.descriptionPlaceholder, font: CicadaTheme.detailBodyFont)
            } else if let text = ref.description, !text.isEmpty {
                Text(text)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .onTapGesture { begin(.description, text) }
                    .help(blocked ? Copy.Projects.sleepBusy : Copy.ProjectsMine.editDescriptionHelp)
            } else {
                TextButton(title: Copy.ProjectsMine.addDescription, action: { begin(.description, "") })
                    .disabled(blocked)
            }
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.ProjectsMine.startedLine(ref.mine ? ref.mineVia : nil, day: ref.created))
                if let by = ref.descriptionBy, ref.description != nil {
                    Text("·")
                    if !by.isPerson { OriginMark(origin: by.by, size: 12) }
                    Text(Copy.ProjectsMine.editedBy(by.by, day: by.day))
                }
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(1)
        }
        // Review of #493: a draft is never lost — clicking elsewhere (another project, which rebuilds this column)
        // saves it to THIS project, as ⏎ would; only Esc drops it.
        .onChange(of: focused) { _, isFocused in
            if !isFocused, editing != nil { commit() }
        }
        .onDisappear { if editing != nil { commit() } }
    }

    private func field(prompt: String, font: Font) -> some View {
        TextField("", text: $draft, axis: editing == .description ? .vertical : .horizontal)
            .font(font)
            .focused($focused)
            .cicadaField(isFocused: focused, prompt: prompt, isEmpty: draft.isEmpty)
            .onSubmit { commit() }
            // Esc cancels: `editing` goes first, so the focus loss that follows saves nothing.
            .onExitCommand { Instant.run { editing = nil } }
            .onAppear { focused = true }
    }

    private func begin(_ field: Field, _ text: String) {
        guard !blocked else { return }
        draft = text
        editing = field
    }

    private func commit() {
        if let change = ProjectHeaderDraft.change(editing, draft: draft, ref: ref) { save(change.name, change.description) }
        editing = nil
    }
}

// MARK: - The knowledge panel

/// The "project knowledge" column (Q7, Claude-desktop style): what fed the project beside what happened. Conversations
/// with why each is tied (the line under the list says it in words, so hover is never the only explanation — P-h),
/// Sources & influences grouped by kind with Add an influence, and what a provider project carried.
struct ProjectKnowledgePanel: View {
    let timeline: ProjectTimeline
    let conversations: ProjectConversationsPage?
    let blocked: Bool
    let openConversation: (ProjectConversationRow) -> Void
    let untie: (ProjectConversationRow) -> Void
    let openEntity: (String) -> Void
    let addInfluence: () -> Void
    let undoInfluence: (ProjectInfluence) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            block {
                header(Copy.ProjectsMine.conversations(conversations?.total ?? timeline.conversationCount))
                if let page = conversations, !page.conversations.isEmpty {
                    ForEach(page.conversations.prefix(30)) { row in conversationRow(row) }
                    let why = Copy.ProjectsMine.whyLine(page.counts)
                    if !why.isEmpty {
                        Text(why).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            .help(Copy.ProjectsMine.tieHelp)
                    }
                } else {
                    Text(Copy.ProjectsMine.noConversations)
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            block {
                HStack {
                    header(Copy.ProjectsMine.influences(timeline.influences.count))
                    Spacer()
                    TextButton(title: Copy.ProjectsMine.addInfluence, action: addInfluence).disabled(blocked)
                }
                if timeline.influences.isEmpty {
                    Text(Copy.ProjectsMine.noInfluences)
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(groups, id: \.0) { tag, rows in
                    // A kind the record knows labels its group; the rest sit under no label (never "Thing").
                    if !tag.isEmpty { SectionLabel(tag).padding(.top, CicadaTheme.scaled(2)) }
                    ForEach(rows) { influenceRow($0) }
                }
            }
            ForEach(timeline.knowledge, id: \.projectId) { k in
                block {
                    header(Copy.ProjectsMine.fromProvider(k.provider))
                    if let text = k.instructions, !text.isEmpty {
                        Text(Copy.ProjectsMine.instructions).font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(6)
                    }
                    if !k.docs.isEmpty {
                        Text(Copy.ProjectsMine.documents).font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        ForEach(k.docs, id: \.self) { doc in
                            Label(doc, systemImage: "doc").font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                        }
                    }
                }
            }
        }
    }

    private var groups: [(String, [ProjectInfluence])] {
        var order: [String] = []
        var by: [String: [ProjectInfluence]] = [:]
        for row in timeline.influences {
            let tag = ProjectInfluence.knownTags.contains(row.tag) ? row.tag : ""
            if by[tag] == nil { order.append(tag) }
            by[tag, default: []].append(row)
        }
        // The unlabelled group comes last.
        return order.filter { !$0.isEmpty }.map { ($0, by[$0] ?? []) } + (by[""].map { [("", $0)] } ?? [])
    }

    private func block<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) { content() }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgOption))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }

    private func header(_ text: String) -> some View {
        Text(text).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
    }

    private func conversationRow(_ row: ProjectConversationRow) -> some View {
        Button { openConversation(row) } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: row.harness ?? row.origin ?? "mcp", size: 14)
                Text(row.title.isEmpty ? Copy.Projects.page : row.title)
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingXS)
                if let day = Copy.ProjectsMine.day(row.day) {
                    Text(day).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(row.why.map { Copy.ProjectsMine.why($0, provider: row.providerLabel) }.joined(separator: " · "))
        .contextMenu {
            Button(Copy.ProjectsMine.notAboutThis) { untie(row) }.disabled(blocked)
        }
    }

    private func influenceRow(_ row: ProjectInfluence) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                if let entity = row.entity {
                    Button { openEntity(entity) } label: {
                        Text(row.label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    .buttonStyle(.cicadaPlain)
                } else if let url = row.url, let link = URL(string: url) {
                    Link(destination: link) {
                        Text(row.label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                    }
                } else {
                    Text(row.label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textPrimary)
                }
                Text(Copy.ProjectsMine.influenceBy(row.by, day: row.day))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer(minLength: CicadaTheme.spacingXS)
            if row.by == "user" && row.undoable {
                TextButton(title: Copy.ProjectsMine.undo, action: { undoInfluence(row) }).disabled(blocked)
            }
        }
    }
}

// MARK: - Add an influence

/// Add an influence (mockup 3): step 1 a field plus option rows — the pages already in memory first, "Something new"
/// last, a link when it is one (DR-42: one tap picks); step 2 an optional "how" chip and the person's own sentence,
/// then one primary "Add influence". A name that matches no page stays plain text (Q9).
struct AddInfluenceSheet: View {
    let candidates: [(id: String, name: String, type: String)]
    let submit: (_ url: String?, _ what: String?, _ entity: String?, _ how: String?, _ note: String?) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var picked: Pick?
    @State private var how = "inspired"
    @State private var note = ""
    @FocusState private var focused: Bool

    enum Pick: Equatable { case link(String), page(String, String), new(String) }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var isLink: Bool { trimmed.lowercased().hasPrefix("http://") || trimmed.lowercased().hasPrefix("https://") }
    private var matches: [(id: String, name: String, type: String)] {
        guard trimmed.count >= 2, !isLink else { return [] }
        let q = trimmed.lowercased()
        return Array(candidates.filter { $0.name.lowercased().contains(q) }.prefix(5))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.ProjectsMine.influenceTitle).font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textPrimary)
            if let picked { stepTwo(picked) } else { stepOne }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(480))
        .background(CicadaTheme.bgBase)
    }

    private var stepOne: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            TextField("", text: $text)
                .focused($focused)
                .cicadaField(isFocused: focused, prompt: Copy.ProjectsMine.influencePlaceholder, isEmpty: text.isEmpty)
                .onAppear { focused = true }
            if isLink {
                option(Copy.ProjectsMine.aLink(trimmed), glyph: "link") { picked = .link(trimmed) }
            } else if !trimmed.isEmpty {
                if !matches.isEmpty { SectionLabel(Copy.ProjectsMine.alreadyInMemory) }
                ForEach(matches, id: \.id) { m in
                    option(m.name, glyph: "circle.fill") { picked = .page(m.id, m.name) }
                }
                option(Copy.ProjectsMine.somethingNew(trimmed), glyph: "plus") { picked = .new(trimmed) }
            }
            HStack { Spacer(); NeutralButton(title: Copy.ProjectsMine.cancel, shortcut: .cancelAction) { dismiss() } }
        }
    }

    private func stepTwo(_ pick: Pick) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.ProjectsMine.howTitle)
            Picker("", selection: $how) {
                Text(Copy.ProjectsMine.howInspired).tag("inspired")
                Text(Copy.ProjectsMine.howReference).tag("reference")
                Text(Copy.ProjectsMine.howUses).tag("uses")
                Text(Copy.ProjectsMine.howPerson).tag("person")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            TextField("", text: $note, axis: .vertical)
                .lineLimit(1...4)
                .cicadaField(prompt: Copy.ProjectsMine.notePlaceholder, isEmpty: note.isEmpty)
            HStack {
                TextButton(title: Copy.ProjectsMine.back, action: { picked = nil })
                Spacer()
                PrimaryActionButton(title: Copy.ProjectsMine.addInfluenceButton) { send(pick) }
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private func option(_ title: String, glyph: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: glyph).font(CicadaTheme.icon(.badge)).foregroundStyle(CicadaTheme.textTertiary)
                Text(title).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer()
            }
            .padding(CicadaTheme.scaled(10))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
    }

    private func send(_ pick: Pick) {
        let words = note.trimmingCharacters(in: .whitespacesAndNewlines)
        switch pick {
        case .link(let url): submit(url, nil, nil, how, words.isEmpty ? nil : words)
        case .page(let id, _): submit(nil, nil, id, how, words.isEmpty ? nil : words)
        case .new(let name): submit(nil, name, nil, how, words.isEmpty ? nil : words)
        }
        dismiss()
    }
}

/// Q7 (DESIGN_RULES §9, 2026-10-27): the card and the knowledge panel side by side when there is room, the panel folded
/// under the card when there is not.
enum ProjectKnowledgeLayout {
    static let panelWidth: CGFloat = 312
    static let cardWidth: CGFloat = 640
    static let gap: CGFloat = 24

    static func sideBySide(available: CGFloat) -> Bool {
        available >= CicadaTheme.scaled(cardWidth * 0.85 + panelWidth + gap)
    }
}


/// What a header edit sends, if anything: a non-empty new name, or a description that differs (an empty one clears it).
enum ProjectHeaderDraft {
    static func change(_ field: ProjectHeaderEditor.Field?, draft: String, ref: ProjectRef)
        -> (name: String?, description: String?)? {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        switch field {
        case .name where !text.isEmpty && text != ref.name: return (text, nil)
        case .description where text != (ref.description ?? ""): return (nil, text)
        default: return nil
        }
    }
}
