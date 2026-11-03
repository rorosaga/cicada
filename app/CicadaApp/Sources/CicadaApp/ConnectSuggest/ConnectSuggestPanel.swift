import AppKit
import SwiftUI

/// G231 — a panel that never takes the keyboard: no field, so nothing in it needs keys, and the app the person just
/// entered keeps every keystroke (the G191 lessons: no activation, no key window, no stray key pressing a button).
/// Its buttons answer the first click (`ConnectSuggestHostingView`), so it never needs to become key to be used.
final class ConnectSuggestNSPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    /// The notch growing: its top is the screen's edge, as the ask-why panel's is.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

/// A click on a button lands on the button, not on activating a window that never activates.
final class ConnectSuggestHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// G231 — the live presenter. The same notch as the ask-why question (`SaveWhyNotch`, `SaveWhyNotchShape`, the notch
/// tokens; DESIGN_RULES §9 2026-11-03): a borderless non-activating panel one level above the menu bar, on every Space
/// and over full screen, shown with `orderFrontRegardless`, on the screen of the app in front.
@MainActor
final class ConnectSuggestPanelController: ConnectSuggestPresenting {
    private var panel: ConnectSuggestNSPanel?
    private var notch = SaveWhyNotchModel()
    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    func show(_ center: ConnectSuggestCenter) {
        hideNow()
        let panel = ConnectSuggestNSPanel(contentRect: .zero, styleMask: [.nonactivatingPanel, .borderless],
                                          backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = SaveWhyPanelController.level
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false   // depth is a ring, not a shadow (direction D)
        panel.appearance = NSAppearance(named: .darkAqua)

        // The screen the person is working on: the front app's front window, else `NSScreen.main`.
        let screen = SaveWhyScreen.live(channel: nil)
        let screenFrame = screen?.frame ?? CGRect(x: 0, y: 0, width: 1440, height: 900)
        let visible = screen?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 876)
        let notchRect = SaveWhyNotch.notchRect(screen: screenFrame, topLeft: screen?.auxiliaryTopLeftArea,
                                               topRight: screen?.auxiliaryTopRightArea,
                                               topInset: screen?.safeAreaInsets.top ?? 0)
        let notch = SaveWhyNotchModel()
        self.notch = notch
        notch.collapsed = SaveWhyNotch.collapsed(notch: notchRect)
        notch.band = SaveWhyNotch.band(screen: screenFrame, visible: visible, notch: notchRect)

        let host = ConnectSuggestHostingView(rootView: ConnectSuggestPanelView(center: center, notch: notch))
        panel.contentView = host
        panel.setFrame(SaveWhyNotch.frame(screen: screenFrame, notch: notchRect, size: host.fittingSize),
                       display: false)
        panel.orderFrontRegardless()
        self.panel = panel
        // Next turn of the run loop, so the shape is drawn at rest and the spring has a start to leave.
        DispatchQueue.main.async { [notch] in notch.grown = true }
    }

    func hide() {
        guard let panel else { return }
        self.panel = nil
        notch.grown = false
        DispatchQueue.main.asyncAfter(deadline: .now() + CicadaMotion.notchShrinkLength(reduceMotion: reduceMotion)) {
            panel.orderOut(nil)
        }
    }

    private func hideNow() {
        panel?.orderOut(nil)
        panel = nil
    }
}

/// G231 — the suggestion itself: the bookworm beside the app's own icon, the question, what is read, two or three
/// things Cicada does with it, and No · Not now · Yes. Notch-black in both appearances with the dark ladder's text
/// (`CicadaTheme.Notch`), the notch's shape growing on its spring and only fading under Reduce Motion (DR-66).
struct ConnectSuggestPanelView: View {
    let center: ConnectSuggestCenter
    let notch: SaveWhyNotchModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// The ask-why card's width, so the notch has one size of voice.
    static let width: CGFloat = SaveWhyPanelView.width
    static let iconPoints: CGFloat = 32

