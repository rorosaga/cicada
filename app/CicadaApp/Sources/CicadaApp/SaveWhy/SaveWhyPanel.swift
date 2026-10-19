import AppKit
import SwiftUI

/// A panel that never activates the app: it floats over the browser (full screen included) and takes the keyboard
/// only once the person clicks into it — then Esc closes it.
///
/// G191 live: "only once the person clicks into it" is enforced here, not hoped for. `canBecomeKey` is false until a
/// mouse-down lands in this panel, so no app activation, window cycling or stray key can make it key and type into
/// it or press a chip (the measured "Something else…" that opened by itself).
final class SaveWhyNSPanel: NSPanel {
    var onEscape: (() -> Void)?
    /// Whether the person has clicked inside this panel since it showed.
    private(set) var clickedInside = false

    override var canBecomeKey: Bool { clickedInside }

    override func sendEvent(_ event: NSEvent) {
        if Self.isPersonsClick(event.type) { clickedInside = true }
        super.sendEvent(event)
    }

    static func isPersonsClick(_ type: NSEvent.EventType) -> Bool {
        type == .leftMouseDown || type == .rightMouseDown || type == .otherMouseDown
    }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onEscape?() }
    /// AppKit keeps windows under the menu bar; this one is the notch growing, so its top is the screen's edge.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

/// G191 v2 — what the controller and the view share: whether the shape is grown, and the notch it grows from.
@MainActor
@Observable
final class SaveWhyNotchModel {
    var grown = false
    var collapsed = SaveWhyNotch.collapsed(notch: nil)
    var band = SaveWhyNotch.fallbackMenuBar
}

/// G191 — the live presenter: one `NSPanel` hosting `SaveWhyPanelView`, shown with `orderFrontRegardless` (never
/// `makeKey`), so the browser keeps focus and keyboard until the person clicks the panel. The window sits over the
/// menu bar with its top on the screen's top edge (`SaveWhyNotch.frame`); the view grows the notch's shape inside it.
@MainActor
final class SaveWhyPanelController: SaveWhyPresenting {
    private var panel: SaveWhyNSPanel?
    private var monitors: [Any] = []
    private let focus = SaveWhyFocus()
    /// One per showing, so a panel still shrinking away never re-grows with the next.
    private var notch = SaveWhyNotchModel()
    /// Where the open panel was placed, so a resize keeps its top on the screen's edge under the same notch.
    private var placedOn: (screen: CGRect, notch: CGRect?)?
    /// The open panel — for tests (losing the keyboard to another app's window never closes it).
    var window: SaveWhyNSPanel? { panel }

    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    /// Above the menu bar and its status items (the panel covers the bar around the notch while it shows), below
    /// menus, so an open menu still draws over it.
    static let level = NSWindow.Level(rawValue: NSWindow.Level.mainMenu.rawValue + 3)

