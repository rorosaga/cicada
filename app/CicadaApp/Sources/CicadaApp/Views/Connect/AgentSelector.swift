import SwiftUI

/// Round 4 C8 — the row of agents, each a real mark over its name, one selected, a ✓ on every agent Cicada has
/// seen connect. Self-contained on purpose: Settings → Agents hosts it today and phase B's onboarding reuses it,
/// so it takes plain values (the entries, a selection binding, two id sets) and fetches nothing.
///
/// R-AG16 (DR-5, DR-7): selection is neutral — `bgSelected` with the strong ring, sliding from pill to pill by
/// `matchedGeometryEffect` under `CicadaMotion.standard` (Reduce Motion jumps) — and only the ✓ is green,
/// because "an agent Cicada has seen connect" is the same kind of fact as the import ✓. R-AG15: the ✓ scales in
/// once, and only for a pill that flipped while this view was on screen (`justConnected`); one connected at first
/// load is simply there. No keyboard shortcut: the pills are buttons in the focus order, nothing more (DR-60).
struct AgentSelector: View {
    let entries: [AgentCatalogEntry]
    @Binding var selection: String
    let connected: Set<String>
    let justConnected: Set<String>

    @Namespace private var namespace
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        // 80, not 68: at 68 the live Settings → Agents read "Claude C…" (orchestrator live check, 2026-09-24).
        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(80)), spacing: CicadaTheme.scaled(4))],
                  spacing: CicadaTheme.scaled(4)) {
            ForEach(entries) { entry in pill(entry) }
        }
        .padding(CicadaTheme.scaled(4))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }

    private func pill(_ entry: AgentCatalogEntry) -> some View {
        let selected = selection == entry.id
        let isConnected = connected.contains(entry.id)
        return Button {
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selection = entry.id }
        } label: {
            VStack(spacing: CicadaTheme.scaled(4)) {
                AgentMark(entry: entry, size: 20)
                Text(entry.name)
                    .font(CicadaTheme.font(size: 11, weight: selected ? .medium : .regular))
                    .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
                    .truncationMode(.tail)
            }
            .padding(.vertical, CicadaTheme.spacingSM)
            .padding(.horizontal, CicadaTheme.scaled(4))
            .frame(maxWidth: .infinity)
            .background {
                if selected {
                    CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                        .fill(CicadaTheme.bgSelected)
                        .ringed(.strong, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                        .matchedGeometryEffect(id: "selection", in: namespace)
                }
            }
            .overlay(alignment: .topTrailing) {
                if isConnected {
                    check
                        .transition(reduceMotion ? .opacity : .scale.combined(with: .opacity))
                }
            }
            .animation(justConnected.contains(entry.id)
                       ? (reduceMotion ? CicadaMotion.fade : CicadaMotion.success(reduceMotion: false))
                       : nil,
                       value: isConnected)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(entry.name)
        .accessibilityValue(isConnected ? Copy.agentConnectedBadge : "")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    /// The ✓ bubble: `success` on a `bgFocus` circle so it reads over the selected fill and the card alike.
    private var check: some View {
        Image(systemName: "checkmark.circle.fill")
            .font(CicadaTheme.font(size: 12))
            .foregroundStyle(CicadaTheme.success)
            .background(Circle().fill(CicadaTheme.bgFocus))
            .padding(CicadaTheme.scaled(3))
            .accessibilityHidden(true)
    }
}

/// An agent's mark at `size`: its bundled mark through `LogoImage` (so `claude-code` gets its `>_` badge, R-AG8),
/// else its SF Symbol in `textSecondary` (Grok until a sourced xAI mark exists, R-AG9). A plain mark is clipped
/// to a rounded square because `hermes` is a full-bleed plate (DR-52); a composed mark is not, since its base is
/// transparent-cornered and a clip would shave the badge at its outer corner.
struct AgentMark: View {
    let entry: AgentCatalogEntry
    let size: CGFloat

    var body: some View {
        let side = CicadaTheme.scaled(size)
        if let mark = entry.mark, LogoImage.exists(name: mark) {
            if BrandMark.composition(for: mark).badge != nil {
                LogoImage(name: mark, size: side)
            } else {
                LogoImage(name: mark, size: side)
                    .clipShape(CicadaTheme.shape(side * 0.22))
            }
        } else {
            Image(systemName: entry.symbol)
                .font(CicadaTheme.font(size: size * 0.8))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: side, height: side)
        }
    }
}
