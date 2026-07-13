import SwiftUI

/// One unified inbox card. Collapsed: kind-colored leading icon + entity name +
/// one-line title. Expanded: source-context blockquote + an action row that
/// switches on `item.requiredInput`:
///   - `.choice`    → option buttons (decay keep/archive/snooze, conflict options)
///   - `.freetext`  → TextField + Answer (sends `action:"answer", answer:text`)
///   - `.merge`     → merge picker (prefilled hint) + Answer/Dismiss/Skip
///   - `.none`      → simple Dismiss
struct InboxCardView: View {
    let item: InboxItem
    /// (action, answer?, mergeTarget?, mergeSurvivor?) — forwarded to
    /// `InboxViewModel.resolve`. `mergeSurvivor` (issue #1) is the id the user
    /// chose to keep as the canonical entity; nil for non-merge actions.
    /// Returns whether the resolve succeeded — `fire()` uses this to reset
    /// `resolving` on failure instead of leaving the card dimmed forever.
    let onResolve: (String, String?, String?, String?) async -> Bool

    @State private var isExpanded = false
    @State private var isHovered = false
    @State private var answerText = ""
    @State private var mergeText = ""
    /// Which side of a merge survives. `.existing` keeps the existing target
    /// (legacy default); `.mention` keeps the clarified mention's cleaner name.
    @State private var mergeSurvivor: MergeSurvivor = .existing
    @State private var resolving = false