    func show(_ center: SaveWhyCenter) {
        hideNow()
        let panel = SaveWhyNSPanel(contentRect: .zero, styleMask: [.nonactivatingPanel, .borderless],
                                   backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = Self.level
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false   // depth is a ring, not a shadow (direction D)
        // Notch-black in both appearances: AppKit's own controls (the text field) draw dark on it too.
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.onEscape = { [weak center] in center?.send(.escape) }

        // G191 live: the screen the bookmark was made on — the browser's front window, else the front app's — and
        // `NSScreen.main` only when neither is known (`SaveWhyScreen`). The notch is that screen's own.
        let screen = SaveWhyScreen.live(channel: center.state?.channel)
        let screenFrame = screen?.frame ?? CGRect(x: 0, y: 0, width: 1440, height: 900)
        let visible = screen?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 876)
        let notchRect = SaveWhyNotch.notchRect(screen: screenFrame, topLeft: screen?.auxiliaryTopLeftArea,
                                               topRight: screen?.auxiliaryTopRightArea,
                                               topInset: screen?.safeAreaInsets.top ?? 0)
        let notch = SaveWhyNotchModel()
        self.notch = notch
        notch.collapsed = SaveWhyNotch.collapsed(notch: notchRect)
        notch.band = SaveWhyNotch.band(screen: screenFrame, visible: visible, notch: notchRect)
        placedOn = (screenFrame, notchRect)

        let host = NSHostingView(rootView: SaveWhyPanelView(center: center, focus: focus, notch: notch,
                                                            onFieldClick: { [weak self, weak center] in
            center?.input(.engage)
            self?.focusText()
        }))
        panel.contentView = host
        panel.setFrame(SaveWhyNotch.frame(screen: screenFrame, notch: notchRect, size: host.fittingSize),
                       display: false)
        panel.orderFrontRegardless()
        self.panel = panel
        // Next turn of the run loop, so the view has drawn the shape at rest and the spring has a start to leave.
        DispatchQueue.main.async { [notch] in notch.grown = true }
        // A click anywhere else — another app (global) or another of Cicada's windows (local) — closes it; a click
        // inside Chrome's own bookmark bubble does not (2026-10-19: the person is working there), unless it closed it.
        // Nothing else does: losing the keyboard to another app's window (a dictation tool's overlay) never closes it.
        if let global = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: {
            [weak center] _ in
            let location = NSEvent.mouseLocation
            let primary = NSScreen.screens.first?.frame.height ?? 0
            Task { @MainActor in
                center?.click(at: BookmarkBubblePolicy.windowListPoint(location, primaryHeight: primary))
            }
        }) { monitors.append(global) }
        if let local = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: {
            [weak center, weak panel] event in
            if event.window !== panel { Task { @MainActor in center?.input(.clickOutside) } }
            return event
        }) { monitors.append(local) }
    }

    func hide() {
        guard let panel else { return }
        removeMonitors()
        self.panel = nil
        // Back into the notch, then gone.
        notch.grown = false
        DispatchQueue.main.asyncAfter(deadline: .now() + CicadaMotion.notchShrinkLength(reduceMotion: reduceMotion)) {
            panel.orderOut(nil)
        }
    }

    /// A click in the field (G191 v3: the field is always there, so the window never resizes for it): the panel takes
    /// the keyboard — it may, the click was inside it — and the field the focus.
    func focusText() {
        guard let panel, panel.clickedInside else { return }
        panel.makeKey()
        focus.request()
    }

    private func hideNow() {
        removeMonitors()
        panel?.orderOut(nil)
        panel = nil
    }

    private func removeMonitors() {
        monitors.forEach(NSEvent.removeMonitor)
        monitors.removeAll()
    }
}

/// Asks the text field for focus from AppKit (the field exists only once "Something else…" is tapped).
@MainActor
@Observable
final class SaveWhyFocus {
    private(set) var ticket = 0
    func request() { ticket &+= 1 }
}

/// G191 — the panel itself: the bookworm, the question, the page it is about, the reasons as toggles, the words and
/// Save. v2 (owner 2026-10-14): the notch growing — notch-black in both appearances, the top band empty for the notch,
/// one hairline sheen on the grown edge, a ring-free outline (DESIGN_RULES §9, 2026-10-14). v3 (owner 2026-10-15):
/// any number of reasons, drawn as toggles; the field always there; Save or Return confirms; and nothing in it
/// changes size as it fills — the field, the footer and every chip's check slot are there from the first frame, so
/// the shape grows once and never jumps.
struct SaveWhyPanelView: View {
    let center: SaveWhyCenter
    let focus: SaveWhyFocus
    let notch: SaveWhyNotchModel
    /// A click in the field: make the panel key so the words go there.
    var onFieldClick: () -> Void = {}
    @FocusState private var textFocused: Bool
    @State private var draft = ""
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// Wide enough for the four reasons on one line at 1× (owner 2026-10-19: "The four options could all fit on a
    /// single line"); a larger text size wraps them (`SaveWhyChipRows`).
    static let width: CGFloat = 468
    /// The card's inner width: what the chips have.
    static var contentWidth: CGFloat { width - 2 * CicadaTheme.spacingMD }
    /// The bookworm's room-art size (64 × 48 at 1×, the sheet's own frame timings).
    static let mascotPoints: CGFloat = 48

