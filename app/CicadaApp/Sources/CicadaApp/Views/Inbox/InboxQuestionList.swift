import SwiftUI

/// §5.3 — the questions, in the list column's three styles: one-line rows at full width (STATE 0),
/// the two-line triage column beside an open question (STATE 1), titles only beside the question and
/// the Reader (STATE 2). The held answer's Undo row sits where its question was (DR-42).
///
/// The stack is deliberately not lazy: an Undo row's ⌘Z must stay realised while it is scrolled out
/// of view (R-DI4), and an inbox is tens of rows, not thousands. Keys (DR-68, R-DI10): ↑/↓ move the
/// selection while the list has focus, ⏎ moves focus into the question, Esc is the page's.
struct InboxQuestionList: View {
    let entries: [InboxRowEntry]
    let style: ColumnPlan.ListStyle
    /// The plan's `list`, in points — the row slots are decided in units (R-DI26).
    let width: CGFloat
    let openId: String?
    /// R-DI4 — off while a text field on the page has focus, so the field keeps its own ⌘Z.
    let undoShortcut: Bool
    /// DR-30 — bumped by a palette or Home hand-off, so the landed row scrolls into view.
    let landingToken: Int
    let open: (InboxItem) -> Void
    let undo: () -> Void
    let move: (Int) -> Void
    let focusQuestion: () -> Void
    let escape: () -> Void
    /// Drawn after the questions at full width only — "Settled by a check" (owner ruling 2026-10-16).
    var footer: AnyView? = nil
    /// Drawn before the questions at full width only — the quick review's entry points (owner 2026-10-19).
    var header: AnyView? = nil
    /// The grouped list at full width (owner 2026-10-26, `InboxGroups`): kind headers with counts, page headers,
    /// questions. Nil draws `entries` flat, as the narrow columns always do.
    var lines: [InboxListLine]? = nil
    var toggleGroup: (InboxKind) -> Void = { _ in }
    var startReview: (ReviewKind) -> Void = { _ in }

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var padding: EdgeInsets {
        switch style {
        // 30 + a row's own 10 = the 40 gutter (§5.3 STATE 0).
        case .wide:
            EdgeInsets(top: 0, leading: CicadaTheme.scaled(30), bottom: CicadaTheme.scaled(72),
                       trailing: CicadaTheme.scaled(30))
        // The mock's CSS `0 8 24 12`.
        case .triage, .titles, .hidden:
            EdgeInsets(top: 0, leading: CicadaTheme.scaled(12), bottom: CicadaTheme.scaled(24),
                       trailing: CicadaTheme.scaled(8))
        }
    }

