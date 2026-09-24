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
                    ForEach(entries) { entry in
                        Group {
                            switch entry {
                            case .item(let item):
                                InboxRow(item: item, style: style, slots: slots, selected: item.id == openId,
                                         now: now) { open(item) }
                            case .undo(let held, let item):
                                InboxUndoRow(held: held, item: item, style: style,
                                             shortcutEnabled: undoShortcut, onUndo: undo)
                                    .transition(.opacity.animation(CicadaMotion.undoFade(reduceMotion: reduceMotion)))
                            }
                        }
                        .id(entry.id)
                    }
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
            if style == .wide {
                // Beside the row's button, never inside it: a button nested in a button is two
                // targets for one click. VoiceOver already has the row.
                IconButton(systemName: "chevron.right", help: Copy.Inbox.openQuestion, action: open)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(height: CicadaTheme.scaled(height))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
        .onHover { hovering = $0 }
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
            KindGlyph(kind: item.kind)
            question.frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
            Spacer(minLength: 0)
            if slots.entity {
                Text(item.displayName)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(metaColor)
                    .lineLimit(1)
                    .frame(width: CicadaTheme.scaled(180), alignment: .leading)
            }
            if slots.source {
                source.frame(width: CicadaTheme.scaled(220), alignment: .leading)
            }
            age.frame(width: CicadaTheme.scaled(30), alignment: .trailing)
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
                if !item.displayName.isEmpty {
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
            .font(CicadaTheme.font(size: 13, weight: .medium))
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
                .font(CicadaTheme.font(size: 14))
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