    var body: some View {
        if let state = center.state {
            // Under Reduce Motion the shape is drawn grown and only fades (DR-66); otherwise it grows and shrinks.
            let progress: CGFloat = reduceMotion || notch.grown ? 1 : 0
            let shape = SaveWhyNotchShape(progress: progress, collapsed: notch.collapsed)
            card(state)
                .padding(.top, notch.band)
                .padding(.horizontal, SaveWhyNotch.ear)
                .opacity(notch.grown ? 1 : 0)
                .background(CicadaTheme.Notch.surface)
                .clipShape(shape)
                .overlay {
                    // The sheen: a hairline on the grown edge, faded out across the band so the screen's top edge
                    // never shows a line.
                    shape.stroke(CicadaTheme.Notch.edge, lineWidth: 1)
                        .mask(LinearGradient(stops: [.init(color: .clear, location: 0),
                                                     .init(color: .black, location: 0.45)],
                                             startPoint: .top, endPoint: .bottom))
                        .opacity(notch.grown ? 1 : 0)
                }
                .animation(notch.grown ? CicadaMotion.notchGrow(reduceMotion: reduceMotion)
                                       : CicadaMotion.notchShrink(reduceMotion: reduceMotion), value: notch.grown)
                .onChange(of: focus.ticket) { _, _ in textFocused = true }
                // In the field however it got there: the person is about to write or dictate — no timer closes it.
                .onChange(of: textFocused) { _, focused in if focused { center.input(.engage) } }
                .accessibilityElement(children: .contain)
                .accessibilityLabel(Copy.SaveWhy.question)
        }
    }

    private func card(_ state: SaveWhyPanelState) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            header(state)
            reasons(state)
            words(state)
            HStack {
                Text(Copy.SaveWhy.hint(pending: state.isPending, chosen: !state.selection.isEmpty,
                                       editing: state.isEditing, noBookmark: center.noBookmark))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.Notch.textTertiary)
                    .lineLimit(1)
                Spacer()
                // Kept in place while pending (no site to name yet), so the footer never moves when the link arrives.
                Button(Copy.SaveWhy.dontAsk) { center.input(.dontAskForSite) }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.Notch.textSecondary)
                    .opacity(state.isPending ? 0 : 1)
                    .disabled(state.isPending)
                    .accessibilityHidden(state.isPending)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.top, CicadaTheme.spacingSM)
        .padding(.bottom, CicadaTheme.spacingMD)
        .frame(width: Self.width, alignment: .leading)
    }

    /// The four reasons on one line (owner 2026-10-19), wrapping into balanced rows only when a larger text size
    /// leaves no room (`SaveWhyChipRows`). No project chips: the field is the "something else".
    private func reasons(_ state: SaveWhyPanelState) -> some View {
        SaveWhyReasonChips(reasons: center.options.reasons, isSelected: { state.isSelected(reason: $0) }) {
            center.input(.tapReason($0))
        }
    }

    /// The field and Save, always there: a few words of the person's own, Return or Save to confirm.
    private func words(_ state: SaveWhyPanelState) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(Copy.SaveWhy.placeholder, text: $draft)
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.Notch.textPrimary)
                .focused($textFocused)
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.vertical, CicadaTheme.scaled(6))
                .background(Capsule().strokeBorder(textFocused ? CicadaTheme.Notch.chipSelectedRing
                                                                : CicadaTheme.Notch.chipRing, lineWidth: 1))
                .contentShape(Capsule())
                .simultaneousGesture(TapGesture().onEnded { onFieldClick() })
                .onChange(of: draft) { _, text in center.send(.draftChanged(text)) }
                .onSubmit { center.input(.submit) }
                .accessibilityLabel(Copy.SaveWhy.wordsLabel)
            Button(Copy.SaveWhy.save) { center.input(.submit) }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.font(size: 12, weight: .semibold))
                .foregroundStyle(state.selection.isEmpty ? CicadaTheme.Notch.textTertiary
                                                         : CicadaTheme.Notch.textPrimary)
                .padding(.horizontal, CicadaTheme.scaled(12))
                .padding(.vertical, CicadaTheme.scaled(6))
                .background(Capsule().fill(state.selection.isEmpty ? Color.clear : CicadaTheme.Notch.chipSelected))
                .overlay(Capsule().strokeBorder(CicadaTheme.Notch.chipRing, lineWidth: 1))
                .disabled(state.selection.isEmpty)
        }
    }

    private func header(_ state: SaveWhyPanelState) -> some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            // The mascot, curious (its "?" beat), on the sheet's own clock; decorative, the question says it all.
            BookwormView(state: .curious(count: 1), pointSize: Self.mascotPoints)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(Copy.SaveWhy.question)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.Notch.textPrimary)
                Text(state.item.map { Copy.SaveWhy.subject(title: $0.title, host: $0.host, resave: $0.resave == true,
                                                           saved: state.isEditing) }
                     ?? Copy.SaveWhy.pendingSubject(browser: BrowserInventory.spec(forBookmarksChannel: state.channel)?
                                                    .name))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.Notch.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
    }
}

