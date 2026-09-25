import SwiftUI

/// R-DL9 — the page's ONE filter (§10: "11/11" and "Labels" fold into one View menu). Types are the Graph's own filter
/// (`graphVM.filter.types`: one filter, two surfaces, as before); labels narrow to pages carrying any chosen label (the
/// retired label popover's search and cap); "Expand all" shows every row of every group in All (DR-39, remembered).
struct ClustersViewMenu: View {
    @Binding var types: Set<EntityType>
    @Binding var labels: Set<String>
    let labelCounts: [(label: String, count: Int)]
    let typeCounts: [EntityType: Int]
    @Binding var expandAll: Bool
    @State private var labelQuery = ""

    /// The retired popover built up to 100 rows and froze on open; eight and a search is the mock's answer.
    static let labelCap = 8

    private var matchingLabels: [(label: String, count: Int)] {
        let q = labelQuery.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? labelCounts : labelCounts.filter { $0.label.lowercased().contains(q) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            header(Copy.Lists.typesShared,
                   trailing: Copy.Lists.typesShown(types.count, of: EntityType.selectableCases.count))
            ForEach(EntityType.selectableCases) { type in
                checkRow(on: types.contains(type), dot: type, label: type.label, count: typeCounts[type] ?? 0) {
                    if types.contains(type) { types.remove(type) } else { types.insert(type) }
                }
            }
            if types.count < EntityType.selectableCases.count {
                menuRow(Copy.Lists.showEveryType) { types = Set(EntityType.selectableCases) }
            }
            header(Copy.Lists.labels,
                   trailing: labels.isEmpty ? Copy.Lists.labelCount(labelCounts.count) : Copy.Lists.labelsOn(labels.count))
                .padding(.top, CicadaTheme.spacingSM)
            CicadaSearchField(text: $labelQuery, prompt: Copy.Lists.searchLabels, findEnabled: false)
                .padding(.vertical, CicadaTheme.scaled(4))
            ForEach(matchingLabels.prefix(Self.labelCap), id: \.label) { entry in
                checkRow(on: labels.contains(entry.label), dot: nil, label: entry.label, count: entry.count) {
                    if labels.contains(entry.label) { labels.remove(entry.label) } else { labels.insert(entry.label) }
                }
            }
            if matchingLabels.isEmpty {
                note(labelQuery.trimmingCharacters(in: .whitespaces).isEmpty ? Copy.Lists.noLabels : Copy.Lists.noLabelMatch)
            } else if matchingLabels.count > Self.labelCap {
                note(Copy.Lists.moreLabels(matchingLabels.count - Self.labelCap))
            }
            if !labels.isEmpty { menuRow(Copy.Lists.clearLabels) { labels = [] } }
            header(Copy.Lists.groupsInAll, trailing: nil).padding(.top, CicadaTheme.spacingSM)
            menuRow(expandAll ? Copy.Lists.collapseAll : Copy.Lists.expandAll) { expandAll.toggle() }
        }
        .padding(CicadaTheme.scaled(6))
        .frame(width: CicadaTheme.scaled(260))
        .background(CicadaTheme.bgMenu)
    }

    private func header(_ title: String, trailing: String?) -> some View {
        HStack {
            SectionLabel(title)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let trailing {
                Text(trailing).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .padding(.top, CicadaTheme.scaled(4))
    }

    private func checkRow(on: Bool, dot: EntityType?, label: String, count: Int,
                          action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "checkmark")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .opacity(on ? 1 : 0)
                    .accessibilityHidden(true)
                if let dot { TypeDot(type: dot).opacity(on ? 1 : 0.35) }
                Text(label)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(on ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(UsageFormat.count(count)).font(CicadaTheme.metaFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .buttonStyle(.cicadaPlain)
        .listRowSurface(height: 28, selected: false)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private func menuRow(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textSecondary)
                .padding(.leading, CicadaTheme.scaled(22))
        }
        .buttonStyle(.cicadaPlain)
        .listRowSurface(height: 28, selected: false)
    }

    private func note(_ text: String) -> some View {
        Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            .padding(.leading, CicadaTheme.scaled(30))
            .frame(height: CicadaTheme.scaled(26))
    }
}
