import AppKit
import SwiftUI

/// Whether a token had a space before it in the sentence (R-PP15); `SentenceFlowLayout` draws the gap.
private struct SpaceBefore: LayoutValueKey {
    static let defaultValue = false
}

/// R-PP15 — a sentence laid out token by token: words and chips flow left to right and wrap at the width, each line's
/// tokens centred on one line, so a 22-unit chip and the words beside it share a centre (the mock's inline chips). Not
/// the entity card's `FlowLayout`, which top-aligns and spaces every item alike.
struct SentenceFlowLayout: Layout {
    var space: CGFloat
    var lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(subviews, width: proposal.width ?? .infinity).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arranged = arrange(subviews, width: bounds.width)
        for (i, subview) in subviews.enumerated() {
            let f = arranged.frames[i]
            subview.place(at: CGPoint(x: bounds.minX + f.minX, y: bounds.minY + f.minY), proposal: ProposedViewSize(f.size))
        }
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> (size: CGSize, frames: [CGRect]) {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        var lines: [[Int]] = [[]]
        var x: CGFloat = 0
        for (i, size) in sizes.enumerated() {
            let gap = subviews[i][SpaceBefore.self] && x > 0 ? space : 0
            if x > 0, x + gap + size.width > width {
                lines.append([])
                x = 0
            }
            x += (subviews[i][SpaceBefore.self] && x > 0 ? space : 0) + size.width
            lines[lines.count - 1].append(i)
        }
        var frames = Array(repeating: CGRect.zero, count: sizes.count)
        var y: CGFloat = 0
        var widest: CGFloat = 0
        for line in lines where !line.isEmpty {
            let height = line.map { sizes[$0].height }.max() ?? 0
            var lx: CGFloat = 0
            for i in line {
                if subviews[i][SpaceBefore.self], lx > 0 { lx += space }
                frames[i] = CGRect(x: lx, y: y + (height - sizes[i].height) / 2, width: sizes[i].width, height: sizes[i].height)
                lx += sizes[i].width
            }
            widest = max(widest, lx)
            y += height + lineSpacing
        }
        return (CGSize(width: min(widest, width), height: max(0, y - lineSpacing)), frames)
    }
}

/// R-PP15 — a happening as ONE sentence: its words, the owner as the sentence's own word with a "you" tag, and every
/// page a chip that opens its card in the third column. A happening's sentence leads its row (14, `textPrimary`); a
/// moment's is its fact (13, `textSecondary`).
struct StorySentence: View {
    let text: String
    let participants: [ProjectParticipant]
    var lead = true
    let openEntity: (String) -> Void

    private var font: Font { lead ? CicadaTheme.detailBodyFont : CicadaTheme.bodyFont }
    private var ink: Color { lead ? CicadaTheme.textPrimary : CicadaTheme.textSecondary }

