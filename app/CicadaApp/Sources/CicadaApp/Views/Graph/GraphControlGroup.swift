import SwiftUI

/// The Graph's one quiet floating group (Direction D, §10 Graph; R-DG2, R-DG3): the whose-beliefs text tabs,
/// Legend, − + fit and the pan toggle, bottom-leading on the canvas. It replaced four islands — a find field and
/// an observer bar top-left, a context legend bottom-left, filter and zoom bottom-right — each its own glass card.
///
/// An opaque floating surface, not Liquid Glass (R-DG2): `LiquidGlass.swift` keeps glass off the canvas until the
/// G109 frame-time check has been run, and R-SU17 let that rule outrank a design doc before.
struct GraphControlGroup: View {
    static let height: CGFloat = 36

    let showsObserverTabs: Bool
    let legendOpen: Bool
    let onToggleLegend: () -> Void
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            if showsObserverTabs {
                GraphObserverTabs()
                Color.clear.frame(width: CicadaTheme.spacingSM, height: 1)
            }
            GraphLegendButton(isOpen: legendOpen, action: onToggleLegend)
            Color.clear.frame(width: CicadaTheme.spacingSM, height: 1)
            IconButton(systemName: "minus", help: Copy.Graph.zoomOut) { graphVM.zoomAction = .out }
            IconButton(systemName: "plus", help: Copy.Graph.zoomIn) { graphVM.zoomAction = .zoomIn }
            IconButton(systemName: "arrow.up.left.and.arrow.down.right", help: Copy.Graph.fit) { graphVM.zoomAction = .fit }
            // Pan mode — the click-based twin of holding Shift (owner, 2026-09-03).
            IconButton(systemName: "arrow.up.and.down.and.arrow.left.and.right",
                       help: graphVM.panModeOn ? Copy.Graph.panOnHelp : Copy.Graph.panOffHelp,
                       isOn: graphVM.panModeOn) { graphVM.panModeOn.toggle() }
        }
        .padding(.horizontal, CicadaTheme.spacingXS)
        .frame(height: CicadaTheme.scaled(Self.height))
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Graph.controlsLabel)
    }
}

/// All · Cicada · You · External (R-DG3) — DR-45's text tabs over `setObserver`, shown only when the graph
/// holds more than one observer (a single-observer graph has nothing to lens).
struct GraphObserverTabs: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        TextTabs(tabs: GraphChrome.observerTabs,
                 selection: Binding(get: { graphVM.observerSelection }, set: { graphVM.setObserver($0) }))
    }
}

