import SwiftUI

// DR-43 / R-DI15 — the focus card's bodies that are not option rows. Each one only builds a
// `QuestionResolution` and hands it to `onAnswer`; the Store holds it for its Undo window (R-DI2),
// so nothing here ever writes. Internal (not private) so `InboxFocusCard.variantBody` can switch
// over them and a test can reach each one through `InboxFocusCardFitTests`' fixtures (R-DI21).

/// G98 — a conflict on a multi-valued predicate: every value is listed, nothing is picked. The
/// values sit on the option surface without a radio (a radio would promise a choice that does not
/// exist), and "Got it" removes the item without touching a claim.
struct InformationalBody: View {
    let item: InboxItem
    /// R-DL5 — a value that is a page's id reads as that page's name (display only).
    var names: EntityNames = .empty
    let onAnswer: (QuestionResolution) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.optionGap)) {
            Text(Copy.Inbox.informational)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.bottom, CicadaTheme.spacingSM)
            ForEach(item.options) { option in
                HStack(spacing: CicadaTheme.spacingMD) {
                    Image(systemName: "checkmark.circle")
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .accessibilityHidden(true)
                    PageLineText(names.display(option.label))
                        .font(CicadaTheme.font(size: 14, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let age = option.ageCapsule { Tag(text: age) }
                }
                .padding(.horizontal, CicadaTheme.scaled(14))
                .frame(height: CicadaTheme.scaled(RowMetrics.oneLine))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .pageHelp(option.description ?? names.display(option.label))
            }
            HStack {
                Spacer(minLength: 0)
                NeutralButton(title: Copy.Inbox.gotIt) { onAnswer(QuestionResolution(action: "dismiss")) }
            }
            .padding(.top, CicadaTheme.spacingSM)
        }
    }
}

/// R-DI15 — a clarification with no options. The field is open but NOT auto-focused, so L and Esc
/// work the moment the card appears, and O focuses it. A G60 question object answers through
/// `resolve`, a legacy clarification through `answer` (`FreeTextSubmit`); only the legacy shape
/// keeps the Dismiss and Skip it shipped with.
struct FreeTextBody: View {
    let item: InboxItem
    let field: FocusState<InboxFocusCard.Field?>.Binding
    let onAnswer: (QuestionResolution) -> Void

    @State private var text = ""
    @Environment(InboxViewModel.self) private var inboxVM: InboxViewModel?

    private var isEmpty: Bool { text.trimmed.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                InboxTextField(prompt: Copy.Inbox.answerPrompt, text: $text, isFocused: field.wrappedValue == .answer)
                    .focused(field, equals: .answer)
                    .onSubmit(submit)
                    .onChange(of: text) { _, now in inboxVM?.noteDraft(item.id, now) }
                    .onDisappear { inboxVM?.noteDraft(item.id, "") }
                NeutralButton(title: Copy.Inbox.submit, keyHint: "⏎", isDisabled: isEmpty,
                              disabledHelp: Copy.Inbox.answerNeedsText, action: submit)
            }
            if item.question == nil {
                HStack(spacing: CicadaTheme.spacingXS) {
                    TextButton(title: Copy.Inbox.dismiss) { onAnswer(QuestionResolution(action: "dismiss")) }
                    TextButton(title: Copy.Inbox.skip) { onAnswer(QuestionResolution(action: "skip")) }
                }
                .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
    }

    private func submit() {
        guard let r = FreeTextSubmit.resolution(for: item, text: text) else { return }
        onAnswer(r)
    }
}

/// A person Cicada knows only by their relation to the owner — "What's the name of your partner?" (DR-43's free-text
/// shape, DR-40's buttons). The field is open but not auto-focused, as R-DI15's free text, so L and Esc work at once
/// and O focuses it. Submit is neutral and disabled until there is a name (DR-41); "I'd rather not say" is a
/// `TextButton` (a decline, like Skip) that sends the item's own option key — one tap, never asked again.
struct NameBody: View {
    let item: InboxItem
    let field: FocusState<InboxFocusCard.Field?>.Binding
    let onAnswer: (QuestionResolution) -> Void

    @State private var text = ""
    @Environment(InboxViewModel.self) private var inboxVM: InboxViewModel?

    private var isEmpty: Bool { text.trimmed.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                InboxTextField(prompt: Copy.Inbox.namePrompt, text: $text, isFocused: field.wrappedValue == .answer)
                    .focused(field, equals: .answer)
                    .onSubmit(submit)
                    .onChange(of: text) { _, now in inboxVM?.noteDraft(item.id, now) }
                    .onDisappear { inboxVM?.noteDraft(item.id, "") }
                NeutralButton(title: Copy.Inbox.submit, keyHint: "⏎", isDisabled: isEmpty,
                              disabledHelp: Copy.Inbox.nameNeedsText, action: submit)
            }
            TextButton(title: NameAnswer.declineLabel(item), help: Copy.Inbox.ratherNotSayHelp) {
                onAnswer(NameAnswer.decline)
            }
            .padding(.leading, -CicadaTheme.scaled(10))
        }
    }

    private func submit() {
        guard let r = NameAnswer.resolution(name: text) else { return }
        onAnswer(r)
    }
}

