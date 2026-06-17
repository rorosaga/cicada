import SwiftUI

// MARK: - ClaimChip
//
// The atomic unit of the claim-layer demo (§5 of d2-companion-showcase.md). A
// claim renders as a rounded card: a body line + a single provenance footer
// (observer badge · context pill · ⊥ trust-pill + confidence-ring · authored-by
// pill · source-episode chip · clock → timeline). Superseded claims dim +
// strikethrough so a stale belief is never mistaken for current. Reused
// everywhere a claim is shown: transclusion, the perspective tab, timeline rows.

struct ClaimChip: View {
    let claim: Claim
    /// Optional clock-icon callback — opens the §4 belief timeline for this
    /// claim's `(subject, predicate, context)` key. Hidden when nil.
    var onOpenTimeline: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(claimAttributed)
                .font(CicadaTheme.bodyFont)
                .strikethrough(!claim.isValid)
                .foregroundStyle(claim.isValid ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)

            // Provenance footer — wraps so a long roster of pills never clips.
            ClaimFooterFlow(spacing: 6) {
                ObserverBadge(claim.observer)
                ContextPill(claim.context)
                TrustPill(claim.sourceTrust)
                ConfidenceRing(claim.confidence)
                AuthorPill(claim.authoredBy)
                if let ep = claim.sourceEpisodes.first { EpisodePill(ep) }
                if let onOpenTimeline {
                    Button(action: onOpenTimeline) {
                        Image(systemName: "clock")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .help("Belief timeline")
                }
            }

            if !claim.isValid, let to = claim.validTo {
                Text("superseded \(to)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
        .opacity(claim.isValid ? 1 : 0.6)
    }

    /// The claim text with `[[wikilinks]]` highlighted in the accent color,
    /// mirroring the entity-card body rendering.
    private var claimAttributed: AttributedString {
        renderWikilinks(claim.text)
    }
}

// MARK: - Provenance pills

/// Who holds the belief — symbol + label, colored by observer.
struct ObserverBadge: View {
    let observer: Observer
    init(_ observer: Observer) { self.observer = observer }

    var body: some View {
        Label(observer.label, systemImage: observer.sfSymbol)
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .clipShape(Capsule())
    }

    private var color: Color {
        switch observer {
        case .agent: return CicadaTheme.accent
        case .rodrigo: return Color(hex: 0x4A9EFF)
        case .external: return CicadaTheme.mediaPink
        }
    }
}

/// The context this belief lives in — a colored swatch + name.
struct ContextPill: View {
    let context: String
    init(_ context: String) { self.context = context }

    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(CicadaTheme.contextColor(context))
                .frame(width: 7, height: 7)
            Text(context)
                .font(.system(size: 10, weight: .regular))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(CicadaTheme.surfaceHover)
        .clipShape(Capsule())
    }
}

/// The source-trust axis — ORTHOGONAL to confidence. user_stated = solid green,
/// agent_reflected = hollow amber, etc.
struct TrustPill: View {
    let trust: SourceTrust
    init(_ trust: SourceTrust) { self.trust = trust }

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: filled ? "checkmark.seal.fill" : "checkmark.seal")
                .font(.system(size: 9, weight: .medium))
            Text(trust.label)
                .font(.system(size: 10, weight: .regular))
        }
        .foregroundStyle(color)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
    }

    private var filled: Bool {
        trust == .userStated || trust == .external
    }

    private var color: Color {
        switch trust {
        case .userStated: return Color(hex: 0x22C55E)   // solid green — human stated
        case .agentExtracted: return Color(hex: 0x4A9EFF)
        case .agentReflected: return Color(hex: 0xF59E0B) // hollow amber — agent guess
        case .external: return CicadaTheme.mediaPink
        case .unknown: return CicadaTheme.textTertiary
        }
    }
}

/// A tiny circular gauge for `confidence` — visually SEPARATE from trust so the
/// two orthogonal axes the architecture insists on read at a glance.
struct ConfidenceRing: View {
    let confidence: Double
    init(_ confidence: Double) { self.confidence = max(0, min(1, confidence)) }