    var body: some View {
        if let state = center.state {
            let progress: CGFloat = reduceMotion || notch.grown ? 1 : 0
            let shape = SaveWhyNotchShape(progress: progress, collapsed: notch.collapsed)
            card(state)
                .padding(.top, notch.band)
                .padding(.horizontal, SaveWhyNotch.ear)
                .opacity(notch.grown ? 1 : 0)
                .background(CicadaTheme.Notch.surface)
                .clipShape(shape)
                .overlay {
                    shape.stroke(CicadaTheme.Notch.edge, lineWidth: 1)
                        .mask(LinearGradient(stops: [.init(color: .clear, location: 0),
                                                     .init(color: .black, location: 0.45)],
                                             startPoint: .top, endPoint: .bottom))
                        .opacity(notch.grown ? 1 : 0)
                }
                .animation(notch.grown ? CicadaMotion.notchGrow(reduceMotion: reduceMotion)
                                       : CicadaMotion.notchShrink(reduceMotion: reduceMotion), value: notch.grown)
                // The pointer resting on it holds it; leaving starts its patience again.
                .onHover { center.input(.hover($0)) }
                .accessibilityElement(children: .contain)
                .accessibilityLabel(Copy.ConnectSuggest.title(state.appName))
        }
    }

    private func card(_ state: ConnectSuggestPanelState) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                // The mascot, curious, on the sheet's own clock; decorative — the question says it all.
                BookwormView(state: .curious(count: 1), pointSize: SaveWhyPanelView.mascotPoints)
                    .accessibilityHidden(true)
                // The app's own icon, as macOS draws it (DR-52: the real mark, never a stand-in).
                if let icon = center.icon {
                    Image(nsImage: icon)
                        .resizable()
                        .interpolation(.high)
                        .frame(width: CicadaTheme.scaled(Self.iconPoints), height: CicadaTheme.scaled(Self.iconPoints))
                        .accessibilityHidden(true)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(Copy.ConnectSuggest.title(state.appName))
                        .font(CicadaTheme.font(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.Notch.textPrimary)
                        .lineLimit(1)
                    Text(Copy.ConnectSuggest.reads(state.target))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.Notch.textTertiary)
                        .lineLimit(1)
                }
            }
            SaveWhyChipRows(spacing: CicadaTheme.scaled(6), lineSpacing: CicadaTheme.scaled(6)) {
                ForEach(Copy.ConnectSuggest.uses(state.target.kind), id: \.self) { use in
                    Text(use)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.Notch.textSecondary)
                        .lineLimit(1)
                        .fixedSize()
                        .padding(.horizontal, CicadaTheme.scaled(8))
                        .padding(.vertical, CicadaTheme.scaled(5))
                        .overlay(Capsule().strokeBorder(CicadaTheme.Notch.chipRing, lineWidth: 1))
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel(Copy.ConnectSuggest.usesLabel)
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer()
                quiet(Copy.ConnectSuggest.no, tone: CicadaTheme.Notch.textTertiary) { center.input(.no) }
                quiet(Copy.ConnectSuggest.notNow, tone: CicadaTheme.Notch.textSecondary) { center.input(.notNow) }
                Button(Copy.ConnectSuggest.yes) { center.input(.yes) }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.Notch.textPrimary)
                    .padding(.horizontal, CicadaTheme.scaled(14))
                    .padding(.vertical, CicadaTheme.scaled(6))
                    .background(Capsule().fill(CicadaTheme.Notch.chipSelected))
                    .overlay(Capsule().strokeBorder(CicadaTheme.Notch.chipSelectedRing, lineWidth: 1))
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.top, CicadaTheme.spacingSM)
        .padding(.bottom, CicadaTheme.spacingMD)
        .frame(width: Self.width, alignment: .leading)
    }

    private func quiet(_ title: String, tone: Color, action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.font(size: 12, weight: .medium))
            .foregroundStyle(tone)
            .padding(.horizontal, CicadaTheme.scaled(8))
            .padding(.vertical, CicadaTheme.scaled(6))
    }
}
