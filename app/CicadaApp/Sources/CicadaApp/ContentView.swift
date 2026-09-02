import SwiftUI
import AppKit

struct ContentView: View {
    @State private var selectedTab: AppTab = .graph
    /// Reopen where the user left off. Always read back through
    /// `AppTab.restored(from:)`: this string can name a tab that no longer
    /// exists (G68 retired five of them).
    @AppStorage("cicada.selectedTab") private var selectedTabRaw = AppTab.graph.rawValue
    @State private var columnVisibility: NavigationSplitViewVisibility = .doubleColumn
    // First-launch onboarding: show the Connect guide once, then it lives in
    // Settings → Agents (⌘,). Stored flag so reinstalls of the same Mac user
    // don't re-trigger it on every launch.
    @AppStorage("cicada.hasSeenConnectGuide") private var hasSeenConnectGuide = false
    @State private var showOnboarding = false
    // ⌘K Ask panel (G52, spec §5.9).
    @State private var showAskPanel = false

    // Theme: mirrors the persisted mode into `CicadaTheme.mode` (see
    // Theme/CicadaTheme.swift) on every render, before Sidebar/detail are
    // constructed below. @AppStorage guarantees SwiftUI re-invokes this body
    // whenever the key changes, from anywhere (e.g. the toggle button in
    // SidebarView).
    @AppStorage("cicada.colorScheme") private var colorSchemeRaw: String = AppColorScheme.dark.rawValue

    @Environment(GraphViewModel.self) private var graphVM
    @Environment(InboxViewModel.self) private var inboxVM
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(ConnectionsViewModel.self) private var connectionsVM

    var body: some View {
        // `ViewBuilder` only accepts declarations/`let _ = ...` statements
        // ahead of the returned View expression, not arbitrary statements —
        // hence the `let _ =` wrapper around this side effect.
        let _ = { CicadaTheme.mode = AppColorScheme(rawValue: colorSchemeRaw) ?? .dark }()

        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView(
                selectedTab: $selectedTab,
                inboxCount: inboxVM.pendingCount,
                isSleeping: store.status.value?.sleep.status == "running" || sleepVM.isRunning,
                needsAttention: connectionsVM.needsAttention,
                onOpenSettings: openSettings
            )
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 260)
        } detail: {
            detailContent
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(CicadaTheme.background)
                // A rolled-back mutation (or a refresh that failed with
                // nothing on screen) posts `store.toast`; show it at the
                // bottom of whatever page is open (§5.4).
                .overlay(alignment: .bottom) { toastBanner }
        }
        // Most CicadaTheme.xxx tokens are plain static reads, not
        // @Environment-tracked, so SwiftUI's dependency tracker won't know to
        // re-invoke every descendant's `body` on a theme flip. Keying the
        // whole sidebar/detail subtree on the raw mode string forces a clean
        // rebuild (fresh body calls everywhere) whenever it changes, while
        // `selectedTab`/`columnVisibility` above stay intact since they live
        // outside this subtree.
        .id(colorSchemeRaw)
        .navigationSplitViewStyle(.prominentDetail)
        // No `.task { load() }` here: `graphVM`/`inboxVM` are thin
        // projections over `Store.graph`/`Store.inbox` (§5.5). The Store
        // hydrates both from disk and refreshes them itself
        // (`store.bootstrap()`, wired in `CicadaApp`'s `.onAppear`); the VMs
        // pick up every subsequent change reactively (`GraphViewModel`'s
        // `observeStore()`; `InboxViewModel.items` reads the snapshot
        // directly), so there's nothing left for ContentView to kick off.
        .onAppear {
            selectedTab = AppTab.restored(from: selectedTabRaw)
            if !hasSeenConnectGuide { showOnboarding = true }
        }
        .onChange(of: selectedTab) { _, newValue in
            selectedTabRaw = newValue.rawValue
            // Bug 3 / G108 — a different tab drops the entity card's stale
            // "go deeper" trail (the currently-open card, if any, is left
            // alone; only its click-through history is cleared).
            graphVM.resetNavigationHistory()
        }
        .sheet(isPresented: $showOnboarding) {
            ConnectView(isOnboarding: true) {
                hasSeenConnectGuide = true
                showOnboarding = false
            }
            .frame(width: 780, height: 640)
        }
        // ⌘K opens the Ask panel (G52) from anywhere in the app — a hidden
        // button is the standard SwiftUI way to attach a global keyboard
        // shortcut that isn't tied to a visible control.
        .background {
            Button("") { showAskPanel = true }
                .keyboardShortcut("k", modifiers: .command)
                .buttonStyle(.cicadaPlain)
                .frame(width: 0, height: 0)
                .opacity(0)
        }
        .sheet(isPresented: $showAskPanel) {
            AskPanel { entityId in
                withAnimation(.spring(duration: 0.25)) { selectedTab = .graph }
                graphVM.selectEntity(id: entityId)
                showAskPanel = false
            }
        }
    }

    /// Transient capsule for `store.toast`, auto-clearing after 4 s. Keyed on
    /// the message so a second toast restarts the timer instead of inheriting
    /// the first one's remaining time.
    @ViewBuilder
    private var toastBanner: some View {
        if let toast = store.toast {
            Text(toast)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(.horizontal, 16)
                .padding(.vertical, 9)
                .background(
                    Capsule().fill(CicadaTheme.surface)
                        .overlay(Capsule().stroke(CicadaTheme.border, lineWidth: 1))
                )
                .shadow(color: .black.opacity(0.25), radius: 10, y: 3)
                .padding(.bottom, 22)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .task(id: toast) {
                    try? await Task.sleep(for: .seconds(4))
                    guard !Task.isCancelled else { return }
                    store.toast = nil
                }
        }
    }

    /// The graph view is never torn down by a tab switch (owner, 2026-09-03:
    /// "if I zoom in and change tab and go back, it should still be zoomed in
    /// to where I was"). A `switch` here rebuilt `GraphView`'s `WKWebView` on
    /// every return — a cold re-layout, the zoom reset, and the G109 "explosion
    /// on return". The graph stays mounted underneath, hidden and inert while
    /// another tab is showing; the other tabs are built on top as before.
    @ViewBuilder
    private var detailContent: some View {
        ZStack {
            GraphContainerView(selectedTab: $selectedTab, showAskPanel: $showAskPanel)
                .opacity(selectedTab == .graph ? 1 : 0)
                .allowsHitTesting(selectedTab == .graph)
                .accessibilityHidden(selectedTab != .graph)
            if selectedTab != .graph {
                otherTabContent
            }
        }
    }

    @ViewBuilder
    private var otherTabContent: some View {
        switch selectedTab {
        case .graph:
            EmptyView()
        case .clusters:
            TopicsView(selectedTab: $selectedTab)
        case .feed:
            FeedView(selectedTab: $selectedTab)
        case .sleep:
            SleepView(selectedTab: $selectedTab)
        case .inbox:
            InboxListView()
        case .activity:
            // An entity chip on a conversation row navigates the same way an
            // Ask citation does: select in the graph, then show the graph.
            ActivityView { entityId in
                withAnimation(.spring(duration: 0.25)) { selectedTab = .graph }
                graphVM.selectEntity(id: entityId)
            }
        }
    }

    /// SwiftUI has no API for opening the `Settings` scene programmatically,
    /// so the footer gear posts the same AppKit action ⌘, does.
    private func openSettings() {
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }
}