/// The reasons as toggles: a check slot that is filled or empty (always there, so a tap never moves the row), one
/// weight for both states (a bolder label would widen the chip and reflow the row). On one line at 1× (owner
/// 2026-10-19); `SaveWhyChipRows` wraps them into balanced rows when a larger text size leaves no room (DR-70).
struct SaveWhyReasonChips: View {
    let reasons: [SavedWhyOptions.Reason]
    let isSelected: (String) -> Bool
    let onTap: (String) -> Void

    var body: some View {
        SaveWhyChipRows(spacing: CicadaTheme.scaled(6), lineSpacing: CicadaTheme.scaled(6)) {
            ForEach(reasons) { reason in
                chip(reason.label, selected: isSelected(reason.key)) { onTap(reason.key) }
            }
        }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(4)) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(selected ? CicadaTheme.Notch.textPrimary : CicadaTheme.Notch.textTertiary)
                Text(title)
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(CicadaTheme.Notch.textPrimary)
                    .lineLimit(1)
                    .fixedSize()
            }
            .padding(.leading, CicadaTheme.scaled(6))
            .padding(.trailing, CicadaTheme.scaled(8))
            .padding(.vertical, CicadaTheme.scaled(5))
            .background(Capsule().fill(selected ? CicadaTheme.Notch.chipSelected : Color.clear))
            .overlay(Capsule().strokeBorder(selected ? CicadaTheme.Notch.chipSelectedRing : CicadaTheme.Notch.chipRing,
                                            lineWidth: 1))
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityAddTraits(selected ? [.isSelected, .isToggle] : [.isToggle])
    }
}

/// The chips' rows: every chip on one line when they fit, else the fewest balanced rows that do (four chips: two
/// and two, never three and one), else one per row. Each chip keeps its own size; nothing truncates.
struct SaveWhyChipRows: Layout {
    var spacing: CGFloat
    var lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        let rows = SaveWhyPanelLayout.rows(widths: sizes.map(\.width), available: proposal.width ?? .infinity,
                                           spacing: spacing)
        let width = rows.map { row in row.map { sizes[$0].width }.reduce(0, +) + spacing * CGFloat(row.count - 1) }
            .max() ?? 0
        let height = rows.map { row in row.map { sizes[$0].height }.max() ?? 0 }.reduce(0, +)
            + lineSpacing * CGFloat(max(0, rows.count - 1))
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        var y = bounds.minY
        for row in SaveWhyPanelLayout.rows(widths: sizes.map(\.width), available: bounds.width, spacing: spacing) {
            var x = bounds.minX
            let height = row.map { sizes[$0].height }.max() ?? 0
            for i in row {
                subviews[i].place(at: CGPoint(x: x, y: y + (height - sizes[i].height) / 2), anchor: .topLeading,
                                  proposal: ProposedViewSize(sizes[i]))
                x += sizes[i].width + spacing
            }
            y += height + lineSpacing
        }
    }
}

