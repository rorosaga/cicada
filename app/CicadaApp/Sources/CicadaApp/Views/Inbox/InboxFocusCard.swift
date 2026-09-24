import AppKit
import SwiftUI

/// §5.3 STATE 1 — C's focus card (DR-42, DR-43): the header, the question stated once, the quote
/// hero, where it came from in a person's words, the extractor's guess, the answers, the hint and
/// Not now. Every kind renders here (`FocusCardVariant`, R-DI15). It never sends anything: an
/// answer goes to `onAnswer`, and the Store holds it for its Undo window (R-DI2). The page keys it
/// by `item.id`, so a swap is a fresh card whose seeded state never animates on mount (DR-65).
struct InboxFocusCard: View {
    let item: InboxItem
    let padding: CGFloat
    /// Close × (STATE 1 → 0). nil where there is no column to close — the Sources page (R-DI16).
    var onClose: (() -> Void)? = nil
    /// DR-27 — "‹ N questions", only while the list is hidden.
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    /// DR-28 — Esc with nothing open inside the card belongs to the page.
    var onEscape: () -> Void = {}
    /// R-DI4 — while a field here has focus, ⌘Z is the field's own.
    var onEditingChange: (Bool) -> Void = { _ in }
    let onAnswer: (QuestionResolution) -> Void

    enum Field: Hashable { case other, answer, merge }

    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @State private var selection: QuestionSelection
    @State private var otherText = ""
    @State private var showAllLines = false
    @FocusState private var field: Field?

    init(item: InboxItem, padding: CGFloat, onClose: (() -> Void)? = nil, hiddenListCount: Int? = nil,
         onShowList: @escaping () -> Void = {}, onEscape: @escaping () -> Void = {},
         onEditingChange: @escaping (Bool) -> Void = { _ in },
         onAnswer: @escaping (QuestionResolution) -> Void) {
        self.item = item
        self.padding = padding
        self.onClose = onClose
        self.hiddenListCount = hiddenListCount
        self.onShowList = onShowList
        self.onEscape = onEscape
        self.onEditingChange = onEditingChange
        self.onAnswer = onAnswer
        // G115 R6 — the first highlight is Sleep's own proposal; a conflict with none starts on row 1.
        _selection = State(initialValue: QuestionSelection(optionCount: item.options.count,
                                                           allowOther: item.allowOther,
                                                           initialIndex: item.recommendedIndex))
    }