// MARK: - Graph Container with Zoom Controls

struct GraphContainerView: View {
    @Binding var selectedTab: AppTab
    @Binding var showAskPanel: Bool
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(BanksViewModel.self) private var banksVM
    @State private var showUploadOverlay = false

    var body: some View {
        ZStack {
            GraphView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            // Top-right: Ask + Sleep + Upload + Help buttons
            VStack {
                HStack {
                    Spacer()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        AskButton(showAskPanel: $showAskPanel)
                        TopBarControls(
                            selectedTab: $selectedTab,
                            showUploadOverlay: $showUploadOverlay
                        )
                    }
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }

            // Top-left: memory-bank ("Projects") switcher (M6) above the observer
            // "who believes what" filter (§3a). The filter bar only renders once
            // the graph carries observer data, otherwise EmptyView.
            VStack {
                HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        BankSwitcher(banksVM: banksVM)
                        ObserverFilterBar()
                    }
                    .padding(CicadaTheme.spacingLG)
                    Spacer()
                }
                Spacer()
            }

            // Bottom-left: context legend (§2a). EmptyView until contexts land.
            VStack {
                Spacer()
                HStack {
                    ContextLegend()
                        .padding(CicadaTheme.spacingLG)
                    Spacer()
                }
            }

            // Bottom-right: Filter + Zoom controls
            VStack {
                Spacer()
                HStack {
                    Spacer()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        FilterButton()
                        ZoomControls()
                    }
                    .padding(CicadaTheme.spacingLG)
                }
            }

            // Node click → floating markdown-preview window over the graph.
            // Dimmed backdrop dismisses on tap; the card itself opens on the
            // raw Source view (what the user asked to see on click).
            if let entity = graphVM.selectedEntity {
                Color.black.opacity(0.45)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { graphVM.clearSelection() }
                    .transition(.opacity)

                EntityDetailCard(entity: entity, defaultRaw: false)
                    // One card identity PER ENTITY. Without this, following a
                    // wikilink A → B reuses A's @State — A's claims, repos,
                    // fact sources and selected tab render under B's name.
                    .id(entity.id)
                    .frame(maxWidth: 620, maxHeight: 680)
                    .padding(CicadaTheme.spacingXL)
                    .transition(.scale(scale: 0.97).combined(with: .opacity))
            }

            // Upload overlay
            if showUploadOverlay {
                UploadOverlay(isPresented: $showUploadOverlay)
                    .transition(.opacity)
            }
        }
        .animation(.spring(duration: 0.3), value: graphVM.selectedEntity?.id)
        .animation(.spring(duration: 0.3), value: showUploadOverlay)
    }
}

