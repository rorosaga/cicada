import SwiftUI

struct TopicsView: View {
    @Binding var selectedTab: AppTab
    @Environment(GraphViewModel.self) private var graphVM
    @State private var searchText = ""
    @State private var showFilterPopover = false
    @State private var selectedLabels: Set<String> = []
    @State private var showLabelPopover = false
    @State private var selectedEntity: Entity?
    @State private var showUploadOverlay = false

    var body: some View {
        ZStack {
            // No .ignoresSafeArea(): the title bar is darkened at the window level
            // (CicadaApp). Ignoring the safe area here pushed content under the menu
            // bar and stretched the window to full screen height.
            CicadaTheme.background

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
                    // Shared with the Graph tab — one filter, two surfaces.
                    enabledTypes: Binding(
                        get: { graphVM.filter.types },
                        set: { graphVM.filter.types = $0 }
                    ),
                    showFilterPopover: $showFilterPopover,
                    selectedLabels: $selectedLabels,
                    showLabelPopover: $showLabelPopover,
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
                    TopBarControls(
                        selectedTab: $selectedTab,
                        showUploadOverlay: $showUploadOverlay
                    )
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
    @Binding var selectedLabels: Set<String>
    @Binding var showLabelPopover: Bool
    let onSelect: (Entity) -> Void

    // View-local navigation state for the type-grouped list. None of this writes
    // the Graph-shared `enabledTypes` / `graphVM.filter.types`, so it can never
    // desync the Graph tab — it's purely a way to navigate THIS list by type.
    @State private var expandedTypes: Set<EntityType> = []
    @State private var focusedType: EntityType?

    private var filteredEntities: [Entity] {
        var list = graphVM.entities.filter { enabledTypes.contains($0.type) }
        if !selectedLabels.isEmpty {
            list = list.filter { entity in
                !selectedLabels.isDisjoint(with: Set(entity.tags))
            }
        }
        if searchText.isEmpty {
            return list.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        }
        let query = searchText.lowercased()
        // Rank by match quality: exact > starts-with > contains > tag match
        return list
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

    private var allLabels: [(String, Int)] {
        var counts: [String: Int] = [:]
        for entity in graphVM.entities {
            for tag in entity.tags where !tag.isEmpty {
                counts[tag, default: 0] += 1
            }
        }
        return counts
            .map { ($0.key, $0.value) }
            .sorted { $0.0.localizedCaseInsensitiveCompare($1.0) == .orderedAscending }
    }

    /// `filteredEntities` grouped by type, in canonical `selectableCases` order
    /// (person, project, …, media, hub), dropping types with no matches. Computed
    /// once per render so each section header / chip shows the live post-filter,
    /// post-search count. `filteredEntities` is already A→Z (empty search) or
    /// ranked (search), so each group preserves that order.
    private var groupedEntities: [(type: EntityType, entities: [Entity])] {
        let buckets = Dictionary(grouping: filteredEntities, by: \.type)
        return EntityType.selectableCases.compactMap { type in
            guard let entities = buckets[type], !entities.isEmpty else { return nil }
            return (type, entities)
        }
    }

    private var presentTypes: [EntityType] {
        groupedEntities.map(\.type)
    }

    private var isSearching: Bool {
        !searchText.isEmpty
    }

    private func toggle(_ type: EntityType) {
        if expandedTypes.contains(type) {
            expandedTypes.remove(type)
            if focusedType == type { focusedType = nil }
        } else {
            expandedTypes.insert(type)
        }
    }

    /// Tapping a rail chip "focuses" a type: scroll to it + solo-expand it. A
    /// second tap on the focused chip clears focus and collapses everything.
    private func focus(_ type: EntityType, proxy: ScrollViewProxy) {
        if focusedType == type {
            withAnimation(.spring(duration: 0.25)) {
                focusedType = nil
                expandedTypes.remove(type)
            }
            return
        }
        withAnimation(.spring(duration: 0.3)) {
            focusedType = type
            expandedTypes = [type]
            proxy.scrollTo(type, anchor: .top)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(
                title: "Clusters",
                subtitle: "Auto-detected groups of related entities."
            )

            // Search + filter row
            HStack(spacing: CicadaTheme.spacingMD) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textTertiary)

                    TextField("Search clusters...", text: $searchText)
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
                        Text("\(enabledTypes.count)/\(EntityType.selectableCases.count)")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .foregroundStyle(enabledTypes.count == EntityType.selectableCases.count ? CicadaTheme.textSecondary : CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                }
                .buttonStyle(.plain)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .popover(isPresented: $showFilterPopover, arrowEdge: .top) {
                    TopicsFilterPopover(enabledTypes: $enabledTypes)
                }

                Button {
                    showLabelPopover.toggle()
                } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Image(systemName: "tag")
                            .font(.system(size: 12))
                        Text(selectedLabels.isEmpty ? "Labels" : "\(selectedLabels.count)")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .foregroundStyle(selectedLabels.isEmpty ? CicadaTheme.textSecondary : CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                }
                .buttonStyle(.plain)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .popover(isPresented: $showLabelPopover, arrowEdge: .top) {
                    TopicsLabelPopover(
                        allLabels: allLabels,
                        selectedLabels: $selectedLabels
                    )
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingMD)

            // Type-jump rail: quick "focus this type" chips. Hidden while
            // searching (search flattens to a global ranked list). Wrapped by the
            // ScrollViewReader below so chips can scroll the list to a section.
            ScrollViewReader { proxy in
                VStack(alignment: .leading, spacing: 0) {
                    if !isSearching && presentTypes.count > 1 {
                        TypeJumpRail(
                            groups: groupedEntities,
                            focusedType: focusedType,
                            onTap: { focus($0, proxy: proxy) }
                        )
                        .padding(.bottom, CicadaTheme.spacingSM)
                    }

                    // Count + expand/collapse-all control
                    HStack(spacing: CicadaTheme.spacingMD) {
                        Text("\(filteredEntities.count) clusters")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)

                        if !isSearching && presentTypes.count > 1 {
                            let allExpanded = expandedTypes.isSuperset(of: presentTypes)
                            Button {
                                withAnimation(.spring(duration: 0.25)) {
                                    if allExpanded {
                                        expandedTypes.removeAll()
                                    } else {
                                        expandedTypes = Set(presentTypes)
                                    }
                                    focusedType = nil
                                }
                            } label: {
                                HStack(spacing: CicadaTheme.spacingXS) {
                                    Image(systemName: allExpanded ? "chevron.up.chevron.down" : "chevron.down.chevron.up")
                                        .font(.system(size: 9, weight: .semibold))
                                    Text(allExpanded ? "Collapse all" : "Expand all")
                                        .font(.system(size: 11, weight: .medium))
                                }
                                .foregroundStyle(CicadaTheme.textSecondary)
                            }
                            .buttonStyle(.plain)
                        }

                        Spacer()
                    }
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .padding(.bottom, CicadaTheme.spacingSM)

                    // List — flat ranked list while searching, type-grouped
                    // collapsible sections otherwise. Each section header AND each
                    // expanded row is emitted as a *direct* child of the outer
                    // LazyVStack, so every row is its own lazy cell. Expanding a
                    // 600+ entity type (or "Expand all") never materializes more
                    // rows than fit on screen — laziness is genuinely per-row.
                    ScrollView {
                        LazyVStack(spacing: 2) {
                            if isSearching {
                                ForEach(filteredEntities) { entity in
                                    TopicRowListItem(entity: entity, onTap: { onSelect(entity) })
                                }
                            } else {
                                ForEach(groupedEntities, id: \.type) { group in
                                    TypeSectionHeader(
                                        type: group.type,
                                        count: group.entities.count,
                                        isExpanded: expandedTypes.contains(group.type),
                                        onToggle: { withAnimation(.spring(duration: 0.25)) { toggle(group.type) } }
                                    )
                                    .id(group.type)

                                    if expandedTypes.contains(group.type) {
                                        ForEach(group.entities) { entity in
                                            TopicRowListItem(entity: entity, onTap: { onSelect(entity) })
                                                .padding(.leading, CicadaTheme.spacingLG)
                                        }
                                    }
                                }
                            }
                        }
                        .padding(.horizontal, CicadaTheme.spacingXL)
                        .padding(.bottom, CicadaTheme.spacingXL)
                    }
                }
            }
        }
        // Reset view-local navigation state if the underlying set changes shape
        // (e.g. type filter toggled in the popover) so we never point focus at a
        // type that no longer has matches.
        .onChange(of: presentTypes) { _, newTypes in
            let present = Set(newTypes)
            expandedTypes.formIntersection(present)
            if let f = focusedType, !present.contains(f) { focusedType = nil }
        }
    }
}

// MARK: - Type Section (collapsible per-type group)

/// The tappable header for a single entity-type section. Header = color dot +
/// icon + label + live count pill + rotating chevron. This is a standalone lazy
/// cell: the expanded rows are emitted as siblings in the parent LazyVStack (not
/// nested here), so per-row laziness is preserved even for 600+ entity types.
private struct TypeSectionHeader: View {
    let type: EntityType
    let count: Int
    let isExpanded: Bool
    let onToggle: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: onToggle) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Circle()
                    .fill(CicadaTheme.entityColor(for: type))
                    .frame(width: 10, height: 10)

