import SwiftUI

/// Which half of the Activity page is showing.
///
/// Raw values double as the segment labels AND the persisted `@AppStorage`
/// value, so they must not drift from what the user sees.
enum ActivitySection: String, CaseIterable, Identifiable {
    case usage = "Usage"
    case contributors = "Contributors"
    case conversations = "Conversations"

    var id: String { rawValue }

    /// Decodes the persisted segment. An unknown or missing value falls back
    /// to Usage rather than trapping — the string comes from a defaults domain
    /// that an older build (or another machine, via a synced domain) may have
    /// written.
    static func restored(from raw: String?) -> ActivitySection {
        guard let raw, let section = ActivitySection(rawValue: raw) else { return .usage }
        return section
    }
}

/// The merged Activity page (G68 §1): consumption and attribution are two
/// answers to one question — what did the system do, and who did it — so they
/// share a page, a header and the origins strip that used to sit on Capture.
///
/// Every value here is a projection over `Store` snapshots (§5.5); this view
/// starts no fetches of its own.
struct ActivityView: View {
    /// Entity navigation for the Conversations section's entity chips (G48
    /// §4) — same closure shape the Ask panel's citations use. Optional so a
    /// preview/host without navigation still renders the page.
    var onSelectEntity: ((String) -> Void)?

    @AppStorage("cicada.activitySection") private var sectionRaw = ActivitySection.usage.rawValue
    @Environment(UsageViewModel.self) private var usageVM
    @Environment(Store.self) private var store

    private var section: ActivitySection { ActivitySection.restored(from: sectionRaw) }
    private var origins: [OriginStat] { store.origins.value ?? [] }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PageHeader(title: Copy.activity, subtitle: Copy.activitySubtitle) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Picker("Section", selection: Binding(
                        get: { section },
                        set: { sectionRaw = $0.rawValue }
                    )) {
                        ForEach(ActivitySection.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented).labelsHidden().fixedSize()
                    .accessibilityLabel("Show usage, contributors, or conversations")

                    if section == .usage { UsageRangeControls(viewModel: usageVM) }
                }
            }

            originsStrip

            switch section {
            case .usage: UsageSection()
            case .contributors: ContributorsSection()
            case .conversations: ConversationsSection(onSelectEntity: onSelectEntity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.background)
    }

    /// Provenance pills, moved here from the Capture page: "where your memory
    /// comes from" is the same provenance question the two sections answer.
    @ViewBuilder
    private var originsStrip: some View {
        if !origins.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(Copy.originsLabel)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(origins) { OriginPill(origin: $0) }
                    }
                    .padding(.vertical, 2)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .accessibilityLabel("Where your memory comes from: \(origins.count) sources")
        }
    }
}
