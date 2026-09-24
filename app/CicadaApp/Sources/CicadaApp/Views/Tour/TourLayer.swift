import SwiftUI

/// G152 — the tour over the page area (ContentView's `overlayPreferenceValue` on the Reader host, so the rail, the
/// titlebar and the demo banner are outside it): a scrim with a hole around the current stop's target, the focus ring
/// on the hole's edge (DR-5's first use), and the coach mark. It is also the one view always mounted over the pages,
/// so it owns the tour's triggers — a door's request, the demo's first visit — and routes each stop to its page
/// through `AppRouter`, never by clicking anything (ruling R-DT9).
struct TourLayer: View {
    let anchors: [TourAnchorID: Anchor<CGRect>]
    /// The Welcome or the Settings panel covers the window: the tour waits under it, and nothing starts.
    let hidden: Bool
    let navWidth: CGFloat

    @Environment(TourController.self) private var tour
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(InboxViewModel.self) private var inboxVM
    @State private var calloutSize = CGSize(width: CoachMarkLayout.width, height: 180)

    private var context: TourContext {
        TourContext.from(roster: store.banks.value, graph: store.graph.value, inboxCount: inboxVM.pendingCount)
    }

    /// The auto-start's input: the demo is ON SCREEN, not merely named by the roster — `DemoMode.isShowing` flips only
    /// once `Store.bank` has caught up, so the tour is stamped with the demo's name and the bank-switch interrupt below
    /// never ends the tour the switch itself started.
    private var demoActive: Bool { DemoMode.isShowing(store.banks.value, bank: store.bank) }

    private struct TriggerKey: Equatable {
        let pending: Bool
        let hidden: Bool
        let demo: Bool
    }

    var body: some View {
        GeometryReader { proxy in
            if !hidden, let stop = tour.currentStop, let index = tour.index {
                let step = TourPlan.step(stop, context: context)
                let scale = CGFloat(CicadaTheme.uiScale)
                let target = targetRect(step, in: proxy, scale: scale)
                let placement = CoachMarkLayout.place(target: target, container: proxy.size, callout: calloutSize,
                                                      scale: scale)
                ZStack(alignment: .topLeading) {
                    TourScrim(hole: stop == .search ? nil
                              : target?.insetBy(dx: -CoachMarkLayout.holeInset * scale,
                                                dy: -CoachMarkLayout.holeInset * scale))
                    CoachMark(step: step, index: index, count: tour.count, isLast: tour.isLast,
                              next: { tour.next() }, back: { tour.back() }, skip: { tour.finish() })
                        .frame(width: CicadaTheme.scaled(CoachMarkLayout.width))
                        .fixedSize(horizontal: false, vertical: true)
                        .background {
                            GeometryReader { g in Color.clear.preference(key: CoachMarkSizeKey.self, value: g.size) }
                        }
                        .offset(x: placement.origin.x, y: placement.origin.y)
                }
                .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
                .onPreferenceChange(CoachMarkSizeKey.self) { calloutSize = $0 }
            }
        }
        .onChange(of: TriggerKey(pending: tour.pendingStart, hidden: hidden, demo: demoActive), initial: true) { _, _ in
            evaluate()
        }
        .onChange(of: tour.arrival) { _, _ in route() }
        .onChange(of: store.bank) { _, bank in
            if tour.isActive, tour.bank != bank { tour.interrupt() }
        }
    }

    /// The command bar's rect is computed (it is not in this coordinate space); every other stop takes its first
    /// published candidate, or nil — then the mark sits in the middle, unanchored.
    private func targetRect(_ step: TourStep, in proxy: GeometryProxy, scale: CGFloat) -> CGRect? {
        if step.anchors.first == .commandBar {
            return CoachMarkLayout.commandBarRect(pageWidth: proxy.size.width, navWidth: navWidth, scale: scale)
        }
        for id in step.anchors {
            if let anchor = anchors[id] { return proxy[anchor] }
        }
        return nil
    }

    private func evaluate() {
        switch TourTrigger.decide(pendingStart: tour.pendingStart, hidden: hidden, demoActive: demoActive,
                                  demoStarted: tour.demoStarted, tourActive: tour.isActive) {
        case .start: tour.start(bank: store.bank)
        case .autoStartDemo: tour.autoStart(bank: store.bank)
        case .none: break
        }
    }