/// "Legend" / "Legend · filtered", with the context hues the edges wear (R-DG4). Open is `bgSelected`,
/// never the accent (DR-5).
struct GraphLegendButton: View {
    let isOpen: Bool
    let action: () -> Void
    @Environment(GraphViewModel.self) private var graphVM
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                let dots = GraphChrome.legendDotContexts(graphVM.contextRoster)
                if !dots.isEmpty {
                    HStack(spacing: CicadaTheme.scaled(2)) {
                        ForEach(dots, id: \.self) {
                            Circle().fill(CicadaTheme.contextColor($0))
                                .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
                        }
                    }
                    .accessibilityHidden(true)
                }
                Text(GraphChrome.legendLabel(graphVM.filter))
                Image(systemName: isOpen ? "chevron.down" : "chevron.up")
                    .font(CicadaTheme.font(size: 9, weight: .semibold))
                    .accessibilityHidden(true)
            }
            .font(CicadaTheme.metaMediumFont)
            .foregroundStyle(isOpen || hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(height: CicadaTheme.scaled(TextTabs<String>.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(isOpen ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.Graph.legendHelp)
        .accessibilityAddTraits(isOpen ? .isSelected : [])
    }
}

/// The Legend panel (R-DG4): the context legend, the filters and a key to the canvas's shapes, in one floating
/// surface above the group. Native checkboxes, slider and switch follow the Mac's accent by themselves (DR-4).
struct GraphLegendPanel: View {
    static let width: CGFloat = 272
    static let rowHeight: CGFloat = 28

    let showsObserverTabs: Bool
    let maxHeight: CGFloat
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        ViewThatFits(in: .vertical) {
            content
            ScrollView { content }
        }
        .frame(width: CicadaTheme.scaled(Self.width))
        .frame(maxHeight: maxHeight)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Graph.legendHelp)
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if showsObserverTabs {
                heading(Copy.Graph.whoseBeliefs)
                GraphObserverTabs().padding(.bottom, CicadaTheme.spacingXS)
            }
            if !graphVM.contextRoster.isEmpty {
                heading(Copy.Graph.contextHeading, showAll: !graphVM.filter.contexts.isEmpty) {
                    graphVM.filter.contexts = []
                }
                ForEach(GraphChrome.contextRows(roster: graphVM.contextRoster, edges: graphVM.edges, filter: graphVM.filter)) { row in
                    legendRow(on: row.isOn, action: { graphVM.toggleContext(row.context) }) {
                        Capsule().fill(CicadaTheme.contextColor(row.context))
                            .frame(width: CicadaTheme.scaled(14), height: CicadaTheme.scaled(2))
                    } label: {
                        Text(ClaimContext.displayName(row.context))
                    } trailing: {
                        Text(GraphChrome.linksLabel(row.links))
                    }
                }
            }
            heading(Copy.Graph.typeHeading, showAll: !graphVM.filter.allTypesSelected) {
                graphVM.filter.types = Set(EntityType.selectableCases)
            }
            ForEach(GraphChrome.typeRows(nodes: graphVM.nodes, filter: graphVM.filter)) { row in
                legendRow(on: row.isOn, action: { graphVM.toggleType(row.type) }) {
                    Circle().fill(CicadaTheme.entityColor(for: row.type))
                        .frame(width: CicadaTheme.scaled(9), height: CicadaTheme.scaled(9))
                } label: {
                    Text(row.type.label)
                } trailing: {
                    Text(UsageFormat.count(row.count))
                }
            }
            heading(Copy.Graph.statusHeading)
            ForEach(GraphChrome.statusRows(graphVM.filter)) { row in
                Toggle(isOn: Binding(get: { row.isOn }, set: { _ in graphVM.filter.toggleStatus(row.status) })) {
                    HStack {
                        Text(row.label).font(CicadaTheme.font(size: 13)).foregroundStyle(CicadaTheme.textPrimary)
                        Spacer(minLength: 0)
                        if let hint = row.hint {
                            Text(hint).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                }
                .toggleStyle(.checkbox)
                .frame(height: CicadaTheme.scaled(Self.rowHeight))
                .padding(.horizontal, CicadaTheme.spacingSM)
            }
            HStack {
                SectionLabel(Copy.Graph.minConfidence)
                Spacer(minLength: 0)
                Text(GraphChrome.minConfidenceLabel(graphVM.filter.minConfidence))
                    .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textSecondary)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.top, CicadaTheme.spacingSM)
            Slider(value: Binding(get: { graphVM.filter.minConfidence }, set: { graphVM.filter.minConfidence = $0 }),
                   in: 0...1, step: 0.05)
                .controlSize(.small)
                .padding(.horizontal, CicadaTheme.spacingSM)
            Toggle(Copy.Graph.showLogos, isOn: Binding(
                get: { graphVM.filter.showLogos },
                set: { on in
                    graphVM.filter.showLogos = on
                    if on { Task { await graphVM.pushVisibleLogos() } }
                }))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .font(CicadaTheme.font(size: 13))
                .help(Copy.Graph.showLogosHelp)
                .frame(height: CicadaTheme.scaled(32))
                .padding(.horizontal, CicadaTheme.spacingSM)
            key
        }
        .padding(CicadaTheme.spacingSM)
    }

    /// DR-69 — the canvas's shapes in words (nothing on the canvas explains itself otherwise).
    private var key: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            keyLine(Copy.Graph.keyBigger) {
                HStack(alignment: .bottom, spacing: 1) {
                    Circle().frame(width: CicadaTheme.scaled(5), height: CicadaTheme.scaled(5))
                    Circle().frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
                }
                .foregroundStyle(CicadaTheme.textTertiary)
            }
            keyLine(Copy.Graph.keyDashed) {
                Circle().strokeBorder(CicadaTheme.textTertiary, style: StrokeStyle(lineWidth: 1.5, dash: [2.5, 2]))
            }
            keyLine(Copy.Graph.keyPulse) {
                ZStack {
                    Circle().fill(CicadaTheme.textTertiary).padding(CicadaTheme.scaled(4))
                    Circle().strokeBorder(CicadaTheme.pendingPulse, lineWidth: 1.5)
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .padding(.top, CicadaTheme.spacingMD)
    }

    private func keyLine<Glyph: View>(_ text: String, @ViewBuilder glyph: () -> Glyph) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            glyph().frame(width: CicadaTheme.scaled(14), height: CicadaTheme.scaled(14)).accessibilityHidden(true)
            Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func heading(_ title: String, showAll: Bool = false, clear: @escaping () -> Void = {}) -> some View {
        HStack {
            SectionLabel(title)
            Spacer(minLength: 0)
            if showAll { TextButton(title: Copy.Graph.showAll, action: clear) }
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .padding(.top, CicadaTheme.spacingSM)
    }

    private func legendRow<Swatch: View, Label: View, Trailing: View>(
        on: Bool, action: @escaping () -> Void,
        @ViewBuilder swatch: () -> Swatch, @ViewBuilder label: () -> Label, @ViewBuilder trailing: () -> Trailing
    ) -> some View {
        LegendRow(on: on, action: action, swatch: swatch(), label: label(), trailing: trailing())
    }
}

/// One Legend row: a swatch, the name, a count; dimmed when off; hover is a fill (DR-48). Its own view so each
/// row keeps its own hover state.
private struct LegendRow<Swatch: View, Label: View, Trailing: View>: View {
    let on: Bool
    let action: () -> Void
    let swatch: Swatch
    let label: Label
    let trailing: Trailing
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                swatch.opacity(on ? 1 : 0.3).frame(width: CicadaTheme.scaled(14)).accessibilityHidden(true)
                label.font(CicadaTheme.font(size: 13))
                    .foregroundStyle(on ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                Spacer(minLength: 0)
                trailing.font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(GraphLegendPanel.rowHeight))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
