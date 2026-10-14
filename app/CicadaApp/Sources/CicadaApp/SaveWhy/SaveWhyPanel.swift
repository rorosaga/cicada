import AppKit
import SwiftUI

/// G191 — where the panel sits: top centre of the screen, just under the menu bar — under the notch on a Mac that has
/// one, the same place on one that does not. Pure, so it is tested without a screen.
enum SaveWhyPlacement {
    /// The gap between the menu bar's bottom edge and the panel.
    static let gap: CGFloat = 6
    /// Used when the menu bar is hidden (full screen, auto-hide) and the screen reports no notch either.
    static let fallbackMenuBar: CGFloat = 24

    /// `(start, end)` frames in screen coordinates (origin bottom-left): `end` is where the panel rests, `start` is
    /// `distance` higher — inside the menu bar — so the arrival reads as a drop out of it.
    static func frames(screen: CGRect, visible: CGRect, notchTop: CGFloat, size: CGSize,
                       distance: CGFloat) -> (start: CGRect, end: CGRect) {
        var menuBar = screen.maxY - visible.maxY
        if menuBar <= 0 { menuBar = notchTop > 0 ? notchTop : fallbackMenuBar }
        let x = (screen.midX - size.width / 2).rounded()
        let y = (screen.maxY - menuBar - gap - size.height).rounded()
        let end = CGRect(x: x, y: y, width: size.width, height: size.height)
        return (end.offsetBy(dx: 0, dy: distance), end)
    }
}

/// A panel that never activates the app: it floats over the browser (full screen included) and takes the keyboard
/// only once the person clicks into it — then Esc closes it.
final class SaveWhyNSPanel: NSPanel {
    var onEscape: (() -> Void)?

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onEscape?() }
}

/// G191 — the live presenter: one `NSPanel` hosting `SaveWhyPanelView`, shown with `orderFrontRegardless` (never
/// `makeKey`), so the browser keeps focus and keyboard until the person clicks the panel.
@MainActor
final class SaveWhyPanelController: SaveWhyPresenting {
    private var panel: SaveWhyNSPanel?
    private var monitors: [Any] = []
    private let focus = SaveWhyFocus()

    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    func show(_ center: SaveWhyCenter) {
        hideNow()
        let panel = SaveWhyNSPanel(contentRect: .zero, styleMask: [.nonactivatingPanel, .borderless],
                                   backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = .statusBar
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false   // depth is a ring, not a shadow (direction D)
        panel.onEscape = { [weak center] in center?.send(.escape) }
        let host = NSHostingView(rootView: SaveWhyPanelView(center: center, focus: focus))
        panel.contentView = host
        let size = host.fittingSize
        let screen = NSScreen.main ?? NSScreen.screens.first
        let motion = CicadaMotion.notchDrop(reduceMotion: reduceMotion)
        let frames = SaveWhyPlacement.frames(
            screen: screen?.frame ?? CGRect(x: 0, y: 0, width: 1440, height: 900),
            visible: screen?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 876),
            notchTop: screen?.safeAreaInsets.top ?? 0, size: size, distance: motion.distance)
        panel.setFrame(frames.start, display: false)
        panel.alphaValue = 0
        panel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = motion.duration
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().setFrame(frames.end, display: true)
            panel.animator().alphaValue = 1
        }
        self.panel = panel
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
        let motion = CicadaMotion.notchLeave(reduceMotion: reduceMotion)
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = motion.duration
            panel.animator().setFrame(panel.frame.offsetBy(dx: 0, dy: motion.distance), display: true)
            panel.animator().alphaValue = 0
        }, completionHandler: { panel.orderOut(nil) })
    }

    func focusText() {
        panel?.makeKey()
        // The field is new: let SwiftUI lay it out, then grow the panel downward (its top stays under the menu bar).
        DispatchQueue.main.async { [weak self] in
            guard let self, let panel = self.panel, let content = panel.contentView else { return }
            let size = content.fittingSize
            let top = panel.frame.maxY
            panel.setFrame(CGRect(x: panel.frame.minX, y: top - size.height, width: size.width, height: size.height),
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

/// G191 — the panel itself: the question, the page it is about, the one-tap answers, "Something else…" and "Don't ask
/// for this site". Chrome-layer glass (DR-14, floating control) through `liquidGlass`, a ring for depth.
struct SaveWhyPanelView: View {
    let center: SaveWhyCenter
    let focus: SaveWhyFocus
    @FocusState private var textFocused: Bool
    @State private var draft = ""

    static let width: CGFloat = 440

    var body: some View {
        if let state = center.state {
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
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    Button(Copy.SaveWhy.dontAsk) { center.send(.dontAskForSite) }
                        .buttonStyle(.cicadaPlain)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            .padding(CicadaTheme.spacingMD)
            .frame(width: Self.width, alignment: .leading)
            .liquidGlass(.control, in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous)
                .strokeBorder(CicadaTheme.borderLight, lineWidth: 1))
            .onChange(of: focus.ticket) { _, _ in textFocused = true }
            .accessibilityElement(children: .contain)
            .accessibilityLabel(Copy.SaveWhy.question)
        }
    }

    private func header(_ state: SaveWhyPanelState) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            Text(Copy.SaveWhy.question)
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.SaveWhy.subject(title: state.item.title, host: state.item.host))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(CicadaTheme.font(size: 12, weight: selected ? .semibold : .regular))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.vertical, CicadaTheme.scaled(5))
                .background(Capsule().fill(selected ? CicadaTheme.bgSelected : Color.clear))
                .overlay(Capsule().strokeBorder(selected ? CicadaTheme.textSecondary : CicadaTheme.borderLight,
                                                lineWidth: 1))
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
