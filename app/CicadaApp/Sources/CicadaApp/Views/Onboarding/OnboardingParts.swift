import SwiftUI

/// A working page's headline (DR-17's fourth call site: onboarding headlines) and its one line. ROR-118: 36 pt over a
/// 17 pt line in the secondary ink, up from 28 over 14, so the step's name is the first thing read and the line a clear
/// second (hierarchy, DR-15's display role kept).
struct OnboardingHeadline: View {
    let title: String
    let subline: String

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(title)
                .font(CicadaTheme.displayFont(size: 36))
                .tracking(CicadaTheme.displayTracking(size: 36))
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Text(subline)
                .font(CicadaTheme.font(size: 17))
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One option of a pair that are equals (ROR-118: "Use an API key" read as a stray label beside a plan row that had no
/// selected state). The chosen one carries a `textPrimary` ring and a filled check, never the accent (DR-5, "selection is
/// a `textPrimary` ring"); the other is the same card at rest with an open circle. With an `action` the whole row is the
/// button.
struct OnboardingChoice<Content: View>: View {
    let selected: Bool
    var action: (() -> Void)? = nil
    @ViewBuilder var content: (_ indicator: AnyView) -> Content

    var body: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadius)
        let indicator = AnyView(
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .font(CicadaTheme.font(size: 20))
                .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.ring(.input))
                .accessibilityHidden(true))
        let row = content(indicator)
            .padding(.vertical, CicadaTheme.spacingXS)
            .frame(minHeight: CicadaTheme.scaled(64))
            .background(shape.fill(CicadaTheme.bgFocus))
            .overlay(shape.strokeBorder(selected ? CicadaTheme.textPrimary : CicadaTheme.ring(.resting),
                                        lineWidth: selected ? 1.5 : 1))
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
