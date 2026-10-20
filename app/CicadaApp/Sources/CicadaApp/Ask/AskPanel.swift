import SwiftUI

/// ⌘K panel (G52, spec §5.9): a question field over `POST /ask`, rendering a
/// grounded markdown answer with wikilink-style citation chips, an explicit
/// "I don't know" gap list, and a confidence meter. Since G136 the ⌘K find
/// palette hosts it as its Ask mode (`hostedViewModel`); standalone it still
/// draws its own header and sheet size.
struct AskPanel: View {
    @Environment(Store.self) private var store
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(\.dismiss) private var dismiss

    /// Called when a citation chip (or a history row with a cached answer)
    /// is tapped — the host switches to the Graph tab and closes itself.
    var onSelectEntity: (String) -> Void
    /// G136 (round-3 design §3.5, A11) — the ⌘K palette hosts this body in Ask
    /// mode. When set, the palette owns the question field and the view model,
    /// so this view draws the answer only: no header, no sheet size. `nil`
    /// keeps the standalone panel exactly as it was. Nothing below
    /// `// MARK: - Answer` changes — Track P edits that body in parallel.
    var hostedViewModel: AskViewModel? = nil

    @State private var ownViewModel: AskViewModel?
    private var vm: AskViewModel? { hostedViewModel ?? ownViewModel }
    @FocusState private var questionFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if hostedViewModel == nil {
                header
                Divider().background(CicadaTheme.border)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    if let vm {
                        if let error = vm.error {
                            errorBanner(error)
                        }
                        // DR-43 (round 3, 2026-10-20): asking is said in words — over the still skeleton the first
                        // time, above the dimmed answer when it asks again — never a spinner (the field drew one too).
                        if let answer = vm.answer {
                            if vm.isAsking {
                                Text(Copy.AskWords.asking)
                                    .font(CicadaTheme.metaFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                            answerView(answer)
                                .opacity(vm.isAsking ? 0.5 : 1.0)
                                .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: vm.isAsking)
                        } else if vm.isAsking {
                            ListSkeleton(message: Copy.AskWords.asking, rows: 3)
                                .padding(.top, CicadaTheme.spacingSM)
                        } else if !vm.history.isEmpty {
                            recentQuestions(vm)
                        } else {
                            emptyState
                        }
                    }
                }
                .padding(CicadaTheme.spacingLG)
            }
        }
        .frame(width: hostedViewModel == nil ? 560 : nil, height: hostedViewModel == nil ? 460 : nil)
        .background(CicadaTheme.surface)
        // The grounded answer (`MarkdownBody` at line ~109) can contain
        // `[[wikilinks]]` in its own prose, not just the citation chips
        // below — without this they rendered as accent-colored links that
        // did nothing on tap (bug 2). Same destination as a citation chip.
        .wikilinkNavigation(onSelect: onSelectEntity)
        .task {
            // Hosted: the palette made the view model, loaded its history and
            // owns the field's focus.
            guard hostedViewModel == nil else { return }
            if ownViewModel == nil {
                let newVM = AskViewModel(store: store)
                ownViewModel = newVM
                await newVM.loadHistory()
            }
            questionFocused = true
        }
    }

    // MARK: - Header / input

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "sparkle.magnifyingglass")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.accent)

            TextField("Ask your memory…", text: Binding(
                get: { vm?.question ?? "" },
                set: { vm?.question = $0 }
            ))
            .textFieldStyle(.plain)
            .font(CicadaTheme.font(size: 15))
            .foregroundStyle(CicadaTheme.textPrimary)
            .focused($questionFocused)
            .onSubmit { submit() }

            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .buttonStyle(.cicadaPlain)
        }
        .padding(CicadaTheme.spacingLG)
    }

    private func submit() {
        guard let vm else { return }
        Task { await vm.ask() }
    }

    // MARK: - Answer

    @ViewBuilder
    private func answerView(_ answer: AskResponse) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            MarkdownBody(text: answer.answer)

            confidenceMeter(answer.confidence)

            if !answer.citations.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    SectionLabel("Sources")

                    AskChipFlowLayout(spacing: CicadaTheme.spacingSM) {
                        ForEach(answer.citationRows, id: \.id) { row in
                            citationChip(row.citation)
                        }
                    }

                    // G118 slice 2 (§4.7, P5) — the words behind each source:
                    // hover a chip for the sentence, click for the conversation
                    // (the Reader opens beside the window; this sheet steps
                    // aside, `ContentView`).
                    ForEach(answer.citationRows.filter { !$0.citation.evidenceChips.isEmpty }, id: \.id) { row in
                        AskEvidenceRow(citation: row.citation)
                    }
                }
            }

            // 2026-10-19 — beside the page sources, the conversations the answer used that no page cites (Ask's
            // search leg): each opens in the Reader (DR-31), named by its title and day (DR-54).
            if !answer.conversationRows.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    SectionLabel(Copy.AskWords.fromConversations)
                        .help(Copy.AskWords.fromConversationsHelp)
                        .padding(.bottom, CicadaTheme.spacingXS)
                    ForEach(answer.conversationRows) { conversation in
                        AskConversationRowView(conversation: conversation)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel(Copy.AskWords.fromConversationsHelp)
            }

            if !answer.gaps.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text("I don't know:")
                        .font(CicadaTheme.font(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)

                    ForEach(answer.gapRows, id: \.id) { row in
                        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                            Text("•").foregroundStyle(CicadaTheme.textTertiary)
                            Text(row.text)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                        }
                    }
                }
            }
        }
    }

    private func citationChip(_ citation: AskCitation) -> some View {
        Button {
            onSelectEntity(citation.entityId)
        } label: {
            HStack(spacing: 6) {
                EntityPicture(id: citation.entityId, name: citation.entityName,
                              type: graphVM.nodes.first { $0.id == citation.entityId }?.type ?? .concept, size: 20)
                Text("[[\(citation.entityName)]]")
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.accent)
            }
            .padding(.leading, CicadaTheme.spacingXS)
            .padding(.trailing, CicadaTheme.spacingSM)
            .padding(.vertical, CicadaTheme.spacingXS)
            .background(Capsule().fill(CicadaTheme.accent.opacity(0.12)))
        }
        .buttonStyle(.cicadaPlain)
        .help(citation.snippet)
        .accessibilityLabel("Open \(citation.entityName)")
    }

    private func confidenceMeter(_ confidence: Double) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            SectionLabel("Confidence")

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(CicadaTheme.border).frame(height: 4)
                    Capsule()
                        .fill(CicadaTheme.accent)
                        .frame(width: geo.size.width * max(0, min(1, confidence)), height: 4)
                }
            }
            .frame(height: 4)

            Text("\(Int(confidence * 100))%")
                .font(CicadaTheme.captionFont.monospacedDigit())
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    // MARK: - Empty / history / error

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("Ask a question grounded in your memory graph.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            Text("Answers cite the entities they draw on, and say what they don't know.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    private func recentQuestions(_ vm: AskViewModel) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel("Recent")

            ForEach(vm.history) { entry in
                AskRecentRow(question: entry.question) { vm.select(entry) }
            }
        }
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.entityColor(for: .deadline))
            Text(message)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .padding(CicadaTheme.spacingSM)
        .background(CicadaTheme.entityColor(for: .deadline).opacity(0.1),
                    in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))   // DR-12: continuous
    }
}