    var body: some View {
        // DR-58 — an age is computed when read, never stored.
        let now = Date.now
        let slots = InboxRowSlots.of(listUnits: width / CGFloat(CicadaTheme.uiScale))
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: style == .triage ? CicadaTheme.scaled(RowMetrics.twoLineGap) : 0) {
                    if style == .wide, let header { header }
                    if style == .wide, let lines {
                        // Inbox v2: a kind's header, then its body as ONE block that grows out of the header and
                        // fades in when the group opens (`disclosureReveal`), so the groups below ease down rather
                        // than jump. The ids stay on each line, so ⌘K's landing still scrolls to its row.
                        ForEach(InboxListBlock.blocks(lines)) { block in
                            VStack(spacing: 0) {
                                if let header = block.header {
                                    self.line(header, slots: slots, now: now)
                                        .padding(.top, block.isFirst ? 0 : CicadaTheme.spacingLG)
                                        .id(header.id)
                                }
                                if !block.body.isEmpty {
                                    VStack(spacing: 0) {
                                        if let kind = block.kind {
                                            InboxGroupExplainer(kind: kind)
                                        }
                                        ForEach(block.body) { line in
                                            self.line(line, slots: slots, now: now).id(line.id)
                                        }
                                    }
                                    .disclosureReveal()
                                }
                            }
                        }
                    } else {
                        ForEach(entries) { entry in
                            Group { row(entry, slots: slots, now: now) }
                                .id(entry.id)
                        }
                    }
                    if style == .wide, let footer { footer }
                }
                .padding(padding)
                // A row that leaves on the server's word fades out. The Undo row keeps its question's
                // id, so the tap itself changes no id and never animates (DR-61).
                .animation(CicadaMotion.rowLeave(reduceMotion: reduceMotion), value: entries.map(\.id))
            }
            .onChange(of: landingToken) { _, _ in
                guard let openId else { return }
                Instant.run { proxy.scrollTo(openId, anchor: .center) }
            }
        }
        .focusable()
        .focusEffectDisabled()
        .onMoveCommand { direction in
            switch direction {
            case .up: move(-1)
            case .down: move(1)
            default: break
            }
        }
        .onKeyPress(.return) {
            guard openId != nil else { return .ignored }
            focusQuestion()
            return .handled
        }
        .onExitCommand { escape() }
    }

    /// One line of the grouped list (owner 2026-10-26). A header is a disclosure, never an answer: opening or closing a
    /// group sends nothing, and the group's one action is its quick review, which still asks one question at a time.
    @ViewBuilder private func line(_ line: InboxListLine, slots: InboxRowSlots, now: Date) -> some View {
        switch line {
        case .kind(let kind, let count, let isOpen, let review):
            InboxGroupHeader(kind: kind, count: count, isOpen: isOpen, review: review,
                             toggle: { toggleGroup(kind) }, startReview: startReview)
        case .page(_, let name, let count):
            InboxPageHeader(name: name, count: count)
        case .entry(let entry, let nested):
            // Inbox v2: inside a group the kind is said once, by its header, so the row leaves its glyph out.
            row(entry, slots: slots, now: now, nested: nested, grouped: true)
        }
    }

    /// One entry's row — split out of `body`, which sat near the type checker's release-build budget.
    @ViewBuilder private func row(_ entry: InboxRowEntry, slots: InboxRowSlots, now: Date,
                                  nested: Bool = false, grouped: Bool = false) -> some View {
        switch entry {
        case .item(let item):
            InboxRow(item: item, style: style, slots: slots, selected: item.id == openId,
                     now: now, nested: nested, showsGlyph: !grouped) { open(item) }
        case .undo(let held, let item):
            InboxUndoRow(held: held, item: item, style: style,
                         shortcutEnabled: undoShortcut, onUndo: undo)
                .transition(.opacity.animation(CicadaMotion.undoFade(reduceMotion: reduceMotion)))
        }
    }
}

/// One question in the list (§5.3). The whole row opens it; the chevron is its visible twin. Depth
/// is a fill, never a lift, a scale or a shadow (DR-48); selection is a neutral fill, never the
/// accent (DR-2, `SelectionTintLintTests`).
struct InboxRow: View {
    let item: InboxItem
    let style: ColumnPlan.ListStyle
    var slots = InboxRowSlots(entity: true, source: true)
    let selected: Bool
    let now: Date
    /// Under its page's header (owner 2026-10-26): the page is said once, there, so the row leaves its name out.
    var nested = false
    /// F-09's Needs you draws the row alone — the row already opens the question (R-HO12).
    var showsOpenButton = true
    /// Inbox v2 (2026-10-26): under its kind's header the glyph would say the kind a second time on every row
    /// (DR-38); the slot stays empty so the questions still line up with the header's title.
    var showsGlyph = true
    let open: () -> Void

    @State private var hovering = false

