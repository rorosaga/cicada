import AppKit
import SwiftUI

/// §10 Feed / R-DL15 — one saved item as the detail column: what it is, the item itself (a player where the provider
/// has one, the page's card otherwise), why it is saved and where it came from. It is the retired
/// `FeedItemPreviewSheet`'s body moved into the column (R-DL16), so a video plays at the column's width, not in a
/// 480 pt sheet. No "Show in conversation": `/sources` carries no saving episode (reported).
struct FeedItemDetail: View {
    let item: MediaFeedItem
    let padding: CGFloat
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(FeedViewModel.self) private var viewModel
    @State private var enrichedDescription: String?

    private var title: String { item.title.isEmpty ? item.url : item.title }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Text(title)
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            MediaPreview(model: previewModel)
                .padding(.top, CicadaTheme.scaled(20))
            SectionLabel(Copy.Lists.whySaved).padding(.top, CicadaTheme.scaled(24)).padding(.bottom, CicadaTheme.scaled(6))
            why
            SectionLabel(Copy.Lists.savedFrom).padding(.top, CicadaTheme.scaled(24)).padding(.bottom, CicadaTheme.scaled(6))
            savedFrom
            Text(meta)
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.top, CicadaTheme.scaled(20))
        }
        .padding(padding)
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth), alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .task(id: item.id) { await loadDescription() }
    }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let n = hiddenListCount {
                TextButton(title: Copy.Lists.savedBack(n), help: Copy.Lists.showList, action: onShowList)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
            Text(Eyebrow.text(FeedKind.of(item).singular, item.site ?? ""))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            IconButton(systemName: "link", help: Copy.Lists.copyLink) {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(item.url, forType: .string)
                store.toast = Copy.Lists.linkCopied
            }
            IconButton(systemName: "point.3.connected.trianglepath.dotted", help: Copy.Lists.showOnGraph) {
                router.routeToEntity(item.mediaEntityId)
            }
            IconButton(systemName: "xmark", help: Copy.Lists.closeCard, action: onClose)
        }
        .frame(minHeight: CicadaTheme.scaled(28))
        .padding(.bottom, CicadaTheme.spacingSM)
    }

    @ViewBuilder
    private var why: some View {
        let about = FeedWhy.about(item, names: store.entityNames)
        let own = FeedWhy.ownWords(item)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let own {
                Text(own)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !about.isEmpty {
                FlowLayout(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Lists.about).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    ForEach(about, id: \.id) { entry in
                        // DR-5 use 5 — a link.
                        Button(entry.name) { router.routeToClustersEntity(entry.id) }
                            .buttonStyle(.cicadaPlain)
                            .font(CicadaTheme.detailBodyFont)
                            .foregroundStyle(CicadaTheme.accentText)
                            .help(Copy.Lists.openInClusters(entry.name))
                    }
                }
            }
            if own == nil && about.isEmpty {
                Text(Copy.Lists.nothingPointsHere).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private var savedFrom: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let origin = FeedSourceLine.markOrigin(item) {
                OriginMark(origin: origin, size: CicadaTheme.scaled(14)).markHover()
            }
            Text(FeedSourceLine.text(item))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
        }
        .help(FeedSourceLine.help(item) ?? "")
    }

    private var meta: String {
        var parts: [String] = []
        if let day = FeedDates.day(item, withYear: true) { parts.append(Copy.Lists.savedOn(day)) }
        if viewModel.scoresAreInformative {
            parts.append(Copy.Lists.relevanceLine(UsageFormat.percent(item.relevance * 100)))
        }
        return parts.joined(separator: " · ")
    }

    private var previewModel: MediaPreviewModel {
        var model = MediaPreviewModel(item: item)
        model.description = enrichedDescription
        return model
    }

    /// G102 R12 — the row carries its description; fetching the page is only the fallback for an older backend.
    private func loadDescription() async {
        if let seeded = item.description, !seeded.isEmpty {
            enrichedDescription = seeded
            return
        }
        enrichedDescription = nil
        if let entity = try? await APIClient.shared.fetchEntity(id: item.mediaEntityId) {
            // F1 R-FX8 — `EntityProse` strips the claims fence first.
            enrichedDescription = EntityProse.firstSection(["## Description", "## Summary"], in: entity.markdownContent)
        }
    }
}
