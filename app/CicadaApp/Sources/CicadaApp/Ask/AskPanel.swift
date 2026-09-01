import SwiftUI

/// ⌘K panel (G52, spec §5.9): a question field over `POST /ask`, rendering a
/// grounded markdown answer with wikilink-style citation chips, an explicit
/// "I don't know" gap list, and a confidence meter. Presented as a `.sheet`
/// from `ContentView`.
struct AskPanel: View {
    @Environment(Store.self) private var store
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(\.dismiss) private var dismiss

    /// Called when a citation chip (or a history row with a cached answer)
    /// is tapped — `ContentView` switches to the Graph tab before this view
    /// dismisses itself.
    var onSelectEntity: (String) -> Void

    @State private var vm: AskViewModel?
    @FocusState private var questionFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    if let vm {
                        if let error = vm.error {
                            errorBanner(error)
                        }
                        if let answer = vm.answer {
                            answerView(answer)
                                .opacity(vm.isAsking ? 0.5 : 1.0)
                                .animation(.easeInOut(duration: 0.15), value: vm.isAsking)
                        } else if vm.isAsking {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                ProgressView().controlSize(.small)
                                Text("Asking your memory…")
                                    .font(CicadaTheme.bodyFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                            }
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
        .frame(width: 560, height: 460)
        .background(CicadaTheme.surface)
        .task {
            if vm == nil {
                let newVM = AskViewModel(store: store)
                vm = newVM
                await newVM.loadHistory()
            }
            questionFocused = true
        }
    }

    // MARK: - Header / input

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "sparkle.magnifyingglass")
                .font(.system(size: 14))
                .foregroundStyle(CicadaTheme.accent)

            TextField("Ask your memory…", text: Binding(
                get: { vm?.question ?? "" },
                set: { vm?.question = $0 }
            ))
            .textFieldStyle(.plain)
            .font(.system(size: 15))
            .foregroundStyle(CicadaTheme.textPrimary)
            .focused($questionFocused)
            .onSubmit { submit() }

            if vm?.isAsking == true {
                ProgressView().controlSize(.small)
            }

            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 14))
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
                    Text("SOURCES")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .tracking(1.2)

                    AskChipFlowLayout(spacing: CicadaTheme.spacingSM) {
                        ForEach(answer.citationRows, id: \.id) { row in
                            citationChip(row.citation)
                        }
                    }
                }
            }

            if !answer.gaps.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text("I don't know:")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)

                    ForEach(answer.gapRows, id: \.id) { row in
                        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                            Text("•").foregroundStyle(CicadaTheme.textTertiary)
                            Text(row.text)
                                .font(.system(size: 12))
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
                LogoImage(entityId: citation.entityId, name: citation.entityName, size: 20)
                Text("[[\(citation.entityName)]]")
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(CicadaTheme.accent)
            }
            .padding(.leading, 4)
            .padding(.trailing, CicadaTheme.spacingSM)
            .padding(.vertical, 4)
            .background(Capsule().fill(CicadaTheme.accent.opacity(0.12)))
        }
        .buttonStyle(.cicadaPlain)
        .help(citation.snippet)
        .accessibilityLabel("Open \(citation.entityName)")
    }

    private func confidenceMeter(_ confidence: Double) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text("CONFIDENCE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

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
                .font(.system(size: 11, design: .monospaced))
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
                .font(.system(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    private func recentQuestions(_ vm: AskViewModel) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("RECENT")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            ForEach(vm.history) { entry in
                Button {
                    vm.select(entry)
                } label: {
                    HStack {
                        Text(entry.question)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        Spacer()
                        Image(systemName: "arrow.up.left")
                            .font(.system(size: 10))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                }
                .buttonStyle(.cicadaPlain)
            }
        }
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.entityColor(for: .deadline))
            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .padding(CicadaTheme.spacingSM)
        .background(CicadaTheme.entityColor(for: .deadline).opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
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