// MARK: - AskChipFlowLayout
//
// Minimal wrapping HStack for citation chips — a plain `HStack` clips at the
// panel width and a fixed-width `LazyVGrid` doesn't fit a variable number of
// variable-width chips. `Layout` (macOS 13+) is the smallest primitive that
// wraps correctly.
struct AskChipFlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: maxWidth.isFinite ? maxWidth : x, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = bounds.minX
        var y: CGFloat = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: .unspecified)
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

/// One cited page's evidence under an answer: its name, then its chips.
private struct AskEvidenceRow: View {
    let citation: AskCitation
    @State private var expanded = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            Text(citation.entityName)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .frame(maxWidth: CicadaTheme.scaled(140), alignment: .leading)
            AskChipFlowLayout(spacing: 6) {
                EvidenceChipRun(chips: citation.evidenceChips, subjectId: citation.entityId, expanded: $expanded)
            }
        }
    }
}

/// A question asked before (round 3, 2026-10-20): a row like every other (DR-48) — no fill at rest, the shared hover
/// fill under the pointer. It rested on the hover fill in a bare `RoundedRectangle` until then, so every row read as
/// hovered.
private struct AskRecentRow: View {
    let question: String
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack {
                Text(question)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer()
                Image(systemName: "arrow.up.left")
                    .font(CicadaTheme.icon(.badge))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(.vertical, CicadaTheme.spacingSM)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering)
    }
}

/// One conversation an answer used that no page cites (2026-10-19). DR-48: one kind glyph, hover is a fill, never a
/// lift; DR-34: the one-line row height from tokens; DR-54: title and day on the row, the episode id only in `.help`.
/// A click opens the conversation in the Reader (DR-31) — the palette steps aside for it, as for an evidence chip.
private struct AskConversationRowView: View {
    let conversation: AskConversation
    @Environment(Store.self) private var store: Store?
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @State private var hovering = false

    var body: some View {
        let title = AskConversationRow.title(conversation)
        Button(action: activate) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                Image(systemName: "bubble.left.and.bubble.right")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                Text(title)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(AskConversationRow.day(conversation.day))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .fixedSize()
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering)
        .help(AskConversationRow.help(conversation))
        .accessibilityLabel(Copy.AskWords.openConversationLabel(title))
        .accessibilityHint(Copy.AskWords.openConversationHint)
    }

    private func activate() {
        switch AskConversationRow.primary(conversation, readerAvailable: reader != nil) {
        case .open(let target): reader?.open(target)
        case .copy(let value):
            AppPasteboard.copy(value)
            let message = Copy.SleepDetailsWords.copied(nil)
            store?.flash(message)
            AccessibilityNotification.Announcement(message).post()
        }
    }
}
