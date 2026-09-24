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
    let onAnswer: (QuestionResolution) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.optionGap)) {
            Text(Copy.Inbox.informational(item.predicate))
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
                    Text(option.label)
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
                .help(option.description ?? option.label)
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

    private var isEmpty: Bool { text.trimmed.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                InboxTextField(prompt: Copy.Inbox.answerPrompt, text: $text, isFocused: field.wrappedValue == .answer)
                    .focused(field, equals: .answer)
                    .onSubmit(submit)
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

/// A possible duplicate — the port of the pre-DS-2 merge card (G113 slice 3b), with neutral
/// buttons (DR-40). The existing entity is the merge's DATA source (it owns the real frontmatter
/// and history) and is editable, seeded from `mergeTargetHint`; the survivor picker chooses only
/// which NAME the merged page keeps. No "Recommended" here either (G115 §4): the server never sets
/// one on a merge, and the view never invents what the server withheld.
struct MergeBody: View {
    let item: InboxItem
    let field: FocusState<InboxFocusCard.Field?>.Binding
    let onAnswer: (QuestionResolution) -> Void

    enum Survivor { case existing, mention }

    @State private var answerText = ""
    @State private var mergeText = ""
    @State private var survivor: Survivor = .existing

    private var mentionName: String { item.displayName }
    /// The pre-DS-2 rule: what the person typed, else the server's hint.
    private var existingName: String {
        let t = mergeText.trimmed
        return t.isEmpty ? (item.mergeTargetHint ?? "") : t
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Grid(alignment: .leading, horizontalSpacing: CicadaTheme.spacingMD, verticalSpacing: CicadaTheme.spacingSM) {
                GridRow {
                    SectionLabel(Copy.Inbox.describeEntity)
                    InboxTextField(prompt: Copy.Inbox.describePrompt, text: $answerText,
                                   isFocused: field.wrappedValue == .answer)
                        .focused(field, equals: .answer)
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
                survivorRow(existingName, note: Copy.Inbox.existingPage, on: survivor == .existing) { survivor = .existing }
            }

            if let direction = MergeDirection.line(survivorIsMention: survivor == .mention,
                                                   mention: mentionName, existing: existingName) {
                Text(direction)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            // DR-31 — a row of four buttons can outgrow a 440 column at 1.4×; it folds onto two
            // lines rather than wanting more width than the column gives.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    skipButton.padding(.leading, -CicadaTheme.scaled(10))
                    Spacer(minLength: CicadaTheme.spacingSM)
                    actionButtons
                }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack(spacing: CicadaTheme.spacingSM) { actionButtons }
                    skipButton.padding(.leading, -CicadaTheme.scaled(10))
                }
            }
        }
        .onAppear {
            if mergeText.isEmpty, let hint = item.mergeTargetHint { mergeText = hint }
        }
    }

    /// The extractor's side: "Newly noticed · tool". Composed outside `Text(` (R-DI23).
    private var mentionNote: String {
        [Copy.Inbox.newFromExtraction, item.suggestedClassification].compactMap { $0 }
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var skipButton: some View {
        TextButton(title: Copy.Inbox.skip) { onAnswer(QuestionResolution(action: "skip")) }
    }

    @ViewBuilder
    private var actionButtons: some View {
        NeutralButton(title: Copy.Inbox.answer, isDisabled: answerText.trimmed.isEmpty,
                      disabledHelp: Copy.Inbox.answerNeedsText) {
            onAnswer(QuestionResolution(action: "answer", answer: answerText.trimmed))
        }
        // G113 slice 3b — a remembered verdict: the backend needs the other side of the pair
        // (`merge_target_hint` OR `mergeTarget`), so disable rather than fire a request it must 400.
        NeutralButton(title: Copy.Inbox.keepSeparate,
                      isDisabled: MergeReject.resolution(existingName: existingName) == nil,
                      disabledHelp: Copy.Inbox.mergeNeedsTarget) {
            if let r = MergeReject.resolution(existingName: existingName) { onAnswer(r) }
        }
        NeutralButton(title: Copy.Inbox.merge, isDisabled: mergeText.trimmed.isEmpty,
                      disabledHelp: Copy.Inbox.mergeNeedsTarget) {
            // The data source is always the existing target; the survivor is the chosen name.
            let keep = survivor == .mention ? mentionName : existingName
            onAnswer(QuestionResolution(action: "merge", mergeTarget: mergeText.trimmed, mergeSurvivor: keep))
        }
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
            NeutralButton(title: Copy.Inbox.keepActive) { onAnswer(QuestionResolution(action: "keep_active")) }
            NeutralButton(title: Copy.Inbox.archive) { onAnswer(QuestionResolution(action: "archive")) }
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