    var body: some View {
        let parts = ProjectStory.tokens(text, participants: participants)
        SentenceFlowLayout(space: CicadaTheme.scaled(4), lineSpacing: CicadaTheme.scaled(3)) {
            ForEach(parts.tokens) { token in
                tokenView(token).layoutValue(key: SpaceBefore.self, value: token.spaceBefore)
            }
            ForEach(Array(parts.extra.enumerated()), id: \.offset) { _, p in
                ParticipantChip(participant: p, text: p.name, trailing: "", font: font, open: openEntity)
                    .layoutValue(key: SpaceBefore.self, value: true)
            }
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private func tokenView(_ token: StoryToken) -> some View {
        switch token.kind {
        case .word:
            Text(token.text).font(font).foregroundStyle(ink)
        case .owner:
            if let p = token.participant { OwnerChip(participant: p, text: token.text, trailing: token.trailing, font: font) }
        case .page:
            if let p = token.participant {
                ParticipantChip(participant: p, text: token.text, trailing: token.trailing, font: font, open: openEntity)
            }
        }
    }
}

/// A page the sentence names: its type's dot (DR-8: a hue once per item) and the sentence's own words on a neutral
/// capsule (never a tinted pill, DR-44); a click opens its card. A document with a URL adds ↗, a link (DR-5 use 5).
struct ParticipantChip: View {
    let participant: ProjectParticipant
    let text: String
    let trailing: String
    let font: Font
    let open: (String) -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 0) {
            Button { if let id = participant.id { open(id) } } label: {
                HStack(spacing: CicadaTheme.scaled(5)) {
                    TypeDot(type: participant.type)
                    Text(text).font(font).fontWeight(.medium).foregroundStyle(CicadaTheme.textPrimary)
                }
                .padding(.leading, CicadaTheme.scaled(7))
                .padding(.trailing, CicadaTheme.scaled(8))
                .frame(height: CicadaTheme.scaled(22))
                .background(Capsule().fill(hovering ? CicadaTheme.bgButtonHover : CicadaTheme.bgSelected))
                .contentShape(Capsule())
            }
            .buttonStyle(.cicadaPlain)
            .onHover { hovering = $0 }
            .help(Copy.Projects.openEntity(participant.name, type: participant.type.label))
            .accessibilityLabel(Copy.Projects.openEntity(participant.name, type: participant.type.label))
            if let url = participant.url.flatMap(URL.init(string:)) {
                Button { NSWorkspace.shared.open(url) } label: {
                    Image(systemName: "arrow.up.right")
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.accentText)
                        .padding(.horizontal, CicadaTheme.scaled(4))
                        .frame(height: CicadaTheme.scaled(22))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help(Copy.Projects.openLink(url.host ?? ""))
                .accessibilityLabel(Copy.Projects.openLink(url.host ?? ""))
            }
            if !trailing.isEmpty { Text(trailing).font(font).foregroundStyle(CicadaTheme.textSecondary) }
        }
    }
}

/// R-PP15 — the owner: the sentence's own word with a small "you" tag (the owner's own "[user]" made visual; G117's
/// "Name (you)"). It opens nothing: the page is already about you. The tag sits on `bgBase`, not `Tag`'s `bgSelected`,
/// because it rides on a `bgSelected` capsule and would vanish.
struct OwnerChip: View {
    let participant: ProjectParticipant
    let text: String
    let trailing: String
    let font: Font

    var body: some View {
        HStack(spacing: 0) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Text(text).font(font).fontWeight(.medium).foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.Projects.you)
                    .font(CicadaTheme.captionFont)
                    .fontWeight(.medium)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.scaled(5))
                    .frame(height: CicadaTheme.scaled(16))
                    .background(Capsule().fill(CicadaTheme.bgBase))
            }
            .padding(.leading, CicadaTheme.scaled(8))
            .padding(.trailing, CicadaTheme.scaled(4))
            .frame(height: CicadaTheme.scaled(22))
            .background(Capsule().fill(CicadaTheme.bgSelected))
            .help(Copy.Projects.youHelp(participant.name))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Copy.Projects.youHelp(participant.name))
            if !trailing.isEmpty { Text(trailing).font(font).foregroundStyle(CicadaTheme.textSecondary) }
        }
    }
}

/// R-PP16 — where a row came from, once (DR-54): the origin's real mark (DR-52) and "<App> · <title>", its evidence
/// chip (who spoke and the day, DR-57), and "Show in conversation ›" into the Reader column (DR-31). Nothing is served
/// as `[ no source recorded ]`, exactly as written, at meta weight (DR-55).
struct ProjectSourceLineView: View {
    let line: ProjectSource.Line
    let evidence: Evidence?
    let subjectId: String
    let showing: Bool
    let show: (() -> Void)?

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            switch line {
            case .conversation(let origin, let app, let title):
                OriginMark(origin: origin, size: CicadaTheme.scaled(14))
                Text(Eyebrow.text(app, title)).lineLimit(1)
            case .note:
                Image(systemName: "square.and.pencil").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                Text(Copy.Projects.yourNote)
            case .setByYou:
                Image(systemName: "pencil").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                Text(Copy.Projects.setByYou)
            case .pageHistory:
                Text(Copy.Projects.pageHistory)
            case .none:
                Text(Copy.Projects.noSource)
            case .chipOnly:
                EmptyView()
            }
            if let evidence {
                EvidenceChip(model: EvidenceChipModel(source: .stored(evidence)), subjectId: subjectId)
            }
            Spacer(minLength: 0)
            if let show {
                InlineLink(title: showing ? Copy.Projects.hideConversation : Copy.Projects.showInConversation,
                           help: Copy.Projects.showHelp, action: show)
            }
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
    }
}

