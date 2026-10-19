import SwiftUI

/// The quick review (owner 2026-10-19), inside the Inbox page — not a new window: one kind at a time, one card at a
/// time, the same answers in the same place. DR-25 (the eyebrow carries the place: "Inbox · Fading pages · 3 of 49"),
/// DR-36 (the card is capped like the focus card), DR-40 (answers are option rows and neutral buttons, Skip and End
/// are text buttons; no primary action), DR-42 (an option row answers in one tap, and the answer is held for the
/// Inbox's own Undo window — nothing new writes), DR-49 (every key shows its hint beside its pointer twin), DR-54 (a
/// source in a person's words), DR-60 (no key animates: every key path runs in `Instant.run`), DR-68 (1–9, ⏎, O, ⌘Z
/// and Esc keep their meaning; S is the review's Skip).
struct InboxReviewView: View {
    @Environment(InboxViewModel.self) private var viewModel
    @Environment(Store.self) private var store

    let onEnd: () -> Void
    let onOpenInInbox: (InboxItem) -> Void

    enum Field: Hashable { case card, answer }
    @FocusState private var focus: Field?
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: eyebrow) {
                TextButton(title: Copy.Inbox.Review.end, keyHint: "Esc", help: Copy.Inbox.Review.endHelp) { end() }
            }
            ScrollView {
                VStack(spacing: CicadaTheme.spacingMD) {
                    if let item = viewModel.reviewItem {
                        ReviewCardView(item: item, answers: ReviewCard.answers(item) ?? [],
                                       takesText: ReviewCard.takesText(item), names: store.entityNames,
                                       text: $text, field: $focus,
                                       onAnswer: { answer(item.id, $0) }, onSubmitText: { submitText(item) },
                                       onOpenInInbox: { onOpenInInbox(item) })
                            .id(item.id)
                    } else {
                        finished
                    }
                    footer
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .padding(.bottom, CicadaTheme.scaled(72))
            }
        }
        .focusable()
        .focusEffectDisabled()
        .focused($focus, equals: .card)
        .onKeyPress(phases: .down) { press in
            guard let item = viewModel.reviewItem else { return .ignored }
            let answers = ReviewCard.answers(item) ?? []
            // ⌘Z is the Undo button's own shortcut (below), so the Edit menu never takes it first.
            guard !press.modifiers.contains(.command),
                  let key = ReviewKeys.action(press.characters, answers: answers.count, takesText: ReviewCard.takesText(item),
                                              fieldFocused: focus == .answer) else { return .ignored }
            switch key {
            case .answer(let i): answer(item.id, answers[i].resolution)
            case .skip: skip(item.id)
            case .type: focus = .answer
            }
            return .handled
        }
        // DR-28 — the field's Esc first (it leaves the field), then the review's.
        .onKeyPress(.escape) {
            if focus == .answer {
                focus = .card
                return .handled
            }
            end()
            return .handled
        }
        .onChange(of: viewModel.review?.currentId) { old, _ in
            if let old { viewModel.noteDraft(old, "") }
            text = ""
            settleFocus()
        }
        // Say it once (review of #363) — a half-typed answer keeps the review up when Inbox is clicked again.
        .onChange(of: text) { _, now in
            if let id = viewModel.review?.currentId { viewModel.noteDraft(id, now) }
        }
        .onDisappear { if let id = viewModel.review?.currentId { viewModel.noteDraft(id, "") } }
        .onAppear { settleFocus() }
    }

    private var eyebrow: String {
        guard let review = viewModel.review else { return Copy.Inbox.title }
        // Say it once — the line under the card counts answered, skipped and left; the eyebrow names the review.
        return Eyebrow.text(Copy.Inbox.title, review.kind.title)
    }

    // MARK: The line under the card — progress, Skip, Undo

    @ViewBuilder
    private var footer: some View {
        if let review = viewModel.review {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let id = review.currentId {
                    TextButton(title: Copy.Inbox.Review.skip, keyHint: "S", help: Copy.Inbox.Review.skipHelp) { skip(id) }
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
                Text(Copy.Inbox.Review.progress(answered: review.answered, skipped: review.skipped, left: review.left))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let last = viewModel.reviewLastStep {
                    Text(last)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    // ⌘Z belongs to the field while it has focus (R-DI4).
                    NeutralButton(title: Copy.Inbox.Review.undo, size: .compact,
                                  shortcut: ReviewKeys.undoShortcut(fieldFocused: focus == .answer)
                                      ? KeyboardShortcut("z", modifiers: .command) : nil,
                                  help: Copy.Inbox.Review.undoHelp) { undo() }
                }
            }
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
            .frame(minHeight: CicadaTheme.scaled(TextButton.height))
        }
    }

    @ViewBuilder
    private var finished: some View {
        if let review = viewModel.review {
            VStack(spacing: CicadaTheme.spacingMD) {
                EmptyStateView(title: Copy.Inbox.Review.finished,
                               message: Copy.Inbox.Review.finishedDetail(answered: review.answered,
                                                                          skipped: review.skipped))
                NeutralButton(title: Copy.Inbox.Review.backToInbox, keyHint: "Esc") { end() }
            }
            .padding(.top, CicadaTheme.scaled(48))
        }
    }

    // MARK: Actions (keys and pointer alike — a swap is instant, DR-29 / DR-60)

    /// Every answer and skip names the card it was drawn for (review B1): one for a card no longer on screen is a no-op.
    private func answer(_ itemId: String, _ resolution: QuestionResolution) {
        Instant.run { viewModel.reviewAnswer(itemId: itemId, resolution) }
    }

    private func submitText(_ item: InboxItem) {
        guard let resolution = ReviewCard.typed(item, text: text) else { return }
        answer(item.id, resolution)
    }

    private func skip(_ itemId: String) {
        Instant.run { viewModel.reviewSkip(itemId: itemId) }
    }

    private func undo() {
        Instant.run { viewModel.reviewUndo() }
    }

    private func end() {
        Instant.run { onEnd() }
    }

    /// The keys come back to the card one turn later: a `FocusState` write in the update that swaps the card in is
    /// dropped on macOS (R-DL4's lesson).
    private func settleFocus() {
        DispatchQueue.main.async { focus = .card }
    }
}