    var body: some View {
        ZStack {
            Circle()
                .stroke(CicadaTheme.border, lineWidth: 2)
            Circle()
                .trim(from: 0, to: confidence)
                .stroke(ringColor, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Text(String(format: "%.0f", confidence * 100))
                .font(.system(size: 7, weight: .semibold, design: .rounded))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(width: 18, height: 18)
        .help(String(format: "confidence %.0f%%", confidence * 100))
    }

    private var ringColor: Color {
        if confidence >= 0.66 { return Color(hex: 0x22C55E) }
        if confidence >= 0.33 { return Color(hex: 0xF59E0B) }
        return Color(hex: 0xEF4444)
    }
}

/// Which model (or `user`) authored the claim — same styling as the
/// Contributors view / EntityDetailCard history author badge.
struct AuthorPill: View {
    let author: String
    init(_ author: String) { self.author = author }

    var body: some View {
        Text(author)
            .font(.system(size: 10, weight: .regular))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.18))
            .clipShape(Capsule())
            .foregroundStyle(color)
    }

    private var color: Color {
        author == "user" ? Color(hex: 0x3B82F6) : Color(hex: 0x8B5CF6)
    }
}

/// The source episode chip. Tapping it is the provenance jump (future: opens
/// the raw episode) — inert for now but visually present.
struct EpisodePill: View {
    let episode: String
    init(_ episode: String) { self.episode = episode }

    var body: some View {
        Label(episode, systemImage: "doc.text")
            .font(.system(size: 10, weight: .regular, design: .monospaced))
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(CicadaTheme.surfaceHover.opacity(0.6))
            .clipShape(Capsule())
            .lineLimit(1)
    }
}

// MARK: - Wikilink rendering helper (shared with the claim layer)

/// Parse `[[Wikilinks]]` into an `AttributedString` where the link text is
/// highlighted in the accent color. Mirrors `EntityDetailCard`'s private
/// renderer so claim text reads consistently with entity bodies.
func renderWikilinks(_ text: String) -> AttributedString {
    var result = AttributedString()
    guard let regex = try? NSRegularExpression(pattern: "\\[\\[(.+?)\\]\\]") else {
        var plain = AttributedString(text)
        plain.foregroundColor = CicadaTheme.textPrimary
        return plain
    }
    let nsText = text as NSString
    var lastEnd = 0
    let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
    for match in matches {
        let beforeRange = NSRange(location: lastEnd, length: match.range.location - lastEnd)
        if beforeRange.length > 0 {
            result.append(AttributedString(nsText.substring(with: beforeRange)))
        }
        let linkRange = match.range(at: 1)
        var link = AttributedString(nsText.substring(with: linkRange))
        link.foregroundColor = CicadaTheme.accent
        link.font = CicadaTheme.bodyFont.weight(.medium)
        result.append(link)
        lastEnd = match.range.location + match.range.length
    }
    if lastEnd < nsText.length {
        result.append(AttributedString(nsText.substring(from: lastEnd)))
    }
    return result
}

// MARK: - Wrapping flow layout for the provenance footer

/// A simple wrapping horizontal layout so a claim's provenance pills wrap to the
/// next line instead of clipping on a narrow card. (Local copy so ClaimChip has
/// no cross-file dependency on EntityDetailCard's private FlowLayout.)
struct ClaimFooterFlow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        layout(subviews: subviews, in: proposal.width ?? .infinity).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let positions = layout(subviews: subviews, in: bounds.width).points
        for (index, subview) in subviews.enumerated() {
            let pt = positions[index]
            subview.place(at: CGPoint(x: bounds.minX + pt.x, y: bounds.minY + pt.y), proposal: .unspecified)
        }
    }

    private func layout(subviews: Subviews, in maxWidth: CGFloat) -> (size: CGSize, points: [CGPoint]) {
        var points: [CGPoint] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, totalWidth: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0; y += rowHeight + spacing; rowHeight = 0
            }
            points.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            totalWidth = max(totalWidth, x - spacing)
        }
        return (CGSize(width: totalWidth, height: y + rowHeight), points)
    }
}