/// An expanded row's words (the mock's quote), through `QuoteBlock` — the one door: washed when quoted, bold when found
/// by name, plain when stale (G118 §4.9). Fetched on demand through `ProvenanceCache`; nothing is copied.
struct ProjectQuoteBlock: View {
    let evidence: Evidence
    @Environment(ProvenanceCache.self) private var provenanceCache
    @State private var span: EpisodeSpan?

    var body: some View {
        Group {
            if let span, !span.text.isEmpty {
                QuoteBlock(before: span.before, span: span.text, after: span.after, kind: evidence.kind, label: nil,
                           caption: nil, style: span.stale ? .plain : (evidence.kind == .derived ? .bold : .wash))
            }
        }
        .task(id: evidence) { span = await provenanceCache.span(evidence).value }
    }
}

/// A story row's surface (the mock): `bgHover` under the pointer, `bgFocus` with the strong ring while selected — a
/// ring, never a shadow (DR-9). It grows with its content (rows expand in place), so it is not `ListRowSurface`.
struct StoryRowSurface: ViewModifier {
    let selected: Bool
    @State private var hovering = false

    func body(content: Content) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadius)
        return content
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(shape.fill(selected ? CicadaTheme.bgFocus : (hovering ? CicadaTheme.bgHover : Color.clear)))
            .overlay { if selected { shape.strokeBorder(CicadaTheme.ring(.strong), lineWidth: 1) } }
            .contentShape(Rectangle())
            .onHover { hovering = $0 }
    }
}

/// A row's status glyph (the mock): ● done, ◐ ongoing, ○ said here, a tick for history, a square for stopped — neutral
/// shapes, never a hue (R-PJ21); one glyph, never a dot beside it (DR-48).
struct StoryGlyph: View {
    let glyph: ProjectStory.Glyph

    var body: some View {
        let side = CicadaTheme.scaled(glyph == .ongoing ? 10 : 8)
        Group {
            switch glyph {
            case .done:
                Circle().fill(CicadaTheme.textSecondary)
            case .ongoing:
                Circle().strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(CicadaTheme.textSecondary).frame(width: side / 2)
                    }
                    .clipShape(Circle())
            case .said:
                Circle().strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5)
            case .history:
                CicadaTheme.shape(1).fill(CicadaTheme.textTertiary).frame(width: CicadaTheme.scaled(3))
            case .stopped:
                CicadaTheme.shape(2).strokeBorder(CicadaTheme.textTertiary, lineWidth: 1.5)
            }
        }
        .frame(width: side, height: glyph == .history ? CicadaTheme.scaled(11) : side)
        .accessibilityHidden(true)
    }
}

/// The Plan's diamond (§3.8's shapes): filled when done, hollow when planned, slashed when it passed with no word.
struct PlanDiamond: View {
    let style: ProjectPlan.Diamond

    var body: some View {
        let shape = CicadaTheme.shape(1.5)
        let side = CicadaTheme.scaled(9)
        shape.fill(style == .filled ? CicadaTheme.textPrimary : CicadaTheme.bgBase)
            .overlay { if style != .filled { shape.strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5) } }
            .frame(width: side, height: side)
            .rotationEffect(.degrees(45))
            .overlay { if style == .slashed { Rectangle().fill(CicadaTheme.textSecondary).frame(width: 1.5, height: CicadaTheme.scaled(14)) } }
            .frame(width: CicadaTheme.scaled(14), height: CicadaTheme.scaled(14))
            .accessibilityHidden(true)
    }
}
