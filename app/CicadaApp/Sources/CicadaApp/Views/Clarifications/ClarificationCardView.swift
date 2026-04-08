import SwiftUI

struct ClarificationCardView: View {
    let clarification: Clarification
    let onResolve: () -> Void
    @State private var isExpanded = false
    @State private var answerText = ""
    @State private var showAnswerField = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Collapsed header
            Button {
                withAnimation(.spring(duration: 0.25)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    Image(systemName: "questionmark.circle.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(Color(hex: 0xF59E0B))
                        .frame(width: 24)

                    VStack(alignment: .leading, spacing: 2) {
                        Text(clarification.entityMention)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)

                        Text(clarification.uncertaintyType)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(1)
                    }

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .rotationEffect(.degrees(isExpanded ? 90 : 0))
                }
                .padding(CicadaTheme.spacingLG)
            }
            .buttonStyle(.plain)

            if isExpanded {
                Divider().background(CicadaTheme.border)

                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    // Source context blockquote
                    HStack(spacing: CicadaTheme.spacingMD) {
                        Rectangle()
                            .fill(CicadaTheme.accent)
                            .frame(width: 3)

                        Text(clarification.sourceContext)
                            .font(.system(size: 12, design: .default))
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .italic()
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.vertical, CicadaTheme.spacingSM)

                    // Suggested classification
                    if let suggestion = clarification.suggestedClassification {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: "sparkles")
                                .font(.system(size: 11))
                                .foregroundStyle(CicadaTheme.textTertiary)

                            Text(suggestion)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)

                            if let conf = clarification.suggestedConfidence {
                                Text("(\(Int(conf * 100))% confidence)")
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                        }
                    }

                    // Answer field (shown after tapping Answer)
                    if showAnswerField {
                        VStack(spacing: CicadaTheme.spacingSM) {
                            TextField("Describe this entity...", text: $answerText)
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

                            HStack {
                                Spacer()
                                ActionButton(title: "Submit", icon: "paperplane", color: 0x22C55E, action: onResolve)
                            }
                        }
                    }

                    // Action buttons
                    HStack(spacing: CicadaTheme.spacingSM) {
                        if !showAnswerField {
                            ActionButton(title: "Answer", icon: "text.bubble", color: 0x22C55E) {
                                withAnimation { showAnswerField = true }
                            }
                        }
                        ActionButton(title: "Dismiss", icon: "xmark", color: 0x6B7280, action: onResolve)
                        ActionButton(title: "Merge", icon: "arrow.triangle.merge", color: 0x4A9EFF, action: onResolve)
                        ActionButton(title: "Skip", icon: "arrow.right", color: 0x999999, action: {
                            withAnimation(.spring(duration: 0.25)) {
                                isExpanded = false
                            }
                        })
                    }
                }
                .padding(CicadaTheme.spacingLG)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .glassCard()
    }
}