/// The chips' rows as indices, pure so the rule is tested: one row when every width fits in `available`, else the
/// fewest rows of an equal count (the last may be shorter) whose every row fits, else one chip per row.
enum SaveWhyPanelLayout {
    static func rows(widths: [CGFloat], available: CGFloat, spacing: CGFloat) -> [[Int]] {
        let n = widths.count
        guard n > 0 else { return [] }
        func fits(_ row: ArraySlice<Int>) -> Bool {
            row.map { widths[$0] }.reduce(0, +) + spacing * CGFloat(row.count - 1) <= available + 0.5
        }
        for count in 1...n {
            let perRow = Int((Double(n) / Double(count)).rounded(.up))
            let rows = stride(from: 0, to: n, by: perRow).map { Array($0..<min($0 + perRow, n)) }
            if rows.allSatisfy({ fits($0[...]) }) { return rows }
        }
        return (0..<n).map { [$0] }
    }
}

/// G191 live — which screen the panel grows on. The brief's measurement: Chrome on an external display, and the panel
/// there — `NSScreen.main` (the screen with the key window) happened to be right, but for a background app it is only
/// the screen of the last key window macOS reported, and it says nothing about the browser. So the panel goes where
/// the bookmark was made: the screen holding most of the browser's front window, else the front app's front window,
/// else `NSScreen.main`. Window bounds come from the window list (no Screen Recording needed for bounds and owner).
enum SaveWhyScreen {
    /// The index into `screens` (AppKit frames, origin bottom-left) for a window's AppKit frame, by the largest
    /// overlap; nil when no screen holds any of it.
    static func index(of window: CGRect, in screens: [CGRect]) -> Int? {
        var best: (index: Int, area: CGFloat)?
        for (i, screen) in screens.enumerated() {
            let overlap = screen.intersection(window)
            guard !overlap.isNull, overlap.width > 0, overlap.height > 0 else { continue }
            let area = overlap.width * overlap.height
            if area > (best?.area ?? 0) { best = (i, area) }
        }
        return best?.index
    }

    /// The first window rect any screen holds, in order of preference; else `fallback`.
    static func choose(screens: [CGRect], candidates: [CGRect?], fallback: Int?) -> Int? {
        for window in candidates.compactMap({ $0 }) {
            if let i = index(of: window, in: screens) { return i }
        }
        return fallback
    }

    /// A window-list rect (origin top-left of the primary display, y down) as an AppKit frame (origin bottom-left).
    static func appKitFrame(fromWindowList bounds: CGRect, primaryHeight: CGFloat) -> CGRect {
        CGRect(x: bounds.minX, y: primaryHeight - bounds.maxY, width: bounds.width, height: bounds.height)
    }

    /// The front-most normal (layer 0) on-screen window of `pid`, as an AppKit frame.
    @MainActor
    static func frontWindow(pid: pid_t) -> CGRect? {
        guard let primary = NSScreen.screens.first,
              let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
                as? [[String: Any]] else { return nil }
        for info in list {
            guard (info[kCGWindowOwnerPID as String] as? Int).map(pid_t.init) == pid,
                  (info[kCGWindowLayer as String] as? Int) == 0,
                  let dict = info[kCGWindowBounds as String] as? NSDictionary,
                  let bounds = CGRect(dictionaryRepresentation: dict as CFDictionary),
                  bounds.width > 1, bounds.height > 1 else { continue }
            return appKitFrame(fromWindowList: bounds, primaryHeight: primary.frame.height)
        }
        return nil
    }

    /// The live answer for a bookmark from `channel`'s browser.
    @MainActor
    static func live(channel: String?) -> NSScreen? {
        let screens = NSScreen.screens
        guard !screens.isEmpty else { return nil }
        let browser = channel.flatMap(BrowserInventory.spec(forBookmarksChannel:))
            .flatMap { NSRunningApplication.runningApplications(withBundleIdentifier: $0.bundleId).first }
        let front = NSWorkspace.shared.frontmostApplication
        let candidates: [CGRect?] = [browser.flatMap { frontWindow(pid: $0.processIdentifier) },
                                     front.flatMap { frontWindow(pid: $0.processIdentifier) }]
        let fallback = NSScreen.main.flatMap { main in screens.firstIndex { $0 == main } } ?? 0
        let i = choose(screens: screens.map(\.frame), candidates: candidates, fallback: fallback) ?? fallback
        return screens[i]
    }
}