    private var variant: FocusCardVariant { FocusCardVariant.of(item) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Text(item.questionText)
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            quote
            sourceLine
            if let guess = InboxGuess.text(item) {
                Label(guess, systemImage: "sparkles")
                    .labelStyle(.titleAndIcon)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.top, CicadaTheme.spacingXS)
            }
            variantBody.padding(.top, CicadaTheme.scaled(20))
            hintRow
            if item.allowDefer, variant != .informational, variant != .legacyDecay {
                TextButton(title: Copy.Inbox.notNowSevenDays, keyHint: "L", help: Copy.Inbox.notNowHelp) {
                    onAnswer(QuestionResolution(action: "defer", remindDays: 7))
                }
                .padding(.top, CicadaTheme.scaled(20))
                .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
        .padding(padding)
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth), alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .focusable()
        .focusEffectDisabled()
        .onChange(of: field) { _, now in onEditingChange(now != nil) }
        .onMoveCommand { direction in
            guard variant == .options, field == nil else { return }
            switch direction {
            case .down: selection.moveDown()
            case .up: selection.moveUp()
            default: break
            }
        }
        .onKeyPress(.return) {
            guard variant == .options, field == nil, let action = selection.activate() else { return .ignored }
            switch action {
            case .pick(let i): pick(i)
            case .openOther: field = .other
            default: break
            }
            return .handled
        }
        .onKeyPress(KeyEquivalent("o")) {
            guard field == nil else { return .ignored }
            switch variant {
            case .options where item.allowOther: selection.openOther(); field = .other
            case .freeText: field = .answer
            default: return .ignored
            }
            return .handled
        }
        .onKeyPress(KeyEquivalent("l")) {
            // DR-49 — a key acts only where its pointer twin is on the card: an informational card
            // shows no Not now, so L does nothing there either.
            guard field == nil, item.allowDefer, variant != .informational else { return .ignored }
            onAnswer(QuestionResolution(action: "defer", remindDays: 7))
            return .handled
        }
        .onKeyPress(characters: .decimalDigits) { press in
            guard variant == .options, field == nil, let n = Int(press.characters),
                  case .pick(let i)? = selection.pickNumber(n) else { return .ignored }
            pick(i)
            return .handled
        }
        // DR-28 — an open Other… closes in ONE press (the field loses focus and the row folds; the
        // pre-DS-2 lesson in the old question view: closing only the field left a second Esc doing nothing),
        // then another focused field, then the page's own Esc (the Reader, then the question). A
        // keyboard action never animates (DR-60): the page's Esc is `Instant.run`.
        .onKeyPress(.escape) {
            if selection.otherExpanded {
                field = nil
                _ = selection.escape()
                return .handled
            }
            if field != nil { field = nil; return .handled }
            onEscape()
            return .handled
        }
    }

    // MARK: Header — the kind glyph, the entity, Close × (and "‹ N questions" when the list hides)

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let n = hiddenListCount {
                TextButton(title: Copy.Inbox.questions(n), help: Copy.Inbox.showQuestions, action: onShowList)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
            KindGlyph(kind: item.kind)
            Text(item.displayName)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let onClose {
                IconButton(systemName: "xmark", help: Copy.Inbox.close, action: onClose)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(28))
        .padding(.bottom, CicadaTheme.spacingSM)
    }

    // MARK: The quote hero (DR-18, R-DI11, R-DI22)

    @ViewBuilder
    private var quote: some View {
        if let segments = QuoteSegments.of(item) {
            CitedSpan.text(segments)
                .font(CicadaTheme.quoteFont)
                .lineSpacing(CicadaTheme.quoteLineSpacing)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .citedSpans()
                .quoteBlock()
                .padding(.top, CicadaTheme.scaled(20))
            if QuoteSegments.isDerived(item) {
                Text(Copy.Provenance.derivedCaption)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.top, CicadaTheme.spacingXS)
            }
        } else if !item.hasCause, !item.body.isEmpty {
            // Owner defect 2 (2026-09-03) survives: a long legacy body shows three lines and "Show all N".
            // Cleaned line by line: `clean` joins lines with a space, which would fold the three kept
            // lines back into the one run-on paragraph the collapse exists to prevent.
            let collapsed = CollapsedLines(item.body)
            Text((showAllLines ? collapsed.lines : collapsed.head).map { ExcerptText.clean($0) }.joined(separator: "\n"))
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .quoteBlock()
                .padding(.top, CicadaTheme.scaled(20))
            if collapsed.needsCollapse {
                TextButton(title: showAllLines ? Copy.Inbox.showFewer : Copy.Inbox.showAll(collapsed.lines.count)) {
                    showAllLines.toggle()
                }
                .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
    }

    // MARK: The source line (DR-54) and "Show in conversation ›"

    private var sourceLine: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let origin = InboxSourceLine.markOrigin(item) {
                OriginMark(origin: origin, size: CicadaTheme.scaled(14)).markHover()
            }
            Text(InboxSourceLine.full(item))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let provenance,
               let target = item.cause?.readerTarget(subjectId: item.entityId.isEmpty ? nil : item.entityId) {
                let showing = provenance.isPresented && provenance.current?.episode == target.episode
                Button { showing ? provenance.close() : provenance.open(target) } label: {
                    HStack(spacing: CicadaTheme.scaled(3)) {
                        Text(showing ? Copy.Inbox.hideConversation : Copy.Provenance.showInConversation)
                        Image(systemName: showing ? "chevron.left" : "chevron.right").font(CicadaTheme.icon(.inline))
                    }
                }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.accentText)
                .help(showing ? Copy.Inbox.hideConversationHelp : Copy.Inbox.showConversationHelp)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(22))
        .help(InboxSourceLine.help(item) ?? "")
        .padding(.top, CicadaTheme.scaled(QuoteSegments.of(item) == nil ? 10 : 12))
    }

    // MARK: The answers

    @ViewBuilder
    private var variantBody: some View {
        switch variant {
        case .options: optionsBody
        case .informational: InformationalBody(item: item, onAnswer: onAnswer)
        case .freeText: FreeTextBody(item: item, field: $field, onAnswer: onAnswer)
        case .merge: MergeBody(item: item, field: $field, onAnswer: onAnswer)
        case .legacyDecay: LegacyDecayBody(onAnswer: onAnswer)
        case .dismissOnly: DismissBody(onAnswer: onAnswer)
        }
    }

    private var optionsBody: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.optionGap)) {
            ForEach(Array(item.options.enumerated()), id: \.element.id) { pair in
                OptionRow(option: pair.element, number: pair.offset < 9 ? pair.offset + 1 : nil,
                          highlighted: !selection.otherExpanded && selection.index == pair.offset,
                          onHover: { selection.highlight(pair.offset) }) { pick(pair.offset) }
            }
            if item.allowOther {
                OtherRow(expanded: selection.otherExpanded,
                         highlighted: selection.isOtherRow) {
                    selection.openOther()
                    field = .other
                }
                if selection.otherExpanded {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        InboxTextField(prompt: Copy.Inbox.otherPrompt, text: $otherText, isFocused: field == .other)
                            .focused($field, equals: .other)
                            .onSubmit(submitOther)
                        NeutralButton(title: Copy.Inbox.submit, keyHint: "⏎",
                                      isDisabled: otherText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                                      disabledHelp: Copy.Inbox.submitNeedsText, action: submitOther)
                    }
                    .padding(.top, CicadaTheme.spacingXS)
                }
            }
        }
    }

    // MARK: The hint (G61) — "Open source ↗"; no check line until G61 S3 serves one (R-DI13)

    @ViewBuilder
    private var hintRow: some View {
        if let hint = item.hint, !hint.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(6)) {
                Image(systemName: "link").font(CicadaTheme.icon(.inline))
                Text(hint).lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                if let url = HintLink.firstURL(in: hint) {
                    Button { NSWorkspace.shared.open(url) } label: {
                        HStack(spacing: CicadaTheme.scaled(3)) {
                            Text(Copy.Inbox.openSource)
                            Image(systemName: "arrow.up.right").font(CicadaTheme.icon(.inline))
                        }
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.accentText)
                    .help(Copy.Inbox.openSourceHelp(url.host ?? url.absoluteString))
                }
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.top, CicadaTheme.scaled(20))
        }
    }

    // MARK: Actions

    private func pick(_ i: Int) {
        guard item.options.indices.contains(i) else { return }
        onAnswer(QuestionResolution(action: "resolve", optionKey: item.options[i].key))
    }

    private func submitOther() {
        guard let r = FreeTextSubmit.resolution(for: item, text: otherText) else { return }
        onAnswer(r)
    }
}

