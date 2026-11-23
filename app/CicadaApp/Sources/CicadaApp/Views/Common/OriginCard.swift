import SwiftUI

/// One item of a history, as a card that reads at a glance: the words (two lines, the rest on a click), and under them
/// the app they came from and how long ago — `[mark] Chrome · 5d ago` (owner 2026-11-23: "by a glance we can see the
/// app, the reason, how long ago it was and it's a card that can be expanded", after Superwhisper's Recent
/// recordings). A click expands it to the full words and the card's `detail`.
///
/// **The newest is coloured, the older fade (owner 2026-11-23, DESIGN_RULES §9).** In a history the `current` card
/// wears the accent ring and a faint accent wash; `past` cards drop to `textSecondary` at reduced opacity, back to full
/// while the pointer is on them so they stay readable. A list of one is `current`.
///
/// Generic on purpose: anything the person said or kept that has an origin and a time — a bookmark's reasons today —
/// is drawn the same way. `OriginMark` draws the app (`OriginIconography.cicada` for the app itself).
struct OriginCard<Detail: View>: View {
    typealias Tone = OriginCardTone

    let text: String
    /// An origin key `OriginMark` knows; nil draws no app.
    var origin: String? = nil
    /// Overrides the origin's own name ("Chrome").
    var originName: String? = nil
    var date: Date? = nil
    /// A word after the age, e.g. "Waiting for Sleep".
    var note: String? = nil
    var tone: Tone = .current
    @ViewBuilder var detail: () -> Detail

    @State private var expanded = false
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(text)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(tone == .past ? CicadaTheme.textSecondary : CicadaTheme.textPrimary)
                .lineLimit(expanded ? nil : 2)
                .truncationMode(.tail)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            footer
            if expanded {
                detail()
                    .transition(.opacity)
            }
        }
        .originCardChrome(tone: tone, hovering: hovering, held: expanded)
        .onTapGesture { toggle(animated: true) }
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(accessibilityText)
        .accessibilityHint(expanded ? Copy.OriginCard.collapseHint : Copy.OriginCard.expandHint)
        .accessibilityAction { toggle(animated: false) }   // a keyboard action never animates (DR, §8)
    }

    private var footer: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            if let origin {
                OriginMark(origin: origin, size: CicadaTheme.scaled(16))
                Text(name(origin))
            }
            ForEach(Array(trail.enumerated()), id: \.offset) { index, part in
                if index > 0 || origin != nil { Text("·") }
                Text(part).monospacedDigit()
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Image(systemName: "chevron.down")
                .font(CicadaTheme.font(size: 9, weight: .semibold))
                .rotationEffect(.degrees(expanded ? 180 : 0))
                .opacity(hovering || expanded ? 1 : 0)
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
        .lineLimit(1)
    }

    /// The age, then the note: each after a middle dot.
    private var trail: [String] {
        var out: [String] = []
        if let date { out.append(Copy.OriginCard.ago(date, now: Date())) }
        if let note { out.append(note) }
        return out
    }

    private func name(_ origin: String) -> String { originName ?? OriginIconography.label(for: origin) }

    private var accessibilityText: String {
        ([text] + [origin.map(name)].compactMap { $0 } + trail).joined(separator: ", ")
    }

    private func toggle(animated: Bool) {
        if animated, let animation = CicadaMotion.expand(reduceMotion: reduceMotion) {
            withAnimation(animation) { expanded.toggle() }
        } else {
            expanded.toggle()
        }
    }
}

extension OriginCard where Detail == EmptyView {
    init(text: String, origin: String? = nil, originName: String? = nil, date: Date? = nil, note: String? = nil,
         tone: Tone = .current) {
        self.init(text: text, origin: origin, originName: originName, date: date, note: note, tone: tone) { EmptyView() }
    }
}

/// The card's look is `SoftCardChrome` (`Theme/SoftCard.swift`), the one chrome every card of the app wears; the family
/// of cards that sit inside another card (`OriginCard`, `EpisodeCard`, `ChatCard`) takes its `nested` ground.
extension View {
    func originCardChrome(tone: OriginCardTone, hovering: Bool, held: Bool = false) -> some View {
        softCard(ground: .nested, tone: tone, hovering: hovering, held: held)
    }
}