/// A possible duplicate. Inbox v2 (owner 2026-10-26: "I don't really get … possible duplicates"), cut down on
/// 2026-11-24 ("the ui for the question is extremely confusing", DESIGN_RULES §9, DR-38): the question names both
/// sides and the evidence above marks the name where it was said, so what is left here is who the existing page is —
/// its picture, name, type and what it says it is, one line, no tiles — then the answers: Merge (the one neutral
/// button, DR-40; what it does and how sure Cicada was are its hover), Keep separate and Skip (quieter text buttons).
/// What each answer does is no longer three lines under the question: the buttons say it. The rarer moves —
/// describing it instead, merging with a different page, keeping the other name — wait under "Something else", one
/// fold (DR-39), open from the start when Sleep named no page. What is sent is unchanged: the existing page is the
/// merge's DATA source (it owns the real frontmatter and history), seeded from `mergeTargetHint`; the survivor picker
/// chooses only which NAME the merged page keeps. No "Recommended" (G115 §4): the server never sets one on a merge.
struct MergeBody: View {
    let item: InboxItem
    /// R-DL5 — the survivor row and the "A → B" line show the existing page's name when the hint is its id;
    /// `existingName`, which the buttons send, stays exactly what it was (the wire never changes).
    var names: EntityNames = .empty
    /// The graph's pages, for the two sides' pictures, types and summaries (display only).
    var nodes: [GraphNode] = []
    let field: FocusState<InboxFocusCard.Field?>.Binding
    let onAnswer: (QuestionResolution) -> Void

    enum Survivor { case existing, mention }

    @State private var answerText = ""
    @State private var mergeText = ""
    @State private var survivor: Survivor = .existing
    @State private var moreOpen = false

    /// The side by side follows what Merge will send: the field, seeded with Sleep's page (review of #481).
    private var pair: MergePair { MergePair.of(item, nodes: nodes, target: mergeText) }
    private var mentionName: String { item.displayName }
    /// The pre-DS-2 rule: what the person typed, else the server's hint.
    private var existingName: String {
        let t = mergeText.trimmed
        return t.isEmpty ? (item.mergeTargetHint ?? "") : t
    }

