import SwiftUI
import AppKit

struct ContentView: View {
    @State private var selectedTab: AppTab = .graph
    /// Reopen where the user left off. Always read back through
    /// `AppTab.restored(from:)`: this string can name a tab that no longer
    /// exists (G68 retired five of them).
    @AppStorage("cicada.selectedTab") private var selectedTabRaw = AppTab.graph.rawValue
    @State private var columnVisibility: NavigationSplitViewVisibility = .doubleColumn
    // G117 — the four-step first-run sheet (identity → engine → one capture
    // channel → first Sleep), gated per-bank (`OnboardingState`, R5) rather
    // than the old machine-global `hasSeenConnectGuide` flag: switching to a
    // fresh bank (or the demo bank, G117 Task 5) must show the tour again
    // even on a Mac that already onboarded a different bank. The old
    // single-step `ConnectView(isOnboarding: true)` sheet this replaces is
    // still reachable — it's the same view Settings → Agents opens, and its
    // "MCP item" content now also lives inside the embedded
    // `IntegrationsView`'s `.chatAndAgents` category (`harnessRows`), so
    // nothing it offered is lost, only the old single-step framing.
    @State private var showFirstRun = false
    // ⌘K Ask panel (G52, spec §5.9).
    @State private var showAskPanel = false

    @Environment(GraphViewModel.self) private var graphVM
    @Environment(InboxViewModel.self) private var inboxVM
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    /// G126 R9 — consumes a Settings → Integrations "Import in Feed →"
    /// hand-off by switching the sidebar's own selection.
    @Environment(AppRouter.self) private var router

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView(
                selectedTab: $selectedTab,
                inboxCount: inboxVM.pendingCount,
                isSleeping: store.status.value?.sleep.status == "running" || sleepVM.isRunning,
                needsAttention: connectionsVM.needsAttention
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
        // No `.id(colorSchemeRaw)` here any more. Keying this subtree on the
        // mode string used to be what repainted it, because the tokens were
        // static reads SwiftUI could not track — but it rebuilt the whole
        // sidebar/detail tree on every flip, which tears down and reloads the
        // graph's WKWebView and loses its layout. `CicadaTheme.mode` is now
        // backed by an `@Observable` store, so each view that reads a token
        // subscribes to the mode itself and repaints on its own.
        .navigationSplitViewStyle(.prominentDetail)
        // No `.task { load() }` here: `graphVM`/`inboxVM` are thin
        // projections over `Store.graph`/`Store.inbox` (§5.5). The Store
        // hydrates both from disk and refreshes them itself
        // (`store.bootstrap()`, wired in `CicadaApp`'s `.onAppear`); the VMs
        // pick up every subsequent change reactively (`GraphViewModel`'s
        // `observeStore()`; `InboxViewModel.items` reads the snapshot
        // directly), so there's nothing left for ContentView to kick off.
        // R6 — still reads Store snapshots only, no extra fetch. But it can no
        // longer decide on `.onAppear` alone: `store.bootstrap()` is async, so
        // at this point `store.bank` is usually still the placeholder
        // `"default"` and `store.graph` is unloaded. Deciding there asked
        // `isOnboarded` about the wrong bank and read "not loaded" as "empty",
        // which put the sheet on top of an onboarded bank's real data on every
        // cold launch. `FirstRunGate` holds the rule (unknown is never empty);
        // this view just re-asks it whenever an input lands.
        .onAppear {
            selectedTab = AppTab.restored(from: selectedTabRaw)
            evaluateFirstRun()
        }
        // The roster resolving the active bank, and the graph snapshot landing
        // (from the on-disk cache or the network), are the two events that turn
        // an unknown input into a known one.
        .onChange(of: store.bank) { _, _ in evaluateFirstRun() }
        .onChange(of: store.banks.loadedAt) { _, _ in evaluateFirstRun() }
        .onChange(of: store.graph.loadedAt) { _, _ in evaluateFirstRun() }
        .onChange(of: selectedTab) { _, newValue in
            selectedTabRaw = newValue.rawValue
            // Bug 3 / G108 — a different tab drops the entity card's stale
            // "go deeper" trail (the currently-open card, if any, is left
            // alone; only its click-through history is cleared).
            graphVM.resetNavigationHistory()
        }
        .sheet(isPresented: $showFirstRun) {
            FirstRunSheet(bank: store.bank) { showFirstRun = false }
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
        // G126 R9 — Integrations lives in the `Settings{}` scene, a
        // separate window from this one, so it cannot just flip
        // `selectedTab` itself; it stages a tab on the shared `AppRouter`
        // instead and this view is the one that actually switches.
        .onChange(of: router.pendingTab) { _, newTab in
            guard let newTab else { return }
            withAnimation(.spring(duration: 0.25)) { selectedTab = newTab }
            router.pendingTab = nil
        }
        // G117 — Settings → General's "Run setup again" hand-off. Settings
        // is a separate window/scene (same reason `pendingTab` exists above
        // for G126 R9's Feed hand-off) so it cannot flip `showFirstRun`
        // directly; it stages this flag on the shared `AppRouter` instead.
        .onChange(of: router.pendingFirstRun) { _, isPending in
            guard isPending else { return }
            showFirstRun = true
            router.pendingFirstRun = false
        }
        .sheet(isPresented: $showAskPanel) {
            // G123: a citation lands ON its node — the graph zooms to that
            // node's neighbourhood, not just opens its card. An answer's
            // citation is a claim about where something sits in the graph, and
            // showing the card while the viewport stays wherever it was left
            // makes the reader hunt for it.
            AskPanel { entityId in
                withAnimation(.spring(duration: 0.25)) { selectedTab = .graph }
                graphVM.revealEntity(id: entityId)
                showAskPanel = false
            }
        }
    }

    /// G117 — the one place the first-run sheet is raised automatically.
    /// `store.banks.value != nil` is the honest "the bank is resolved" signal:
    /// `Store` has no `hydrated` flag, and `hydrate()` sets `bank` from the
    /// roster it just read (`Store.swift`, `roster.value.active`), so the
    /// roster snapshot having a value is exactly the moment `store.bank` stops
    /// being the placeholder. A hydrated on-disk cache counts as loaded for
    /// both roster and graph — rendering the first frame from disk is the
    /// point of that cache. Never lowers `showFirstRun`: dismissal belongs to
    /// `FirstRunSheet`'s own completion and to the `pendingFirstRun` hand-off,
    /// and a re-evaluation firing under an open sheet must not close it.
    private func evaluateFirstRun() {
        guard !showFirstRun else { return }
        if FirstRunGate.shouldShow(
            bankResolved: store.banks.value != nil,
            isOnboarded: OnboardingState.isOnboarded(bank: store.bank),
            graphLoaded: store.graph.value != nil,
            graphIsEmpty: store.graph.value?.nodes.isEmpty ?? false
        ) {
            showFirstRun = true
        }
    }

    /// Transient capsule for `store.toast`, auto-clearing after 4 s. Keyed on
    /// the message so a second toast restarts the timer instead of inheriting
    /// the first one's remaining time.
    @ViewBuilder
    private var toastBanner: some View {
        if let toast = store.toast {
            Text(toast)
                .font(CicadaTheme.font(size: 12, weight: .medium))
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
            // An entity chip in the consolidation history's expanded detail
            // navigates the same way an Ask citation (or a Sources
            // conversation row, below) does: land on the node, then show
            // its card.
            SleepView(selectedTab: $selectedTab) { entityId in
                withAnimation(.spring(duration: 0.25)) { selectedTab = .graph }
                graphVM.revealEntity(id: entityId)
            }
        case .inbox:
            InboxListView()
        case .sources:
            // An entity chip on a source page's conversation row navigates the
            // same way an Ask citation does (G123): land on the node, then
            // show its card.
            SourcesPageView { entityId in
                withAnimation(.spring(duration: 0.25)) { selectedTab = .graph }
                graphVM.revealEntity(id: entityId)
            }
        }
    }
}

// MARK: - Graph Container with Zoom Controls

struct GraphContainerView: View {
    @Binding var selectedTab: AppTab
    @Binding var showAskPanel: Bool
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(BanksViewModel.self) private var banksVM

