import SwiftUI

/// One unified inbox card. Collapsed (G115 Phase 1): kind-colored leading glyph,
/// the QUESTION on line 1 and its CAUSE on line 2 — the conversation and age
/// that raised it (G97) — plus a real chevron button. Expanded: the cause
/// excerpt with the mention bolded (or the legacy body, collapsed past four
/// lines), the extractor's guess, and an action row:
///   - `informational`      → G98: the values listed, nothing to pick, "Got it"
///   - a question object    → `QuestionView` for EVERY kind, decay included
///   - `.freetext`/`.merge` → the legacy rows (clarification/merge question
///                            objects are Phase 2)
///   - `.none`              → simple Dismiss
struct InboxCardView: View {
    let item: InboxItem
    /// One resolution value (action + answer/optionKey/remindDays/merge fields),
    /// forwarded to `InboxViewModel.resolve`. Returns whether the resolve
    /// succeeded — `fire()` uses this to reset `resolving` on failure.
    let onResolve: (QuestionResolution) async -> Bool

    @State private var isExpanded = false
    @State private var isHovered = false
    @State private var answerText = ""
    @State private var mergeText = ""
    /// Which side of a merge survives. `.existing` keeps the existing target
    /// (legacy default); `.mention` keeps the clarified mention's cleaner name.
    @State private var mergeSurvivor: MergeSurvivor = .existing
    @State private var resolving = false
    /// Owner defect 2 (2026-09-03): a long legacy body shows its first three
    /// lines until this is flipped.
    @State private var showAllLines = false

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
            // G97: the kind glyph is the leading mark now — the entity logo used
            // to sit here, and a name-initial monogram is the wrong metaphor for
            // a question. What the card asks matters more than whose page it is
            // about, and the entity is named inside the question anyway.
            Image(systemName: item.kind.icon)
                .font(.system(size: 16))
                .foregroundStyle(item.kind.color)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 3) {
                // Line 1 is the question for EVERY kind (G115 §1), not just
                // conflict; line 2 is why it exists rather than a second copy
                // of the entity name (`clarification_manager` used to write the
                // name into `title`, so the two lines read identically).
                Text(item.questionText)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(isExpanded ? nil : 1)

                Text(item.causeLine())
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

            // Owner defect 1 (2026-09-03): the chevron was a decoration inside a
            // tappable header and read as a control that did nothing. It is a
            // real button now, toggling the same state as the header tap.
            Button {
                withAnimation(.spring(duration: 0.3, bounce: 0.15)) { isExpanded.toggle() }
            } label: {
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
                    .frame(width: 20, height: 20)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isExpanded ? "Collapse" : "Expand")
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
            // The cause excerpt REPLACES the legacy body pane whenever one
            // resolved: it is the same evidence, bounded (±240 chars) and with
            // the mention marked, where `body` is whatever the generator wrote.
            if item.hasCause, let cause = item.cause {
                excerptPane(cause)
            } else if !item.body.isEmpty {
                collapsedBody(item.body)
            }

            if let model = item.extractorModel ?? (item.extractorConfidence.map { _ in "Cicada" }) {
                provenanceRow(model: model, confidence: item.extractorConfidence)
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

    /// The cause excerpt with the mention bolded (G97). Bounded by construction
    /// (±240 chars server-side), so this pane can never become the owner's
    /// "list of URLs that doesn't end".
    private func excerptPane(_ cause: InboxCause) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            RoundedRectangle(cornerRadius: 1.5).fill(CicadaTheme.borderLight).frame(width: 3)
            Text(ExcerptText.attributed(cause.excerpt, bold: cause.mentionOffsets))
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }

    /// Legacy body (no cause resolved): owner defect 2 — collapse past four
    /// lines to the first three plus a count, with "Show all".
    private func collapsedBody(_ text: String) -> some View {
        let collapsed = CollapsedLines(text)
        let shown = showAllLines ? collapsed.lines : collapsed.head
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            sourceContext(shown.joined(separator: "\n"))
            if collapsed.needsCollapse {
                Button(showAllLines ? "Show fewer" : "Show all \(collapsed.lines.count)") {
                    withAnimation(.spring(duration: 0.2)) { showAllLines.toggle() }
                }
                .buttonStyle(.plain)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.accent)
            }
        }
    }

    /// `Cicada's guess at 0.42` / `gpt-…'s guess at 0.42` — the extractor's
    /// side of the question, stated before the person answers (G115 §7). This
    /// replaced `suggestionRow`, which showed a merge's suggested type; that
    /// now sits under the name it classifies, in `survivorPicker`.
    private func provenanceRow(model: String, confidence: Double?) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "sparkles").font(.system(size: 10)).foregroundStyle(CicadaTheme.textTertiary)
            Text(confidence.map { String(format: "%@'s guess at %.2f", model, $0) } ?? "\(model)'s guess")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    // MARK: - Action row (switches on requiredInput)

    @ViewBuilder
    private var actionRow: some View {
        if item.informational {
            informationalRow
        } else if !item.options.isEmpty || item.question != nil {
            // Every kind — decay included (G115 §1) — answers through the one
            // component. `decayActions` survives only for a cached pre-G115
            // decay payload that carries no options.
            QuestionView(item: item, onResolve: { fire($0) }, onCollapse: {
                withAnimation(.spring(duration: 0.3, bounce: 0.15)) { isExpanded = false }
            })
        } else if item.kind == .decay {
            decayActions
        } else {
            switch item.requiredInput {
            case .freetext: freetextActions
            case .merge: mergeActions
            default:
                HStack {
                    Spacer()
                    InboxActionButton(title: "Dismiss", icon: "xmark", color: CicadaTheme.textSecondary) {
                        fire(QuestionResolution(action: "dismiss"))
                    }
                }
            }
        }
    }

    /// G98 / G115 R4: a conflict on a multi-valued predicate lists its values
    /// and asks for nothing — a tech stack is a set, not a contradiction. The
    /// reconciler already left every value open; there is nothing to supersede.
    private var informationalRow: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("These can all be true — \(item.predicate ?? "this") holds several values. Nothing to pick.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            ForEach(item.options) { option in
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "checkmark.circle").font(.system(size: 10)).foregroundStyle(CicadaTheme.textTertiary)
                    Text(option.label).font(.system(size: 12)).foregroundStyle(CicadaTheme.textPrimary)
                    if let capsule = option.ageCapsule {
                        Text(capsule).font(.system(size: 10, design: .monospaced)).foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            HStack {
                Spacer()
                InboxActionButton(title: "Got it", icon: "checkmark", color: CicadaTheme.success) {
                    fire(QuestionResolution(action: "dismiss"))
                }
            }
        }
    }

    /// Fallback for a cached pre-G115 decay payload with no options; the live
    /// path routes decay through `QuestionView` (R5).
    private var decayActions: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            InboxActionButton(title: "Keep Active", icon: "checkmark", color: CicadaTheme.success) {
                fire(QuestionResolution(action: "keep_active"))
            }
            InboxActionButton(title: "Archive", icon: "archivebox", color: CicadaTheme.textSecondary) {
                fire(QuestionResolution(action: "archive"))
            }
            // Was `remind_later`, whose server branch wrote a `snooze_until` no
            // reader honoured; one defer route for every kind now (G113 R6).
            InboxActionButton(title: "Remind Later", icon: "clock", color: CicadaTheme.warning) {
                fire(QuestionResolution(action: "defer", remindDays: 7))
            }
        }
    }

    /// Clarification → TextField + Answer (the bug-fixed path: sends the typed
    /// answer, never "archive"), plus Dismiss / Skip.
    private var freetextActions: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            answerField(prompt: "Type your answer…")

            HStack(spacing: CicadaTheme.spacingSM) {
                InboxActionButton(title: "Answer", icon: "paperplane", color: CicadaTheme.success,
                                  disabled: answerText.trimmed.isEmpty) {
                    fire(QuestionResolution(action: "answer", answer: answerText.trimmed))
                }
                Spacer()
                InboxActionButton(title: "Dismiss", icon: "xmark", color: CicadaTheme.textSecondary) {
                    fire(QuestionResolution(action: "dismiss"))
                }
                InboxActionButton(title: "Skip", icon: "arrow.right", color: CicadaTheme.textTertiary) {
                    fire(QuestionResolution(action: "skip"))
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
                InboxActionButton(title: "Answer", icon: "paperplane", color: CicadaTheme.success,
                                  disabled: answerText.trimmed.isEmpty) {
                    fire(QuestionResolution(action: "answer", answer: answerText.trimmed))
                }
                InboxActionButton(title: "Merge", icon: "arrow.triangle.merge", color: CicadaTheme.info,
                                  disabled: mergeText.trimmed.isEmpty) {
                    // Data source is always the existing target; the survivor id
                    // is whichever name the user chose to keep.
                    let survivor = mergeSurvivor == .mention ? mentionName : existingName
                    fire(QuestionResolution(action: "merge", mergeTarget: mergeText.trimmed,
                                            mergeSurvivor: survivor))
                }
                Spacer()
                InboxActionButton(title: "Keep separate", icon: "xmark", color: CicadaTheme.textSecondary) {
                    // G113 slice 3b: unlike a plain dismiss, this is a
                    // remembered verdict — the backend records the pair so
                    // it is never re-proposed by Sleep or the dedup sweep.
                    fire(QuestionResolution(action: "reject"))
                }
                InboxActionButton(title: "Skip", icon: "arrow.right", color: CicadaTheme.textTertiary) {
                    fire(QuestionResolution(action: "skip"))
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

            // R10: the two-column preview is the two NAMES with what each one
            // is under it — the extractor's suggested type for the mention, and
            // the plain fact that the other side already exists. No per-side
            // excerpt: that needs each side's own cause and is G103 / Phase 2.
            // No `(Recommended)` on a merge either (G115 §4) — the server never
            // sets one, and the view never invents what the server withheld.
            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                survivorColumn(mentionName,
                               caption: item.suggestedClassification ?? "",
                               isSelected: mergeSurvivor == .mention) {
                    mergeSurvivor = .mention
                }
                survivorColumn(existingName,
                               caption: "existing entity",
                               isSelected: mergeSurvivor == .existing) {
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

    /// One column of the merge preview: the pickable name, with a muted caption
    /// under it saying what that side is. An empty caption renders nothing.
    private func survivorColumn(_ name: String, caption: String, isSelected: Bool,
                                action: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            survivorOption(name, isSelected: isSelected, action: action)
            if !caption.isEmpty, !name.isEmpty {
                Text(caption)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .padding(.horizontal, CicadaTheme.spacingMD)
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
        .buttonStyle(.cicadaPlain)
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
                if !answerText.trimmed.isEmpty {
                    fire(QuestionResolution(action: "answer", answer: answerText.trimmed))
                }
            }
    }

    /// Fire a resolution. Skip just forwards (the card stays); everything else
    /// plays a brief confirming fade before the list removes it. On success
    /// the item disappears from `InboxViewModel.items`, which removes this
    /// card from the list entirely — `resolving` never needs to be unset. On
    /// failure the card survives (the item stays in the list), so `resolving`
    /// MUST be reset here or the card stays frozen at 50% opacity forever.
    private func fire(_ resolution: QuestionResolution) {
        if resolution.action != "skip" {
            withAnimation(.spring(duration: 0.2)) { resolving = true }
        }
        Task {
            let succeeded = await onResolve(resolution)
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
    let color: Color
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
            .foregroundStyle(color)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(maxWidth: fullWidth ? .infinity : nil)
            .background(color.opacity(isHovered ? 0.2 : 0.12))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            // G83 review finding 1: this used to also carry
            // `.scaleEffect(isHovered && !disabled ? 1.03 : 1.0)`. On the
            // common hover-then-click path that 1.03 grow and
            // CicadaPlainButtonStyle's own 0.97 press-shrink (applied outside
            // this label, see the style) multiply to ≈0.999 — the pressed
            // state became nearly invisible on exactly the highest-frequency
            // buttons in the app (Dismiss/Keep Active/Archive/Answer/Merge).
            // Dropped so the shared style is the ONE thing that owns the
            // press transform here; the hover cue stays as the background
            // tint above (`color.opacity(isHovered ? 0.2 : 0.12)`), which
            // doesn't compete with it.
        }
        .buttonStyle(.cicadaPlain)
        .disabled(disabled)
        .opacity(disabled ? 0.4 : 1.0)
        .onHover { isHovered = $0 }
        .animation(.spring(duration: 0.15), value: isHovered)
    }
}