    private var questionColor: Color { selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary }
    private var metaColor: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }
    private var questionFont: Font { CicadaTheme.font(size: 13, weight: selected ? .medium : .regular) }

    private var height: CGFloat {
        switch style {
        case .wide: RowMetrics.oneLine
        case .triage: RowMetrics.twoLine
        case .titles, .hidden: RowMetrics.titleOnly
        }
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(action: open) {
                content
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Inbox.rowAccessibility(kind: item.kind.label, question: item.questionText,
                                                             open: selected))
            .accessibilityAddTraits(selected ? .isSelected : [])
            if style == .wide && showsOpenButton {
                // Beside the row's button, never inside it: a button nested in a button is two
                // targets for one click. VoiceOver already has the row.
                IconButton(systemName: "chevron.right", help: Copy.Inbox.openQuestion, action: open)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(height: CicadaTheme.scaled(height))
        .rowHover($hovering, selected: selected)
    }

    @ViewBuilder
    private var content: some View {
        switch style {
        case .wide: wide
        case .triage: triage
        case .titles, .hidden: titles
        }
    }

    private var question: some View {
        Text(item.questionText)
            .font(questionFont)
            .foregroundStyle(questionColor)
            .lineLimit(1)
    }

    private var age: some View {
        let age = InboxRowAge.of(item, now: now)
        return Text(age.text)
            .font(CicadaTheme.metaFont)
            .monospacedDigit()
            .foregroundStyle(metaColor)
            .lineLimit(1)
            .help(age.help)
    }

    /// DR-52 — the service's real mark, then the source in a person's words; the episode id only in
    /// `.help` (DR-54).
    private var source: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            if let origin = InboxSourceLine.markOrigin(item) {
                OriginMark(origin: origin, size: CicadaTheme.scaled(12))
            }
            Text(InboxSourceLine.row(item))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(metaColor)
                .lineLimit(1)
        }
        .help(InboxSourceLine.help(item) ?? "")
    }

    /// STATE 0 — one line: glyph, question, entity, source, age. The fixed slots drop before they
    /// would overflow the column (R-DI26); the question always keeps the rest.
    private var wide: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if showsGlyph {
                KindGlyph(kind: item.kind)
            } else {
                // Under the group's title: the header's chevron slot and gap (12 + 6) plus the glyph's slot, less the
                // row's own gap after it, so the question starts where the title does.
                Color.clear.frame(width: CicadaTheme.scaled(12 + 6 + KindGlyph.slotWidth + 6) - CicadaTheme.spacingMD,
                                  height: 1)
                    .accessibilityHidden(true)
            }
            question.frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
            Spacer(minLength: 0)
            if slots.entity {
                // Say it once — a question that already names its page ("Still tracking Beta Project?") leaves the
                // column blank; the slot keeps its width so the columns still line up.
                Text(nested || InboxRowWords.namesItsPage(item) ? "" : item.displayName)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(metaColor)
                    .lineLimit(1)
                    .frame(width: CicadaTheme.scaled(180), alignment: .leading)
            }
            if slots.source {
                source.frame(width: CicadaTheme.scaled(220), alignment: .leading)
            }
            age.frame(width: CicadaTheme.scaled(InboxRowAge.slotWidth), alignment: .trailing)
        }
    }

    /// STATE 1 — two lines, nothing at a fixed width: the column can be 280 units wide.
    private var triage: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                KindGlyph(kind: item.kind)
                question
                Spacer(minLength: CicadaTheme.spacingXS)
                age
            }
            HStack(spacing: CicadaTheme.scaled(6)) {
                if !item.displayName.isEmpty && !InboxRowWords.namesItsPage(item) {
                    Text(item.displayName)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(metaColor)
                        .lineLimit(1)
                    Text(Copy.Inbox.dot).font(CicadaTheme.metaFont).foregroundStyle(metaColor)
                }
                source
            }
            .padding(.leading, CicadaTheme.scaled(22))
        }
    }

    /// STATE 2 — titles only, so the question keeps its 440; the whole question is in `.help`.
    private var titles: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            KindGlyph(kind: item.kind)
            question
        }
        .help(item.questionText)
    }
}

