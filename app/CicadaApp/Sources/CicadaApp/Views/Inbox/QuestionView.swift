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

/// The single renderer for every question-carrying inbox kind (conflict,
/// clarification, merge_suggestion) — modelled on Claude Code's
/// `AskUserQuestion`: the question, an option list with descriptions and a
/// muted age capsule, an "Other…" free-text row, and a "remind me later" footer.
///
/// Keyboard: ↑/↓ move, ⏎ picks, `o` opens Other. All of that lives in
/// `QuestionSelection`; this view only paints it.
struct QuestionView: View {
    let item: InboxItem
    let onResolve: (QuestionResolution) -> Void

    @State private var selection: QuestionSelection
    @State private var otherText = ""
    @FocusState private var otherFocused: Bool

    init(item: InboxItem, onResolve: @escaping (QuestionResolution) -> Void) {
        self.item = item
        self.onResolve = onResolve
        _selection = State(initialValue: QuestionSelection(
            optionCount: item.options.count, allowOther: item.allowOther
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
                    optionRow(pair.element, highlighted: selection.index == pair.offset)
                        .onTapGesture { pick(pair.offset) }
                }

                if item.allowOther {
                    otherRow
                }
            }

            if item.allowDefer {
                HStack {
                    Spacer()
                    InboxActionButton(title: "Not sure — remind me later",
                                      icon: "clock", color: CicadaTheme.warning) {
                        onResolve(QuestionResolution(action: "defer"))
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
        .onExitCommand { otherFocused = false }
        .focusable()
        .onKeyPress(.return) { activate(); return .handled }
        .onKeyPress(KeyEquivalent("o")) {
            guard !otherFocused else { return .ignored }
            selection.openOther()
            otherFocused = true
            return .handled
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
                .buttonStyle(.plain)
                .help("Open source")
            }
        }
        .padding(.vertical, 2)
    }

    private func optionRow(_ option: InboxOption, highlighted: Bool) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                Text(option.label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
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