    var body: some View {
        let pair = pair
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(20)) {
            // The question names the two sides and the evidence above marks the name where it was said, so the only thing
            // left to show is who the existing page is (owner 2026-11-24, DR-38): one line, never a pair of tiles.
            if pair.canMerge {
                existingSide(pair)
            } else {
                Text(Copy.Inbox.Duplicate.noTarget)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: CicadaTheme.spacingSM) {
                mergeButton
                // G113 slice 3b — a remembered verdict needs the other side of the pair; with none, the fold below
                // names it first (and "Keep separate" appears once there is one).
                if let reject = MergeReject.resolution(existingName: existingName) {
                    TextButton(title: Copy.Inbox.keepSeparate, help: Copy.Inbox.Duplicate.keepHelp) { onAnswer(reject) }
                }
                TextButton(title: Copy.Inbox.skip) { onAnswer(QuestionResolution(action: "skip")) }
                Spacer(minLength: 0)
            }

            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                DisclosureHeader(title: Copy.Inbox.Duplicate.somethingElse, isOpen: moreOpen,
                                 help: Copy.Inbox.Duplicate.somethingElseHelp) { moreOpen.toggle() }
                if moreOpen {
                    somethingElse.disclosureReveal()
                }
            }
        }
        .onAppear {
            if mergeText.isEmpty, let hint = item.mergeTargetHint { mergeText = hint }
            // Sleep named no page: the field to name one is the way forward, so it starts open (seeded, never animated).
            if !pair.canMerge { moreOpen = true }
        }
    }

    private var mergeButton: some View {
        // What Merge does, in words, and how sure Cicada was — said on hover, not as lines the buttons repeat (DR-38).
        let words = [pair.canMerge ? pair.mergeWords : Copy.Inbox.Duplicate.mergeHelp, InboxGuess.text(item)]
            .compactMap { $0 }.joined(separator: "\n")
        return NeutralButton(title: Copy.Inbox.merge, isDisabled: mergeText.trimmed.isEmpty,
                      help: words, disabledHelp: Copy.Inbox.mergeNeedsTarget) {
            // The data source is always the existing target; the survivor is the chosen name.
            let keep = survivor == .mention ? mentionName : existingName
            onAnswer(QuestionResolution(action: "merge", mergeTarget: mergeText.trimmed, mergeSurvivor: keep))
        }
    }

    /// The existing side — Sleep's page, or the page the person typed (said as theirs when it is): its picture, name and
    /// type, and what the page says it is, in whole words. No ring and no fill: it is the answer's context, not a choice.
    private func existingSide(_ pair: MergePair) -> some View {
        let side = pair.existing
        return HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
            if side.hasPage {
                EntityPicture(id: side.id, name: side.name, type: side.type ?? .unknown, size: 28)
            }
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
                    PageLineText(side.name.isEmpty ? "—" : names.display(side.name))
                        .font(CicadaTheme.font(size: 14, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if pair.existingIsTyped {
                        Text(Copy.Inbox.Duplicate.typedPage)
                            .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    } else if let type = side.type, type != .unknown {
                        Text(type.label)
                            .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                PageLineText(MergePair.wholeWords(side.summary)
                             ?? (side.hasPage ? Copy.Inbox.Duplicate.noSummary
                                 : pair.existingIsTyped ? Copy.Inbox.Duplicate.noSuchPage : Copy.Inbox.Duplicate.noPageYet))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(side.summary == nil ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    /// DR-43 — every merge control stays reachable: the description and Answer, the existing page, the
    /// Keep-as-canonical picker and the "A → B" line.
    private var somethingElse: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Grid(alignment: .leading, horizontalSpacing: CicadaTheme.spacingMD, verticalSpacing: CicadaTheme.spacingSM) {
                GridRow {
                    SectionLabel(Copy.Inbox.describeEntity)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        InboxTextField(prompt: Copy.Inbox.describePrompt, text: $answerText,
                                       isFocused: field.wrappedValue == .answer)
                            .focused(field, equals: .answer)
                        NeutralButton(title: Copy.Inbox.answer, size: .compact, isDisabled: answerText.trimmed.isEmpty,
                                      disabledHelp: Copy.Inbox.answerNeedsText) {
                            onAnswer(QuestionResolution(action: "answer", answer: answerText.trimmed))
                        }
                    }
                }
                GridRow {
                    SectionLabel(Copy.Inbox.existingEntity)
                    InboxTextField(prompt: Copy.Inbox.existingPrompt, text: $mergeText,
                                   isFocused: field.wrappedValue == .merge)
                        .focused(field, equals: .merge)
                }
            }

            VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.optionGap)) {
                SectionLabel(Copy.Inbox.keepAsCanonical)
                survivorRow(mentionName, note: mentionNote, on: survivor == .mention) { survivor = .mention }
                survivorRow(names.display(existingName), note: Copy.Inbox.existingPage, on: survivor == .existing) { survivor = .existing }
            }

            if let direction = MergeDirection.line(survivorIsMention: survivor == .mention,
                                                   mention: mentionName, existing: names.display(existingName)) {
                Text(direction)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
    }

    /// The extractor's side: "Newly noticed · tool". Composed outside `Text(` (R-DI23).
    private var mentionNote: String {
        [Copy.Inbox.newFromExtraction, item.suggestedClassification].compactMap { $0 }
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func survivorRow(_ name: String, note: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingMD) {
                RadioMark(on: on)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(1)) {
                    Text(name.isEmpty ? "—" : name)
                        .font(CicadaTheme.font(size: 14, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if !note.isEmpty {
                        Text(note)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, CicadaTheme.scaled(14))
            .frame(height: CicadaTheme.scaled(RowMetrics.option))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(on ? CicadaTheme.accent : CicadaTheme.ring(.resting), lineWidth: on ? 1.5 : 1))
        }
        .buttonStyle(.cicadaPlain)
        .disabled(name.isEmpty)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// A cached pre-G115 decay payload (no options): DR-43's "one row of neutral buttons".
struct LegacyDecayBody: View {
    let onAnswer: (QuestionResolution) -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            NeutralButton(title: Copy.Inbox.decayYes) { onAnswer(QuestionResolution(action: "keep_active")) }
            NeutralButton(title: Copy.Inbox.decayNo) { onAnswer(QuestionResolution(action: "archive")) }
            NeutralButton(title: Copy.Inbox.notNow, help: Copy.Inbox.notNowHelp) {
                onAnswer(QuestionResolution(action: "defer", remindDays: 7))
            }
        }
    }
}

/// Nothing to pick and nothing to type: the one thing left is to let it go.
struct DismissBody: View {
    let onAnswer: (QuestionResolution) -> Void

    var body: some View {
        NeutralButton(title: Copy.Inbox.dismiss) { onAnswer(QuestionResolution(action: "dismiss")) }
    }
}