/// DR-42 — "Answered · sqlite-vec · Undo": the held answer, in its question's place and at its
/// height, for the Undo window. A resting ring, no fill, no shadow. It is the mock's
/// `role="status"`: VoiceOver hears what was answered, and that Undo is there, when it appears.
struct InboxUndoRow: View {
    let held: ResolveGrace
    let item: InboxItem
    let style: ColumnPlan.ListStyle
    /// Exactly one Undo row on screen owns ⌘Z (R-DI25), and never while a field has focus (R-DI4).
    let shortcutEnabled: Bool
    let onUndo: () -> Void

    private var height: CGFloat {
        switch style {
        case .wide: RowMetrics.oneLine
        case .triage: RowMetrics.twoLine
        case .titles, .hidden: RowMetrics.titleOnly
        }
    }

    private var label: some View {
        Text(style == .titles || style == .hidden ? held.shortLabel : held.label)
            .font(CicadaTheme.rowFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .lineLimit(1)
    }

    private var question: some View {
        Text(item.questionText)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(1)
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "checkmark.circle")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            switch style {
            case .wide:
                HStack(spacing: CicadaTheme.spacingMD) { label; question }
            case .triage:
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) { label; question }
            case .titles, .hidden:
                label
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.Inbox.undo, size: .compact,
                          shortcut: shortcutEnabled ? KeyboardShortcut("z", modifiers: .command) : nil,
                          help: Copy.Inbox.undoHelp, action: onUndo)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(height: CicadaTheme.scaled(height))
        .frame(maxWidth: .infinity, alignment: .leading)
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .accessibilityElement(children: .contain)
        .onAppear { AccessibilityNotification.Announcement(held.label).post() }
    }
}

/// Say it once (owner 2026-10-19) — whether a question's own words already name the page it is about, so a row (or a
/// ⌘K row, or the card's header) does not print that name a second time beside it. Review of #363: the WHOLE name as
/// whole words, diacritic-insensitive and case-insensitive after its first letter, its characters matched literally —
/// "Al" is not in "Alpha", "Go" not in "go?", "Rust" not in "trust" — and not as the start or end of a longer name:
/// "Claude" is not named by "Claude Code" (a capitalised word or a number right beside it continues the name). When in
/// doubt the name shows.
enum InboxRowWords {
    static func namesItsPage(_ item: InboxItem) -> Bool {
        repeats(name: item.displayName, in: item.questionText)
    }

    static func repeats(name: String, in text: String) -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return false }
        let pattern = "(?<![\\p{L}\\p{N}_\\-])" + NSRegularExpression.escapedPattern(for: name)
            + "(?![\\p{L}\\p{N}_\\-])"
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return false }
        let ns = text as NSString
        for match in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            // A capitalised name is never named by a lowercase word: "Go" is not in "How did it go?".
            guard ns.substring(with: match.range).first == name.first else { continue }
            let before = ns.substring(to: match.range.location)
            let after = ns.substring(from: match.range.location + match.range.length)
            if !continuesAName(word: lastWord(before)), !continuesAName(word: firstWord(after)) { return true }
        }
        // Diacritics: "Jose" names "José" — fold both once (folding is idempotent, so this recurses at most once).
        let fold: (String) -> String = { $0.folding(options: [.diacriticInsensitive], locale: nil) }
        let (n, t) = (fold(name), fold(text))
        if n != name || t != text { return repeats(name: n, in: t) }
        return false
    }

    /// The word right beside the match, across one space only: punctuation or a line between ends the name.
    private static func lastWord(_ s: String) -> String? {
        guard s.hasSuffix(" ") else { return nil }
        return s.dropLast().split(separator: " ").last.map(String.init)
    }

    private static func firstWord(_ s: String) -> String? {
        guard s.hasPrefix(" ") else { return nil }
        return s.dropFirst().split(separator: " ").first.map(String.init)
    }

    private static func continuesAName(word: String?) -> Bool {
        guard let first = word?.first else { return false }
        return first.isUppercase || first.isNumber || first == "("
    }
}

