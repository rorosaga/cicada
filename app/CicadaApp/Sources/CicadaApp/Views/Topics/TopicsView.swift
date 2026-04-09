import SwiftUI

struct TopicsView: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var searchText = ""
    @State private var showFilterPopover = false
    @State private var enabledTypes: Set<EntityType> = Set(EntityType.allCases)
    @State private var selectedEntity: Entity?
    @State private var showUploadOverlay = false

    var body: some View {
        ZStack {
            CicadaTheme.background.ignoresSafeArea()

            if let entity = selectedEntity {
                // Detail view
                TopicDetailView(entity: entity, onBack: {
                    withAnimation(.spring(duration: 0.3)) {
                        selectedEntity = nil
                    }
                })
                .transition(.asymmetric(
                    insertion: .move(edge: .trailing).combined(with: .opacity),
                    removal: .move(edge: .trailing).combined(with: .opacity)
                ))
            } else {
                // List view
                TopicsListView(
                    searchText: $searchText,
                    enabledTypes: $enabledTypes,
                    showFilterPopover: $showFilterPopover,
                    onSelect: { entity in
                        withAnimation(.spring(duration: 0.3)) {
                            selectedEntity = entity
                        }
                    }
                )
                .transition(.asymmetric(
                    insertion: .move(edge: .leading).combined(with: .opacity),
                    removal: .move(edge: .leading).combined(with: .opacity)
                ))
            }

            // Top-right controls
            VStack {
                HStack {
                    Spacer()
                    TopBarControls(showUploadOverlay: $showUploadOverlay)
                        .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }

            // Upload overlay
            if showUploadOverlay {
                UploadOverlay(isPresented: $showUploadOverlay)
                    .transition(.opacity)
            }
        }
    }
}

// MARK: - Topics List View

private struct TopicsListView: View {
    @Environment(GraphViewModel.self) private var graphVM
    @Binding var searchText: String
    @Binding var enabledTypes: Set<EntityType>
    @Binding var showFilterPopover: Bool
    let onSelect: (Entity) -> Void

    private var filteredEntities: [Entity] {
        let typeFiltered = graphVM.entities.filter { enabledTypes.contains($0.type) }
        if searchText.isEmpty {
            return typeFiltered.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        }
        let query = searchText.lowercased()
        // Rank by match quality: exact > starts-with > contains > tag match
        return typeFiltered
            .compactMap { entity -> (Entity, Int)? in
                let name = entity.name.lowercased()
                let tags = entity.tags.map { $0.lowercased() }
                var score = 0
                if name == query { score = 100 }
                else if name.hasPrefix(query) { score = 80 }
                else if name.contains(query) { score = 60 }
                else if tags.contains(where: { $0.contains(query) }) { score = 40 }
                else if entity.markdownContent.lowercased().contains(query) { score = 20 }
                return score > 0 ? (entity, score) : nil
            }
            .sorted { $0.1 > $1.1 }
            .map { $0.0 }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header with title + search + filter
            HStack(spacing: CicadaTheme.spacingMD) {
                Text("Topics")
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)

                Spacer()
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.top, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingMD)

            // Search + filter row
            HStack(spacing: CicadaTheme.spacingMD) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textTertiary)

                    TextField("Search topics...", text: $searchText)
                        .textFieldStyle(.plain)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)

                    if !searchText.isEmpty {
                        Button {
                            searchText = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.system(size: 11))
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.vertical, CicadaTheme.spacingSM)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)

                Button {
                    showFilterPopover.toggle()
                } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                            .font(.system(size: 12))
                        Text("\(enabledTypes.count)/\(EntityType.allCases.count)")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .foregroundStyle(enabledTypes.count == EntityType.allCases.count ? CicadaTheme.textSecondary : CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                }
                .buttonStyle(.plain)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .popover(isPresented: $showFilterPopover, arrowEdge: .top) {
                    TopicsFilterPopover(enabledTypes: $enabledTypes)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingMD)

            // Count
            Text("\(filteredEntities.count) topics")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingSM)

            // List
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(filteredEntities) { entity in
                        TopicRowListItem(entity: entity, onTap: { onSelect(entity) })
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
    }
}

private struct TopicsFilterPopover: View {
    @Binding var enabledTypes: Set<EntityType>

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("FILTER BY TYPE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityType.allCases) { type in
                Button {
                    if enabledTypes.contains(type) {
                        enabledTypes.remove(type)
                    } else {
                        enabledTypes.insert(type)
                    }
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: enabledTypes.contains(type) ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 13))
                            .foregroundStyle(enabledTypes.contains(type) ? CicadaTheme.entityColor(for: type) : CicadaTheme.textTertiary)

                        Circle()
                            .fill(CicadaTheme.entityColor(for: type))
                            .frame(width: 8, height: 8)

                        Text(type.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(enabledTypes.contains(type) ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 200)
        .background(CicadaTheme.surface)
    }
}

// MARK: - Topic Row

private struct TopicRowListItem: View {
    let entity: Entity
    let onTap: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Circle()
                    .fill(CicadaTheme.entityColor(for: entity.type))
                    .frame(width: 10, height: 10)

                Text(entity.name)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)

                Text(entity.type.label)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(CicadaTheme.entityColor(for: entity.type).opacity(0.12))
                    .clipShape(Capsule())

                Spacer()

                Text(String(format: "%.0f%%", entity.confidence * 100))
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)

                Image(systemName: "chevron.right")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isHovered ? CicadaTheme.surfaceHover : .clear)
            )
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
    }
}

// MARK: - Topic Detail View

private struct TopicDetailView: View {
    let entity: Entity
    let onBack: () -> Void
    @Environment(GraphViewModel.self) private var graphVM
    @State private var fullEntity: Entity?

    private var displayEntity: Entity {
        fullEntity ?? entity
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Back button
            HStack {
                Button {
                    onBack()
                } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 12, weight: .medium))
                        Text("Topics")
                            .font(.system(size: 12, weight: .medium))
                    }
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                }
                .buttonStyle(.plain)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)

                Spacer()
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.top, CicadaTheme.spacingXL)

            // Detail card
            ScrollView {
                EntityDetailCard(entity: displayEntity)
                    .frame(maxWidth: 640)
                    .padding(CicadaTheme.spacingXL)
                    .frame(maxWidth: .infinity)
            }
        }
        .task(id: entity.id) {
            do {
                fullEntity = try await APIClient.shared.fetchEntity(id: entity.id)
            } catch {
                print("Failed to load full entity: \(error)")
            }
        }
    }
}
