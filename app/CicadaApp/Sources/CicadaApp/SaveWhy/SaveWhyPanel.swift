import AppKit
import SwiftUI

/// A panel that never activates the app: it floats over the browser (full screen included) and takes the keyboard
/// only once the person clicks into it — then Esc closes it.
final class SaveWhyNSPanel: NSPanel {
    var onEscape: (() -> Void)?

    override var canBecomeKey: Bool { true }
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

        let screen = NSScreen.main ?? NSScreen.screens.first
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

        let host = NSHostingView(rootView: SaveWhyPanelView(center: center, focus: focus, notch: notch))
        panel.contentView = host
        panel.setFrame(SaveWhyNotch.frame(screen: screenFrame, notch: notchRect, size: host.fittingSize),
                       display: false)
        panel.orderFrontRegardless()
        self.panel = panel
        // Next turn of the run loop, so the view has drawn the shape at rest and the spring has a start to leave.
        DispatchQueue.main.async { [notch] in notch.grown = true }
        // A click anywhere else — another app (global) or another of Cicada's windows (local) — closes it.
        if let global = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: {
            [weak center] _ in Task { @MainActor in center?.send(.clickOutside) }
        }) { monitors.append(global) }
        if let local = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: {
            [weak center, weak panel] event in
            if event.window !== panel { Task { @MainActor in center?.send(.clickOutside) } }
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

    func focusText() {
        panel?.makeKey()
        // The field is new: let SwiftUI lay it out, then grow the window downward (its top stays on the screen's edge).
        DispatchQueue.main.async { [weak self] in
            guard let self, let panel = self.panel, let content = panel.contentView, let placed = self.placedOn
            else { return }
            panel.setFrame(SaveWhyNotch.frame(screen: placed.screen, notch: placed.notch, size: content.fittingSize),
                           display: true)
            self.focus.request()
        }
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

/// G191 — the panel itself: the bookworm, the question, the page it is about, the one-tap answers, "Something else…" and
/// "Don't ask for this site". v2 (owner 2026-10-14): the notch growing — notch-black in both appearances, the top
/// band empty for the notch, one hairline sheen on the grown edge, a ring-free outline (DESIGN_RULES §9, 2026-10-14).
struct SaveWhyPanelView: View {
    let center: SaveWhyCenter
    let focus: SaveWhyFocus
    let notch: SaveWhyNotchModel
    @FocusState private var textFocused: Bool
    @State private var draft = ""
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let width: CGFloat = 440
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
                .accessibilityElement(children: .contain)
                .accessibilityLabel(Copy.SaveWhy.question)
        }
    }

    private func card(_ state: SaveWhyPanelState) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            header(state)
            FlowLayout(spacing: CicadaTheme.scaled(6)) {
                ForEach(center.options.reasons) { reason in
                    chip(reason.label, selected: state.isSelected(reason: reason.key)) {
                        center.send(.tapReason(reason.key))
                    }
                }
                ForEach(center.options.projects) { project in
                    chip(Copy.SaveWhy.forProject(project.name), selected: state.isSelected(project: project.id)) {
                        center.send(.tapProject(project.id))
                    }
                }
                chip(Copy.SaveWhy.somethingElse, selected: state.phase == .writing) { center.send(.tapOther) }
            }
            if state.phase == .writing {
                TextField(Copy.SaveWhy.placeholder, text: $draft)
                    .textFieldStyle(.roundedBorder)
                    .focused($textFocused)
                    .onChange(of: draft) { _, text in center.send(.draftChanged(text)) }
                    .onSubmit { center.send(.submitText) }
            }
            HStack {
                Text(state.phase == .answered ? Copy.SaveWhy.savingHint : Copy.SaveWhy.hint)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.Notch.textTertiary)
                Spacer()
                Button(Copy.SaveWhy.dontAsk) { center.send(.dontAskForSite) }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.Notch.textSecondary)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.top, CicadaTheme.spacingSM)
        .padding(.bottom, CicadaTheme.spacingMD)
        .frame(width: Self.width, alignment: .leading)
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
                Text(Copy.SaveWhy.subject(title: state.item.title, host: state.item.host))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.Notch.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(CicadaTheme.font(size: 12, weight: selected ? .semibold : .regular))
                .foregroundStyle(CicadaTheme.Notch.textPrimary)
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.vertical, CicadaTheme.scaled(5))
                .background(Capsule().fill(selected ? CicadaTheme.Notch.chipSelected : Color.clear))
                .overlay(Capsule().strokeBorder(selected ? CicadaTheme.Notch.chipSelectedRing : CicadaTheme.Notch.chipRing,
                                                lineWidth: 1))
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