    var body: some View {
        ZStack {
            GraphView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            // G117 — a fresh bank's graph used to be a literal blank canvas
            // (the row's own opening evidence). `isLoading` gates on the
            // Store's cache being empty AND a fetch in flight, so this never
            // flashes on top of the instant on-disk-cache hydrate that
            // `Store` already does — only a bank that is genuinely empty
            // shows it.
            if !graphVM.isLoading && graphVM.nodes.isEmpty {
                EmptyStateView(
                    title: "Nothing here yet",
                    message: Copy.emptyGraphMessage,
                    actionLabel: "Open Integrations",
                    settingsSection: .integrations
                )
            }

            // Top-right: Ask + Help (Track P: the audit removed Sleep/Upload —
            // a cycle starts on the Sleep page, an import behind the Feed's +)
            VStack {
                HStack {
                    Spacer()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        AskButton(showAskPanel: $showAskPanel)
                        TopBarControls(
                            selectedTab: $selectedTab,
                            showUploadOverlay: .constant(false)
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
                        HStack(spacing: CicadaTheme.spacingSM) {
                            BankSwitcher(banksVM: banksVM)
                            GraphSearchField()
                        }
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
        }
        .animation(.spring(duration: 0.3), value: graphVM.selectedEntity?.id)
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
                .font(CicadaTheme.font(size: 13, weight: .medium))
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
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityType.selectableCases) { type in
                Button {
                    graphVM.toggleType(type)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.filter.types.contains(type) ? "checkmark.circle.fill" : "circle")
                            .font(CicadaTheme.font(size: 14))
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
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityStatus.allCases, id: \.self) { status in
                Button {
                    graphVM.filter.toggleStatus(status)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.filter.statuses.contains(status) ? "checkmark.circle.fill" : "circle")
                            .font(CicadaTheme.font(size: 14))
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
                    .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                Spacer()
                Text(String(format: "%.0f%%", graphVM.filter.minConfidence * 100))
                    .font(CicadaTheme.font(size: 10, design: .monospaced))
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
                    .font(CicadaTheme.font(size: 12))
                Text("Ask")
                    .font(CicadaTheme.font(size: 12, weight: .medium))
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
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(isActive ? CicadaTheme.accent : (isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary))
                .frame(width: 36, height: 32)
                .background(isActive ? CicadaTheme.accent.opacity(0.18) : (isHovered ? CicadaTheme.surfaceHover : .clear))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}

// MARK: - Graph node search (G123)

/// A small typeahead over the graph snapshot: ⌘F focuses it, ↑/↓ move, ⏎
/// zooms to the node's neighbourhood and opens its card, Esc clears. Matching
/// is local (`GraphViewModel.searchMatches`) — no request per keystroke.
struct GraphSearchField: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var query = ""
    @State private var highlighted = 0
    @FocusState private var focused: Bool

    private var matches: [GraphNode] { graphVM.searchMatches(query) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "magnifyingglass")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Find a node", text: $query)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.font(size: 12))
                    .focused($focused)
                    .frame(width: 160)
                    .onSubmit { pick(highlighted) }
                    .onKeyPress(.downArrow) { move(1); return .handled }
                    .onKeyPress(.upArrow) { move(-1); return .handled }
                    .onKeyPress(.escape) { clear(); return .handled }
                    .onChange(of: query) { _, _ in highlighted = 0 }
                if !query.isEmpty {
                    Button { clear() } label: {
                        Image(systemName: "xmark.circle.fill").font(CicadaTheme.font(size: 11))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, 6)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
            // ⌘F from anywhere on the page focuses the field.
            .background(
                Button("") { focused = true }
                    .keyboardShortcut("f", modifiers: .command)
                    .opacity(0)
                    .frame(width: 0, height: 0)
            )

            if focused, !query.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    if matches.isEmpty {
                        Text("No node matches")
                            .font(CicadaTheme.font(size: 12))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.horizontal, CicadaTheme.spacingSM)
                            .padding(.vertical, 6)
                    }
                    ForEach(Array(matches.enumerated()), id: \.element.id) { index, node in
                        HStack(spacing: CicadaTheme.spacingXS) {
                            Circle().fill(CicadaTheme.entityColor(for: node.type)).frame(width: 7, height: 7)
                            Text(node.name).font(CicadaTheme.font(size: 12)).lineLimit(1)
                            Spacer(minLength: 0)
                            Text(node.type.rawValue)
                                .font(CicadaTheme.font(size: 10))
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        .padding(.horizontal, CicadaTheme.spacingSM)
                        .padding(.vertical, 5)
                        .background(index == highlighted ? CicadaTheme.surfaceHover : .clear)
                        .contentShape(Rectangle())
                        .onTapGesture { pick(index) }
                    }
                }
                .frame(width: 220)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .padding(.top, 4)
            }
        }
    }

    private func move(_ delta: Int) {
        let count = matches.count
        guard count > 0 else { return }
        highlighted = (highlighted + delta + count) % count
    }

    private func pick(_ index: Int) {
        let list = matches
        guard list.indices.contains(index) else { return }
        graphVM.revealEntity(id: list[index].id)
        clear()
    }

    private func clear() {
        query = ""
        highlighted = 0
        focused = false
    }
}