                Image(systemName: type.icon)
                    .font(.system(size: 12))
                    .foregroundStyle(CicadaTheme.entityColor(for: type))
                    .frame(width: 16)

                Text(type.label)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)

                Text("\(count)")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(CicadaTheme.entityColor(for: type))
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background(CicadaTheme.entityColor(for: type).opacity(0.12))
                    .clipShape(Capsule())

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
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

// MARK: - Type Jump Rail

/// Horizontal strip of type chips under the search row. Tapping a chip focuses
/// that type (scroll + solo-expand). Purely view-local — never touches the
/// Graph-shared filter. Only present types appear (count-0 types are absent).
private struct TypeJumpRail: View {
    let groups: [(type: EntityType, entities: [Entity])]
    let focusedType: EntityType?
    let onTap: (EntityType) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ForEach(groups, id: \.type) { group in
                    TypeChip(
                        type: group.type,
                        count: group.entities.count,
                        isFocused: focusedType == group.type,
                        onTap: { onTap(group.type) }
                    )
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
        }
    }
}

private struct TypeChip: View {
    let type: EntityType
    let count: Int
    let isFocused: Bool
    let onTap: () -> Void
    @State private var isHovered = false

    var body: some View {
        let color = CicadaTheme.entityColor(for: type)
        Button(action: onTap) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Circle()
                    .fill(color)
                    .frame(width: 7, height: 7)

                Text(type.label)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(isFocused ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)

                Text("\(count)")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, 5)
            .background(
                Capsule()
                    .fill(isFocused ? color.opacity(0.15) : (isHovered ? CicadaTheme.surfaceHover : .clear))
            )
            .overlay(
                Capsule()
                    .stroke(isFocused ? color.opacity(0.6) : CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
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

            ForEach(EntityType.selectableCases) { type in
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

private struct TopicsLabelPopover: View {
    let allLabels: [(String, Int)]
    @Binding var selectedLabels: Set<String>
    @State private var labelSearch: String = ""

    /// Cap on how many label rows are materialized at once. Even with the
    /// LazyVStack below, bounding the rendered set keeps an empty/short search
    /// from building thousands of rows when the popover opens (the freeze).
    private static let renderCap = 100

    private var matchingLabels: [(String, Int)] {
        let query = labelSearch.trimmingCharacters(in: .whitespaces).lowercased()
        if query.isEmpty { return allLabels }
        return allLabels.filter { $0.0.lowercased().contains(query) }
    }

    private var visibleLabels: [(String, Int)] {
        Array(matchingLabels.prefix(Self.renderCap))
    }

    private var hiddenCount: Int {
        max(0, matchingLabels.count - visibleLabels.count)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("FILTER BY LABEL")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Search labels…", text: $labelSearch)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, 6)
            .background(CicadaTheme.surfaceHover)
            .clipShape(RoundedRectangle(cornerRadius: 6))

            if allLabels.isEmpty {
                Text("No labels yet")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(visibleLabels, id: \.0) { label, count in
                            Button {
                                if selectedLabels.contains(label) {
                                    selectedLabels.remove(label)
                                } else {
                                    selectedLabels.insert(label)
                                }
                            } label: {
                                HStack(spacing: CicadaTheme.spacingSM) {
                                    Image(systemName: selectedLabels.contains(label) ? "checkmark.circle.fill" : "circle")
                                        .font(.system(size: 13))
                                        .foregroundStyle(selectedLabels.contains(label) ? CicadaTheme.accent : CicadaTheme.textTertiary)

                                    Text(label)
                                        .font(.system(size: 12))
                                        .foregroundStyle(selectedLabels.contains(label) ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                                        .lineLimit(1)

                                    Spacer()

                                    Text("\(count)")
                                        .font(.system(size: 10, design: .monospaced))
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                }
                                .padding(.horizontal, 4)
                                .padding(.vertical, 3)
                            }
                            .buttonStyle(.plain)
                        }

                        if hiddenCount > 0 {
                            Text("+\(hiddenCount) more — refine search")
                                .font(.system(size: 10))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .padding(.horizontal, 4)
                                .padding(.vertical, 4)
                        }
                    }
                }
                .frame(maxHeight: 260)
            }

            if !selectedLabels.isEmpty {
                Divider().background(CicadaTheme.border)
                Button {
                    selectedLabels.removeAll()
                } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Image(systemName: "xmark.circle")
                            .font(.system(size: 11))
                        Text("Clear all")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.vertical, 4)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 240)
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
                        Text("Clusters")
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

            // Detail card — EntityDetailCard already has its own internal
            // ScrollView, so wrapping it in a second one broke the width
            // proposal chain for long markdown bodies (the "zoomed in" bug).
            EntityDetailCard(entity: displayEntity, showsCloseButton: false)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .padding(CicadaTheme.spacingXL)
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