/// One card: the kind's glyph and the page, the question, the context to decide on (DR-38: nothing repeated), the
/// answers in their places, and a field when the answer is words.
struct ReviewCardView: View {
    let item: InboxItem
    let answers: [ReviewAnswer]
    let takesText: Bool
    var names: EntityNames = .empty
    @Binding var text: String
    let field: FocusState<InboxReviewView.Field?>.Binding
    let onAnswer: (QuestionResolution) -> Void
    let onSubmitText: () -> Void
    let onOpenInInbox: () -> Void

    private var isEmpty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Text(ReviewContext.question(item))
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            context
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.optionGap)) {
                ForEach(answers) { answer in
                    OptionRow(option: InboxOption(key: String(answer.number), label: answer.label,
                                                  description: answer.detail, claimId: nil, observedAt: nil,
                                                  lastReferenced: nil, ageDays: nil, recommended: answer.recommended),
                              label: names.display(answer.label), number: answer.number, highlighted: false,
                              onHover: {}) { onAnswer(answer.resolution) }
                }
                if takesText { textRow }
            }
            .padding(.top, CicadaTheme.scaled(20))
        }
        .padding(CicadaTheme.scaled(28))
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth), alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
    }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            KindGlyph(kind: item.kind)
            // Say it once — the question under it already names the page ("Still tracking Beta Project?").
            if !InboxRowWords.repeats(name: item.displayName, in: ReviewContext.question(item)) {
                Text(item.displayName)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            TextButton(title: Copy.Inbox.Review.openInInbox, help: Copy.Inbox.Review.openInInboxHelp,
                       action: onOpenInInbox)
                .padding(.trailing, -CicadaTheme.scaled(10))
        }
        .frame(minHeight: CicadaTheme.scaled(28))
        .padding(.bottom, CicadaTheme.spacingSM)
    }

    // MARK: What to decide on, by kind

    @ViewBuilder
    private var context: some View {
        let lines = ReviewContext.lines(item)
        if !lines.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.top, CicadaTheme.scaled(12))
        }
        if let summary = ReviewContext.summary(item) {
            Text(summary)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, CicadaTheme.scaled(12))
        }
        if let example = item.fold?.example {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Inbox.Review.forExample)
                Text(example)
                    .font(CicadaTheme.quoteFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .quoteBlock()
            }
            .padding(.top, CicadaTheme.scaled(16))
        }
        if ReviewContext.showsQuote(item), let segments = QuoteSegments.of(item) {
            CitedPassage(segments: segments)
                .quoteBlock()
                .padding(.top, CicadaTheme.scaled(16))
            Text(InboxSourceLine.full(item))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
                .help(InboxSourceLine.help(item) ?? "")
                .padding(.top, CicadaTheme.spacingXS)
        }
    }

    private var textRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            InboxTextField(prompt: item.asks == NameAnswer.asks ? Copy.Inbox.namePrompt : Copy.Inbox.answerPrompt,
                           text: $text, isFocused: field.wrappedValue == .answer)
                .focused(field, equals: .answer)
                .onSubmit(onSubmitText)
            NeutralButton(title: Copy.Inbox.submit, keyHint: field.wrappedValue == .answer ? "⏎" : "O",
                          isDisabled: isEmpty, disabledHelp: Copy.Inbox.answerNeedsText, action: onSubmitText)
        }
    }
}