    private func route() {
        guard let stop = tour.currentStop else { return }
        TourRouting.apply(TourPlan.step(stop, context: context).navigation, router: router)
    }
}

private struct CoachMarkSizeKey: PreferenceKey {
    static var defaultValue = CGSize(width: CoachMarkLayout.width, height: 180)
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) { value = nextValue() }
}

/// The page dimmed around one target. Clicks land here and do nothing: the page under the tour is inert, and the tour
/// never acts for the person (G152). `scrimPanel` is the Settings panel's own scrim, so the two modal layers read the
/// same (ruling R-DT10).
struct TourScrim: View {
    let hole: CGRect?
    @State private var shown = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack(alignment: .topLeading) {
            Rectangle().fill(CicadaTheme.scrimPanel)
            if let hole {
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .frame(width: hole.width, height: hole.height)
                    .offset(x: hole.minX, y: hole.minY)
                    .blendMode(.destinationOut)
            }
        }
        .compositingGroup()
        .overlay(alignment: .topLeading) {
            if let hole {
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .strokeBorder(CicadaTheme.focusRing, lineWidth: 2)
                    .frame(width: hole.width, height: hole.height)
                    .offset(x: hole.minX, y: hole.minY)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {}
        .accessibilityHidden(true)
        .opacity(shown ? 1 : 0)
        .animation(CicadaMotion.coachMark(reduceMotion: reduceMotion), value: shown)
        .onAppear { shown = true }
    }
}

/// F-08's callout: "1 of 6" and six dots, the stop's title and one or two sentences, then Skip tour · Back · Next. A
/// floating surface (DR-9/DR-10). Next is a `NeutralButton` so the demo banner's *Finish setting up* stays the one
/// accent on screen (DR-5, DR-40). ⏎ is Next, Esc is Skip tour — the visible controls' own shortcuts, never hidden ones
/// — and ← / → step back and forth while the mark has focus, which it takes when it appears (DR-68, DR-69: every key
/// has a visible twin with a `.help`).
struct CoachMark: View {
    let step: TourStep
    let index: Int
    let count: Int
    let isLast: Bool
    let next: () -> Void
    let back: () -> Void
    let skip: () -> Void

    @FocusState private var focused: Bool
    @State private var shown = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Tour.progress(index + 1, of: count))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                Spacer(minLength: CicadaTheme.spacingSM)
                TourDots(index: index, count: count)
            }
            Text(step.title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Text(step.body)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingXS) {
                TextButton(title: Copy.Tour.skip, keyHint: "esc", help: Copy.Tour.skipHelp, action: skip)
                    .keyboardShortcut(.cancelAction)
                Spacer(minLength: CicadaTheme.spacingSM)
                if index > 0 {
                    TextButton(title: Copy.Tour.back, help: Copy.Tour.backHelp, action: back)
                }
                NeutralButton(title: isLast ? Copy.Tour.done : Copy.Tour.next,
                              trailingSystemImage: isLast ? nil : "arrow.right", size: .compact,
                              shortcut: .defaultAction, help: isLast ? Copy.Tour.doneHelp : Copy.Tour.nextHelp,
                              action: next)
            }
            .padding(.top, CicadaTheme.spacingXS)
        }
        .padding(CicadaTheme.spacingLG)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .focusable()
        .focusEffectDisabled()
        .focused($focused)
        .onKeyPress(.leftArrow) { back(); return .handled }
        .onKeyPress(.rightArrow) { next(); return .handled }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Tour.accessibilityLabel(index + 1, of: count))
        .opacity(shown ? 1 : 0)
        .offset(y: shown || reduceMotion ? 0 : CicadaTheme.scaled(CicadaMotion.coachMarkRise))
        .animation(CicadaMotion.coachMark(reduceMotion: reduceMotion), value: shown)
        .onAppear {
            shown = true
            focused = true
        }
        .onChange(of: index) { _, _ in
            focused = true
            AccessibilityNotification.Announcement(step.title).post()
        }
    }
}

/// Six dots, the current one a wider pill — in the text ladder, never the accent (DR-5). Decorative: "1 of 6" beside
/// them is their text twin (DR-69).
private struct TourDots: View {
    let index: Int
    let count: Int

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(4)) {
            ForEach(0..<count, id: \.self) { i in
                Capsule()
                    .fill(i == index ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(i == index ? 12 : 5), height: CicadaTheme.scaled(5))
            }
        }
        .accessibilityHidden(true)
    }
}
