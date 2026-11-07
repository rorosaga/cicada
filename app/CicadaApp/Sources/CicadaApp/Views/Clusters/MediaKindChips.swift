import SwiftUI

/// ROR-138 follow-up (owner 2026-11-06) — Media's kinds, visible at a glance on the Media tab: one chip row under the
/// tab row, "All" then each kind that holds something, with its count. The same selection the View menu edits
/// (`mediaKinds`: empty is everything but unmentioned feed items), so a chip and the menu never disagree. A key never
/// animates (DR-60); hover is a fill (DR-48); a chip is a word and a number, never an icon (DR-47).
struct MediaKindChips: View {
    @Binding var selected: Set<String>
    let counts: [String: Int]
    let gutter: CGFloat

    private var kinds: [String] { ClustersModel.mediaKindOrder.filter { (counts[$0] ?? 0) > 0 } }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: CicadaTheme.spacingXS) {
                MediaKindChip(label: Copy.Lists.mediaKindAll, count: nil, on: selected.isEmpty) { selected = [] }
                ForEach(kinds, id: \.self) { kind in
                    MediaKindChip(label: Copy.Lists.mediaKind(kind), count: counts[kind], on: selected.contains(kind)) {
                        if selected.contains(kind) { selected.remove(kind) } else { selected.insert(kind) }
                    }
                }
            }
            .padding(.horizontal, gutter)
            .padding(.vertical, CicadaTheme.spacingSM)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Lists.mediaKindsLabel)
    }
}

private struct MediaKindChip: View {
    let label: String
    let count: Int?
    let on: Bool
    let tap: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: tap) {
            HStack(spacing: CicadaTheme.scaled(5)) {
                Text(label).font(CicadaTheme.metaFont.weight(on ? .semibold : .regular))
                    .foregroundStyle(on ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                if let count {
                    Text(UsageFormat.count(count)).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(minHeight: CicadaTheme.scaled(26))
            .background(Capsule().fill(on ? CicadaTheme.bgFocus : (hovering ? CicadaTheme.bgHover : .clear)))
            .overlay(Capsule().strokeBorder(on ? CicadaTheme.border : CicadaTheme.borderLight, lineWidth: 1))
            .contentShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(count.map { "\(label), \($0)" } ?? label)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