/// The Other… row (DR-42): `OptionRow`'s anatomy with a pencil where the radio sits, "Other…" in
/// 14 medium `textSecondary` and `KeyHint("O")`. At rest `bgOption` + the resting ring; expanded or
/// highlighted, the 1.5 pt accent ring (DR-5 use 3). A click opens the field.
struct OtherRow: View {
    let expanded: Bool
    let highlighted: Bool
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var ringed: Bool { expanded || highlighted }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Image(systemName: "pencil")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(16), height: CicadaTheme.scaled(16))
                    .accessibilityHidden(true)
                Text(Copy.Inbox.other)
                    .font(CicadaTheme.font(size: 14, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                KeyHint("O")
            }
            .padding(.leading, CicadaTheme.scaled(14))
            .padding(.trailing, CicadaTheme.scaled(12))
            .frame(height: CicadaTheme.scaled(RowMetrics.option))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? OptionRow.hoverFill : CicadaTheme.bgOption))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(ringed ? CicadaTheme.accent : CicadaTheme.ring(.resting), lineWidth: ringed ? 1.5 : 1))
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Inbox.otherPrompt)
        .onHover { hovering = $0 }
        .accessibilityLabel(Copy.Inbox.other)
        .accessibilityHint(Copy.Inbox.otherPrompt)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// The card's one text input (DR-9 allows a real border on an input): 32 pt, `detailBodyFont`, a
/// `bgBase` fill and the input ring, which turns the accent at 70 % while focused (DR-5 use 1, the
/// focus ring). The caller owns focus — it applies `.focused(_:equals:)` and passes `isFocused`
/// from the same `@FocusState` — so one field never carries two focus bindings.
struct InboxTextField: View {
    let prompt: String
    @Binding var text: String
    let isFocused: Bool

    var body: some View {
        TextField(prompt, text: $text)
            .textFieldStyle(.plain)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(32))
            .frame(maxWidth: .infinity)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(isFocused ? CicadaTheme.accent.opacity(0.7) : CicadaTheme.ring(.input), lineWidth: 1))
    }
}
