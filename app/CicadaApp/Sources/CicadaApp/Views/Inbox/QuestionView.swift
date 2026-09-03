import SwiftUI

/// What a `QuestionView` interaction resolves to — one value instead of four
/// positional arguments, so adding a channel (option key, remind window) never
/// churns every call site again.
struct QuestionResolution {
    let action: String
    var answer: String? = nil
    var optionKey: String? = nil
    var remindDays: Int? = nil
    var mergeTarget: String? = nil
    var mergeSurvivor: String? = nil
}

/// The single renderer for every question-carrying inbox kind — decay included
/// since G115 Phase 1 (R5), alongside conflict, clarification and
/// merge_suggestion — modelled on Claude Code's `AskUserQuestion`: the question,
/// an option list with descriptions and a muted age capsule, an "Other…"
/// free-text row, and a "not now" footer.
///
/// Keys (G115 §7): `1–4` pick, ⏎ activates the highlighted row (which starts on
/// `(Recommended)`), `o` Other, `l` = Not now (7-day defer), `Esc` closes Other
/// then collapses the card with no write. All of that lives in
/// `QuestionSelection`; this view only paints it.
struct QuestionView: View {
    let item: InboxItem
    let onResolve: (QuestionResolution) -> Void
    /// `Esc` on a card with nothing open: collapse it. A no-op default so the
    /// existing call site — and any future one that has no card to collapse —
    /// still compiles without passing a closure.
    let onCollapse: () -> Void

    @State private var selection: QuestionSelection
    @State private var otherText = ""
    @FocusState private var otherFocused: Bool

    init(item: InboxItem,
         onResolve: @escaping (QuestionResolution) -> Void,
         onCollapse: @escaping () -> Void = {}) {
        self.item = item
        self.onResolve = onResolve
        self.onCollapse = onCollapse
        _selection = State(initialValue: QuestionSelection(
            optionCount: item.options.count, allowOther: item.allowOther,
            // R6: ⏎ accepts Sleep's own proposal without hunting for it.
            initialIndex: item.recommendedIndex
        ))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(item.questionText)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            if let hint = item.hint, !hint.isEmpty {
                hintRow(hint)
            }

            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(Array(item.options.enumerated()), id: \.element.id) { pair in
                    optionRow(pair.element, index: pair.offset,
                              highlighted: selection.index == pair.offset)
                        .onTapGesture { pick(pair.offset) }
                }

                if item.allowOther {
                    otherRow
                }
            }

            if item.allowDefer {
                HStack {
                    Spacer()
                    // R5/G113 R6: one defer window for every kind — `defer` with
                    // 7 days, the same route `remind_later` now takes on the
                    // server, so a decay card and a conflict card push out by
                    // the same amount and grade the same way in the ledger.
                    InboxActionButton(title: "Not now — ask again in 7 days (l)",
                                      icon: "clock", color: CicadaTheme.warning) {
                        onResolve(QuestionResolution(action: "defer", remindDays: 7))
                    }
                }
            }
        }
        .onMoveCommand { direction in
            switch direction {
            case .down: selection.moveDown()
            case .up: selection.moveUp()
            default: break
            }
        }
        .focusable()
        .onKeyPress(.return) { activate(); return .handled }
        .onKeyPress(KeyEquivalent("o")) {
            guard !otherFocused else { return .ignored }
            selection.openOther()
            otherFocused = true
            return .handled
        }
        // `Esc` is `selection.escape()`'s alone now — the old
        // `.onExitCommand { otherFocused = false }` closed the text field but
        // left `otherExpanded` true, so a second Esc did nothing and the card
        // could not be dismissed from the keyboard at all.
        .onKeyPress(.escape) {
            switch selection.escape() {
            case .closeOther: otherFocused = false; return .handled
            case .collapse: onCollapse(); return .handled
            default: return .ignored
            }
        }
        .onKeyPress(KeyEquivalent("l")) {
            guard !otherFocused, item.allowDefer else { return .ignored }
            onResolve(QuestionResolution(action: "defer", remindDays: 7))
            return .handled
        }
        .onKeyPress(characters: .decimalDigits) { press in
            guard !otherFocused, let n = Int(press.characters) else { return .ignored }
            if case .pick(let i)? = selection.pickNumber(n) { pick(i); return .handled }
            return .ignored
        }
    }

    // MARK: - Rows

    private func hintRow(_ hint: String) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "link")
                .font(.system(size: 10))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(hint)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(2)
            if let url = firstURL(in: hint) {
                Spacer()
                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.accent)
                }
                .buttonStyle(.cicadaPlain)
                .help("Open source")
            }
        }
        .padding(.vertical, 2)
    }

    /// `index` is the 0-based row: the first nine rows wear their number so the
    /// `1–4` keys are discoverable rather than folklore (G115 §7), and the ONE
    /// option Sleep proposed wears `(Recommended)` — the marker is read off
    /// `option.recommended`, computed server-side from the ledger's `_verdict`
    /// (R6). The view never invents a recommendation.
    private func optionRow(_ option: InboxOption, index: Int, highlighted: Bool) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(index < 9 ? "\(index + 1). \(option.label)" : option.label)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    if option.recommended {
                        Text("(Recommended)")
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(CicadaTheme.accent)
                    }
                }
                if let description = option.description, !description.isEmpty {
                    Text(description)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if let capsule = option.ageCapsule {
                Text(capsule)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(Capsule())
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(highlighted ? CicadaTheme.accent.opacity(0.12) : CicadaTheme.surface.opacity(0.5))
        )
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(highlighted ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
        )
        .contentShape(Rectangle())
    }

    private var otherRow: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if selection.otherExpanded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextField("What's actually true?", text: $otherText)
                        .textFieldStyle(.plain)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .focused($otherFocused)
                        .onSubmit(submitOther)
                    InboxActionButton(title: "Submit", icon: "paperplane", color: CicadaTheme.success,
                                      disabled: otherText.trimmed.isEmpty,
                                      action: submitOther)
                }
                .padding(CicadaTheme.spacingMD)
                .background(CicadaTheme.surface)
                .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .overlay(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .stroke(CicadaTheme.accent.opacity(0.5), lineWidth: 1)
                )
            } else {
                HStack {
                    Image(systemName: "pencil")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text("Other…")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Spacer()
                }
                .padding(CicadaTheme.spacingMD)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .fill(selection.isOtherRow ? CicadaTheme.accent.opacity(0.12)
                                                   : CicadaTheme.surface.opacity(0.5))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .stroke(selection.isOtherRow ? CicadaTheme.accent.opacity(0.5)
                                                     : CicadaTheme.border, lineWidth: 1)
                )
                .contentShape(Rectangle())
                .onTapGesture {
                    selection.openOther()
                    otherFocused = true
                }
            }
        }
    }

    // MARK: - Actions

    private func activate() {
        guard let action = selection.activate() else { return }
        switch action {
        case .pick(let i): pick(i)
        case .openOther: otherFocused = true
        default: break   // `activate()` never yields .closeOther/.collapse
        }
    }

    private func pick(_ i: Int) {
        guard item.options.indices.contains(i) else { return }
        onResolve(QuestionResolution(action: "resolve", optionKey: item.options[i].key))
    }

    private func submitOther() {
        let text = otherText.trimmed
        guard !text.isEmpty else { return }
        // Free text answers the question outright; the backend closes every
        // option claim and records a user-stated claim.
        onResolve(QuestionResolution(action: "resolve", answer: text,
                                     optionKey: item.options.contains(where: { $0.key == "neither" })
                                        ? "neither" : nil))
    }

    private func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        return detector.firstMatch(in: text, range: range)?.url
    }
}