// MARK: - Filter Button

struct FilterButton: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var isHovered = false

    var body: some View {
        Button {
            graphVM.showFilterPopover.toggle()
        } label: {
            Image(systemName: "line.3.horizontal.decrease.circle")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(allEnabled ? (isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary) : CicadaTheme.accent)
                .frame(width: 36, height: 32)
        }
        .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .onHover { isHovered = $0 }
        .popover(isPresented: Binding(
            get: { graphVM.showFilterPopover },
            set: { graphVM.showFilterPopover = $0 }
        ), arrowEdge: .top) {
            FilterPopoverContent()
        }
    }

    private var allEnabled: Bool {
        graphVM.filter.allTypesSelected
    }
}

struct FilterPopoverContent: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("FILTER CATEGORIES")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityType.selectableCases) { type in
                Button {
                    graphVM.toggleType(type)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.filter.types.contains(type) ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 14))
                            .foregroundStyle(graphVM.filter.types.contains(type) ? CicadaTheme.entityColor(for: type) : CicadaTheme.textTertiary)

                        Text(type.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(graphVM.filter.types.contains(type) ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .buttonStyle(.cicadaPlain)
            }

            Divider()
                .background(CicadaTheme.border)
                .padding(.vertical, CicadaTheme.spacingXS)

            Text("STATUS")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityStatus.allCases, id: \.self) { status in
                Button {
                    graphVM.filter.toggleStatus(status)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.filter.statuses.contains(status) ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 14))
                            .foregroundStyle(graphVM.filter.statuses.contains(status) ? CicadaTheme.accent : CicadaTheme.textTertiary)

                        Text(status.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(graphVM.filter.statuses.contains(status) ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .buttonStyle(.cicadaPlain)
            }

            Divider()
                .background(CicadaTheme.border)
                .padding(.vertical, CicadaTheme.spacingXS)

            HStack {
                Text("MIN CONFIDENCE")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                Spacer()
                Text(String(format: "%.0f%%", graphVM.filter.minConfidence * 100))
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }

            Slider(
                value: Binding(
                    get: { graphVM.filter.minConfidence },
                    set: { graphVM.filter.minConfidence = $0 }
                ),
                in: 0...1
            )
            .controlSize(.small)

            Divider()
            Toggle("Show logos", isOn: Binding(
                get: { graphVM.filter.showLogos },
                set: { newValue in
                    graphVM.filter.showLogos = newValue
                    if newValue { Task { await graphVM.pushVisibleLogos() } }
                }
            ))
            .toggleStyle(.switch)
            .accessibilityLabel("Show entity logos on graph nodes")
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 220)
        .background(CicadaTheme.surface)
    }
}

// MARK: - Zoom Controls

struct ZoomControls: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HStack(spacing: 1) {
            ZoomButton(icon: "minus", action: { graphVM.zoomAction = .out })
            Divider().frame(height: 20).background(CicadaTheme.border)
            ZoomButton(icon: "plus", action: { graphVM.zoomAction = .zoomIn })
            Divider().frame(height: 20).background(CicadaTheme.border)
            ZoomButton(icon: "arrow.down.left.and.arrow.up.right", action: { graphVM.zoomAction = .fit })
            Divider().frame(height: 20).background(CicadaTheme.border)
            // Pan-mode toggle — the click-based twin of holding Shift (owner
            // request 2026-09-03): while on, hovering never highlights and a
            // press anywhere pans. Both routes drive the same JS mode; the
            // button stays lit until pressed again.
            ZoomButton(icon: "arrow.up.and.down.and.arrow.left.and.right",
                       isActive: graphVM.panModeOn,
                       action: { graphVM.panModeOn.toggle() })
                .help(graphVM.panModeOn ? "Pan mode on — click to return to normal (or just hold Shift)" : "Pan mode — drag anywhere to move the graph (or hold Shift)")
        }
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
    }
}

// MARK: - Ask Button (G52)

/// Toolbar entry point for the ⌘K Ask panel — the keyboard shortcut works
/// from anywhere in `ContentView`, this just gives it a discoverable button
/// alongside Sleep/Upload/Help.
struct AskButton: View {
    @Binding var showAskPanel: Bool
    @State private var isHovered = false

    var body: some View {
        Button {
            showAskPanel = true
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "sparkle.magnifyingglass")
                    .font(.system(size: 12))
                Text("Ask")
                    .font(.system(size: 12, weight: .medium))
            }
            .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.accent)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
        }
        .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .onHover { isHovered = $0 }
        .help("Ask your memory (⌘K)")
    }
}

private struct ZoomButton: View {
    let icon: String
    var isActive = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(isActive ? CicadaTheme.accent : (isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary))
                .frame(width: 36, height: 32)
                .background(isActive ? CicadaTheme.accent.opacity(0.18) : (isHovered ? CicadaTheme.surfaceHover : .clear))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}