/// A kind's group in the full-width list (owner 2026-10-26): the disclosure with the kind's words and its count, and
/// the group's one action — the quick review (owner 2026-10-19), which asks its questions one at a time with the same
/// answers, the same Undo window and the same resolvers as the card. There is no answer-all: nothing here resolves
/// anything. Inbox v2 (2026-10-26): the kind's glyph leads, once, for the rows under it; the title is the plural in a
/// person's words ("Fading pages"); the review shows only while the group is open, so a closed inbox reads as kinds
/// and counts and nothing else. The header picks the motion (`DisclosureMotion`): a click eases it, a key never does.
/// A fill, never a lift (DR-48); neutral, never the accent (DR-40).
struct InboxGroupHeader: View {
    let kind: InboxKind
    let count: Int
    let isOpen: Bool
    let review: ReviewEntries.Entry?
    let toggle: () -> Void
    let startReview: (ReviewKind) -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            // Ruling 48 (17), DR-81 — a kind is a section label over its questions, never a fold.
            HStack(spacing: CicadaTheme.scaled(6)) {
                KindGlyph(kind: kind).accessibilityHidden(true)
                Text(kind.groupTitle)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(UsageFormat.count(count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Copy.Inbox.groupSpoken(kind.groupTitle, count))
            .accessibilityAddTraits(.isHeader)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let review {
                TextButton(title: Copy.Inbox.groupReview, help: Copy.Inbox.Review.entryHelp(review.kind)) {
                    startReview(review.kind)
                }
                .fixedSize()
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(height: CicadaTheme.scaled(RowMetrics.oneLine))
    }
}

/// Under an open group, what its questions ask and what the answers do, in one plain sentence (inbox v2): the
/// first-time reader's "what is this?", said once per group rather than on every row.
struct InboxGroupExplainer: View {
    let kind: InboxKind

    var body: some View {
        Text(Copy.Inbox.kindExplainer(kind))
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            // In line with the header's title: its padding, the chevron's 12 pt slot, the glyph's slot, and their gaps.
            .padding(.leading, CicadaTheme.scaled(10 + 12 + 6 + KindGlyph.slotWidth + 6))
            .padding(.bottom, CicadaTheme.spacingSM)
    }
}

/// The grouped list's lines cut into blocks for drawing: a kind's header and the lines under it, which arrive and
/// leave together as one disclosure. A kind's tab has no header: its one block is all body.
struct InboxListBlock: Identifiable {
    let id: String
    let header: InboxListLine?
    let body: [InboxListLine]
    let isFirst: Bool

    /// The kind the block is about: its header's, or — under a kind's tab, where there is no header — its questions'.
    var kind: InboxKind? {
        if case .kind(let kind, _, _, _)? = header { return kind }
        for line in body {
            switch line {
            case .entry(.item(let item), _), .entry(.undo(_, let item), _): return item.kind
            default: continue
            }
        }
        return nil
    }

    static func blocks(_ lines: [InboxListLine]) -> [InboxListBlock] {
        var out: [InboxListBlock] = []
        var header: InboxListLine?
        var body: [InboxListLine] = []
        func flush() {
            guard header != nil || !body.isEmpty else { return }
            out.append(InboxListBlock(id: header?.id ?? "block:\(out.count)", header: header, body: body,
                                      isFirst: out.isEmpty))
        }
        for line in lines {
            if case .kind = line {
                flush()
                header = line
                body = []
            } else {
                body.append(line)
            }
        }
        flush()
        return out
    }
}

/// The page two or more questions in a group are about, said once above them (owner 2026-10-26).
struct InboxPageHeader: View {
    let name: String
    let count: Int

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Text(name)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            Text(Copy.Inbox.pageQuestions(count))
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        // Under the group's kind glyph (inbox v2: past the header's chevron), a step left of the questions it heads.
        .padding(.leading, CicadaTheme.scaled(10 + 12 + 6))
        .padding(.top, CicadaTheme.spacingXS)
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.titleOnly))
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}
