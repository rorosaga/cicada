import SwiftUI

/// A working page's headline (DR-17's fourth call site: onboarding headlines) and its one line. ROR-118: 40 pt over an
/// 18 pt line (round 3; 36 over 17 in round 2) in the secondary ink, up from 28 over 14, so the step's name is the first thing read and the line a clear
/// second (hierarchy, DR-15's display role kept).
struct OnboardingHeadline: View {
    let title: String
    let subline: String

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(title)
                .font(CicadaTheme.displayFont(size: 40))
                .tracking(CicadaTheme.displayTracking(size: 40))
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Text(subline)
                .font(CicadaTheme.font(size: 18))
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One option of a pair that are equals (ROR-118: "Use an API key" read as a stray label beside a plan row that had no
/// selected state). Round 2: the chosen one is unmistakable at a glance — a 2 pt `textPrimary` ring (DR-5, "selection is
/// a `textPrimary` ring"), the `bgSelected` fill and a filled check; the other is the same row at rest with an open
/// circle. With an `action` the whole row is the button.
struct OnboardingChoice<Content: View>: View {
    let selected: Bool
    var action: (() -> Void)? = nil
    @ViewBuilder var content: (_ indicator: AnyView) -> Content

    var body: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadius)
        let indicator = AnyView(
            // Round 3: the open circle is read in the secondary ink, a real circle beside the chosen row's filled one,
            // not a ring-strength ghost beside a 2 pt outline.
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .font(CicadaTheme.font(size: 26, weight: selected ? .regular : .light))
                .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .accessibilityHidden(true))
        let row = content(indicator)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(minHeight: CicadaTheme.scaled(104))
            .background(shape.fill(selected ? CicadaTheme.bgSelected : CicadaTheme.bgFocus))
            .overlay(shape.strokeBorder(selected ? CicadaTheme.textPrimary : CicadaTheme.ring(.strong),
                                        lineWidth: selected ? 2 : 1))
            .contentShape(shape)
        if let action {
            Button(action: action) { row }
                .buttonStyle(.cicadaPlain)
                .accessibilityAddTraits(selected ? .isSelected : [])
        } else {
            row.accessibilityElement(children: .combine)
                .accessibilityAddTraits(selected ? .isSelected : [])
        }
    }
}

/// A row of the working steps (ROR-118 round 2): `ConnectionLine`'s anatomy one step larger and brighter — a 16 pt
/// medium name over a 14 pt line in the secondary ink, not 14 over a dim 12 — in the one shared `LogoTile`, so every
/// provider reads as one family (DR-52). Its action is `trailing`; a state, when there is one, `status`.
struct OnboardingRowLine<Trailing: View, Below: View>: View {
    var logo: String?
    var name: String
    var systemFallback: String = LogoTile.monogramFallback
    var prominentGlyph = false
    var detail: String? = nil
    var status: (word: String, on: Bool)? = nil
    var detailLines = 1
    @ViewBuilder var trailing: () -> Trailing
    @ViewBuilder var below: () -> Below

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoTile(logo: logo, name: name, density: .roomy, systemFallback: systemFallback, glyphProminent: prominentGlyph)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(name)
                        .font(CicadaTheme.font(size: 17, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let detail, !detail.isEmpty {
                        Text(detail)
                            .font(CicadaTheme.font(size: 15))
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(detailLines)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let status { StatusDot(word: status.word, on: status.on) }
                trailing()
            }
            below()
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(80), alignment: .leading)
    }
}

extension OnboardingRowLine where Below == EmptyView {
    init(logo: String?, name: String, systemFallback: String = LogoTile.monogramFallback, prominentGlyph: Bool = false,
         detail: String? = nil, status: (word: String, on: Bool)? = nil, detailLines: Int = 1,
         @ViewBuilder trailing: @escaping () -> Trailing) {
        self.init(logo: logo, name: name, systemFallback: systemFallback, prominentGlyph: prominentGlyph, detail: detail,
                  status: status, detailLines: detailLines, trailing: trailing, below: { EmptyView() })
    }
}

/// The one action on a working step's row (ROR-118 round 2): words and a chevron, no box, so four of them never compete
/// with the step's one filled Continue; the row's own hover fill says it is live. The key, a plan and every other
/// verb that opens a row use it.
struct OnboardingRowAction: View {
    let title: String
    let action: () -> Void
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(4)) {
                Text(title).font(CicadaTheme.font(size: 16, weight: .medium))
                Image(systemName: "chevron.right").font(CicadaTheme.font(size: 12, weight: .semibold))
            }
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(32))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgSelected : .clear))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

extension View {
    /// Welcome's and Done's card under the study room (looks pass 2026-10-23): the focus card's material — `bgFocus`,
    /// `radiusLarge`, the resting ring. It sits in the page, so it never floats: no shadow in light mode (DR-9, DR-10,
    /// "depth is a ring").
    func onboardingCard() -> some View {
        background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
            .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
    }
}

/// "More sources any time on the Sources page" — a sentence ending in the one door into Settings
/// (`SettingsSectionLink`, R-DS22), so a pointer never re-types a destination (G68 §2.8).
struct OnboardingPointerLine: View {
    let lead: String
    let home: SettingsHome
    let label: String
    @Environment(AppRouter.self) private var router: AppRouter?

    init(lead: String, section: SettingsSection, label: String) {
        self.init(lead: lead, home: .settings(section, nil), label: label)
    }

    /// D6 — Sources and Agents are sidebar pages now; their pointer opens the page.
    init(lead: String, home: SettingsHome, label: String) {
        self.lead = lead
        self.home = home
        self.label = label
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(lead).foregroundStyle(CicadaTheme.textSecondary)
            switch home {
            case let .settings(section, row): SettingsSectionLink(section: section, row: row, label: label)
            case .page, .readingInBrowser:
                Button { router?.open(home) } label: { Text(label).foregroundStyle(CicadaTheme.accentText) }
                    .buttonStyle(.cicadaPlain)
            }
        }
        .font(CicadaTheme.captionFont)
    }
}

/// A quiet action of a working step's foot or of Welcome's action line (ROR-118 round 3): 16 pt medium words in the
/// secondary ink, brightening on hover, an optional leading chevron for Back. Only Continue is filled; these are the
/// words around it, all set in one family so Back, Skip and Set up later read as one kind of control in one place.
struct OnboardingLink: View {
    let title: String
    var leadingChevron = false
    let action: () -> Void
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(4)) {
                if leadingChevron { Image(systemName: "chevron.left").font(CicadaTheme.font(size: 12, weight: .semibold)) }
                Text(title).font(CicadaTheme.font(size: 16, weight: .medium))
            }
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(40))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgSelected : .clear))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