/// The words a card shows to decide on, pure so a test can read them (no view needed).
enum ReviewContext {
    /// A fold asks its question in the two names; every other card asks the server's question.
    static func question(_ item: InboxItem) -> String {
        if item.kind == .normalization, let fold = item.fold {
            return Copy.Inbox.Review.foldQuestion(fold.raw, fold.canonical)
        }
        return item.questionText
    }

    /// Decay: when it was last said and in how many conversations. Fold: what it covers.
    static func lines(_ item: InboxItem, now: Date = .now, locale: Locale = .autoupdatingCurrent,
                      timeZone: TimeZone = .autoupdatingCurrent) -> [String] {
        switch item.kind {
        case .decay:
            let said = item.subject?.lastSaid ?? item.options.first { $0.key == ReviewCard.keepKey }?.lastReferenced
            let day = ReviewCard.day(said, locale: locale, timeZone: timeZone)
            let days = InboxAge.days(since: said, now: now)
            // Say it once (owner 2026-10-19) — the day or its age, never both: this week reads "today" / "3 days
            // ago", anything older its date ("Oct 19, 2026 · today" was one fact twice).
            let recent = days.map { $0 < 7 } ?? false
            let age = recent ? days.map { InboxAge.phrase(days: $0) } : nil
            var out = [Copy.Inbox.Review.lastSaid(day: recent ? nil : day, age: day == nil || recent ? age : nil)]
            if let subject = item.subject { out.append(Copy.Inbox.Review.conversations(subject.conversations)) }
            return out
        case .normalization:
            guard let fold = item.fold, fold.claims > 0 else { return [] }
            return [Copy.Inbox.Review.foldCovers(claims: fold.claims, pages: max(fold.pages, 1))]
        default:
            return []
        }
    }

    /// What the page is, for a decay or fold card: its lead sentence, as the server clipped it.
    static func summary(_ item: InboxItem) -> String? {
        guard let summary = item.subject?.summary, !summary.isEmpty else { return nil }
        return summary
    }

    /// A conflict or a question shows the words that raised it; a decay or fold card has its own context.
    static func showsQuote(_ item: InboxItem) -> Bool {
        item.kind == .conflict || item.kind == .clarification
    }
}

/// The entry points, above the questions at full width (STATE 0): "Review one kind at a time", then one text button
/// per kind with something to review — "Fading pages · 49" (DR-40 text buttons, DR-20 the one section label, DR-21
/// counts through `UsageFormat`). Nothing when there is nothing to review.
struct InboxReviewEntriesRow: View {
    let entries: [ReviewEntries.Entry]
    let start: (ReviewKind) -> Void

    var body: some View {
        if !entries.isEmpty {
            // DR-31 — the label goes before a button would truncate; the buttons never do.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    SectionLabel(Copy.Inbox.Review.entriesLabel)
                        .padding(.leading, CicadaTheme.scaled(10))
                        .padding(.trailing, CicadaTheme.spacingXS)
                    buttons
                    Spacer(minLength: 0)
                }
                HStack(spacing: CicadaTheme.spacingXS) {
                    buttons
                    Spacer(minLength: 0)
                }
            }
            .padding(.bottom, CicadaTheme.spacingSM)
        }
    }

    private var buttons: some View {
        ForEach(entries) { entry in
            TextButton(title: Copy.Inbox.Review.entry(entry.kind, entry.count),
                       help: Copy.Inbox.Review.entryHelp(entry.kind)) { start(entry.kind) }
                .fixedSize()
        }
    }
}