    private enum MergeSurvivor { case existing, mention }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if isExpanded {
                Divider().background(CicadaTheme.border)
                expandedBody
            }
        }
        .glassCard()
        .overlay(alignment: .leading) {
            // Kind-colored accent rail down the leading edge.
            RoundedRectangle(cornerRadius: 2)
                .fill(item.kind.color)
                .frame(width: 3)
                .padding(.vertical, CicadaTheme.spacingMD)
                .padding(.leading, 2)
        }
        .scaleEffect(isHovered ? 1.008 : 1.0)
        .opacity(resolving ? 0.5 : 1.0)
        .animation(.spring(duration: 0.2), value: isHovered)
        .animation(.spring(duration: 0.25), value: resolving)
        .onHover { isHovered = $0 }
    }

    // MARK: - Header (collapsed, always visible)

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: item.kind.icon)
                .font(.system(size: 16))
                .foregroundStyle(item.kind.color)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 3) {
                Text(item.displayName)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)

                Text(item.title)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(isExpanded ? nil : 1)
            }

            Spacer()

            Text(item.kind.label)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(item.kind.color)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(item.kind.color.opacity(0.12))
                .clipShape(Capsule())

            Image(systemName: "chevron.right")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textTertiary)
                .rotationEffect(.degrees(isExpanded ? 90 : 0))
                .animation(.spring(duration: 0.2), value: isExpanded)
        }
        .padding(CicadaTheme.spacingLG)
        .padding(.leading, CicadaTheme.spacingXS)
        .contentShape(Rectangle())
        .onTapGesture {
            withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                isExpanded.toggle()
            }
        }
    }

    // MARK: - Expanded body

    private var expandedBody: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if !item.body.isEmpty {
                sourceContext(item.body)
            }

            if let suggestion = item.suggestedClassification, !suggestion.isEmpty {
                suggestionRow(suggestion)
            }

            actionRow
        }
        .padding(CicadaTheme.spacingLG)
        .padding(.leading, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Reveal from BELOW the header: the VStack already stacks the body under
        // the title (spacing 0), so a bottom-edge insertion slides the content
        // down out from under the header instead of sweeping over it from the top.
        .transition(.asymmetric(
            insertion: .opacity.combined(with: .move(edge: .bottom)),
            removal: .opacity
        ))
    }

    /// Source-context blockquote — a left rail + italic text, mirroring how a
    /// quoted excerpt reads.
    private func sourceContext(_ text: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(CicadaTheme.borderLight)
                .frame(width: 3)

            Text(text)
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
                .italic()
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func suggestionRow(_ suggestion: String) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "sparkles")
                .font(.system(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(suggestion)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            if let conf = item.suggestedConfidence {
                Text("(\(Int(conf * 100))% confidence)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    // MARK: - Action row (switches on requiredInput)

    @ViewBuilder
    private var actionRow: some View {
        switch item.requiredInput {
        case .choice:
            choiceActions
        case .freetext:
            freetextActions
        case .merge:
            mergeActions
        case .none:
            HStack {
                Spacer()
                InboxActionButton(title: "Dismiss", icon: "xmark", color: 0x6B7280) {
                    fire("dismiss")
                }
            }
        }
    }

    /// Decay → keep/archive/snooze. Conflict → one button per option (sends
    /// `action:"resolve", answer:<option>`).
    @ViewBuilder
    private var choiceActions: some View {
        switch item.kind {
        case .decay:
            HStack(spacing: CicadaTheme.spacingSM) {
                InboxActionButton(title: "Keep Active", icon: "checkmark", color: 0x22C55E) {
                    fire("keep_active")
                }
                InboxActionButton(title: "Archive", icon: "archivebox", color: 0x6B7280) {
                    fire("archive")
                }
                InboxActionButton(title: "Remind Later", icon: "clock", color: 0xF59E0B) {
                    fire("remind_later")
                }
            }
        default:
            // conflict (and any other choice kind): one full-width button per option.
            VStack(spacing: CicadaTheme.spacingSM) {
                ForEach(item.options ?? [], id: \.self) { option in
                    InboxActionButton(
                        title: option, icon: "arrow.right.circle",
                        color: 0x7C8FFF, fullWidth: true
                    ) {
                        fire("resolve", answer: option)
                    }
                }
            }
        }
    }

    /// Clarification → TextField + Answer (the bug-fixed path: sends the typed
    /// answer, never "archive"), plus Dismiss / Skip.
    private var freetextActions: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            answerField(prompt: "Type your answer…")

            HStack(spacing: CicadaTheme.spacingSM) {
                InboxActionButton(title: "Answer", icon: "paperplane", color: 0x22C55E,
                                  disabled: answerText.trimmed.isEmpty) {
                    fire("answer", answer: answerText.trimmed)
                }
                Spacer()
                InboxActionButton(title: "Dismiss", icon: "xmark", color: 0x6B7280) {
                    fire("dismiss")
                }
                InboxActionButton(title: "Skip", icon: "arrow.right", color: 0x999999) {
                    fire("skip")
                }
            }
        }
    }

    /// The two merge candidates: the clarified mention and the existing target.
    /// The existing target is also the merge DATA SOURCE (it owns the real
    /// frontmatter/history), edited via `mergeText`; the survivor picker only
    /// chooses which NAME the merged entity keeps.
    private var mentionName: String { item.displayName }
    private var existingName: String {
        let t = mergeText.trimmed
        return t.isEmpty ? (item.mergeTargetHint ?? "") : t
    }

    /// Merge suggestion → freetext Answer, or Merge two candidates with a
    /// direction picker choosing the canonical survivor, plus Dismiss / Skip.
    private var mergeActions: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            answerField(prompt: "Describe this entity…")

            // Merge-into target (the existing entity = data source), editable.
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "arrow.triangle.merge")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Existing entity…", text: $mergeText)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )

            survivorPicker

            HStack(spacing: CicadaTheme.spacingSM) {
                InboxActionButton(title: "Answer", icon: "paperplane", color: 0x22C55E,
                                  disabled: answerText.trimmed.isEmpty) {
                    fire("answer", answer: answerText.trimmed)
                }
                InboxActionButton(title: "Merge", icon: "arrow.triangle.merge", color: 0x4A9EFF,
                                  disabled: mergeText.trimmed.isEmpty) {
                    // Data source is always the existing target; the survivor id
                    // is whichever name the user chose to keep.
                    let survivor = mergeSurvivor == .mention ? mentionName : existingName
                    fire("merge", mergeTarget: mergeText.trimmed, mergeSurvivor: survivor)
                }
                Spacer()
                InboxActionButton(title: "Dismiss", icon: "xmark", color: 0x6B7280) {
                    fire("dismiss")
                }
                InboxActionButton(title: "Skip", icon: "arrow.right", color: 0x999999) {
                    fire("skip")
                }
            }
        }
        .onAppear {
            if mergeText.isEmpty, let hint = item.mergeTargetHint { mergeText = hint }
        }
    }

    /// Two-option survivor picker: which entity name survives the merge. The
    /// non-survivor is shown as "→ merges into" the chosen canonical name.
    private var survivorPicker: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("KEEP AS CANONICAL")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.0)

            HStack(spacing: CicadaTheme.spacingSM) {
                survivorOption(mentionName, isSelected: mergeSurvivor == .mention) {
                    mergeSurvivor = .mention
                }
                survivorOption(existingName, isSelected: mergeSurvivor == .existing) {
                    mergeSurvivor = .existing
                }
            }

            // Spell out the resulting direction so it's unambiguous.
            let survivor = mergeSurvivor == .mention ? mentionName : existingName
            let absorbed = mergeSurvivor == .mention ? existingName : mentionName
            if !survivor.isEmpty, !absorbed.isEmpty {
                HStack(spacing: 4) {
                    Text(absorbed).foregroundStyle(CicadaTheme.textTertiary)
                    Image(systemName: "arrow.right").font(.system(size: 9))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text(survivor).foregroundStyle(CicadaTheme.textSecondary)
                }
                .font(.system(size: 10))
            }
        }
    }

    private func survivorOption(_ name: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: isSelected ? "largecircle.fill.circle" : "circle")
                    .font(.system(size: 12))
                    .foregroundStyle(isSelected ? CicadaTheme.accent : CicadaTheme.textTertiary)
                Text(name.isEmpty ? "—" : name)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(isSelected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isSelected ? CicadaTheme.accent.opacity(0.12) : CicadaTheme.surface.opacity(0.5))
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(isSelected ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(name.isEmpty)
    }

    private func answerField(prompt: String) -> some View {
        TextField(prompt, text: $answerText)
            .textFieldStyle(.plain)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
            .onSubmit {
                if !answerText.trimmed.isEmpty { fire("answer", answer: answerText.trimmed) }
            }
    }

    /// Fire a resolution. Skip just forwards (the card stays); everything else
    /// plays a brief confirming fade before the list removes it. On success
    /// the item disappears from `InboxViewModel.items`, which removes this
    /// card from the list entirely — `resolving` never needs to be unset. On
    /// failure the card survives (the item stays in the list), so `resolving`
    /// MUST be reset here or the card stays frozen at 50% opacity forever.
    private func fire(
        _ action: String,
        answer: String? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil
    ) {
        if action != "skip" {
            withAnimation(.spring(duration: 0.2)) { resolving = true }
        }
        Task {
            let succeeded = await onResolve(action, answer, mergeTarget, mergeSurvivor)
            if !succeeded {
                withAnimation(.spring(duration: 0.2)) { resolving = false }
            }
        }
    }
}

// MARK: - Action button

struct InboxActionButton: View {
    let title: String
    let icon: String
    let color: UInt32
    var fullWidth: Bool = false
    var disabled: Bool = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: icon)
                    .font(.system(size: 11))
                Text(title)
                    .font(.system(size: 12, weight: .medium))
            }
            .foregroundStyle(Color(hex: color))
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(maxWidth: fullWidth ? .infinity : nil)
            .background(Color(hex: color).opacity(isHovered ? 0.2 : 0.12))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .scaleEffect(isHovered && !disabled ? 1.03 : 1.0)
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.4 : 1.0)
        .onHover { isHovered = $0 }
        .animation(.spring(duration: 0.15), value: isHovered)
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
