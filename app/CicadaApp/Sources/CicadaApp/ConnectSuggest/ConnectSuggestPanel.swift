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

/// G231 — the suggestion itself: the bookworm beside the app's own icon, the question, what is read, and
/// No · Not now · Yes (owner 2026-11-23: no chips of what Cicada does with it, and bigger answers). Notch-black in both appearances with the dark ladder's text
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
                // Its patience, drawn: the offer leaves when the bar has filled (owner 2026-11-25). Under the card's
                // own clip, so the bar follows the notch's sides and its rounded bottom corners.
                .overlay(alignment: .bottom) {
                    NotchCountdownBar(from: state.countdownFrom, length: ConnectSuggestPolicy.timeout)
                        .padding(.horizontal, SaveWhyNotch.ear)
                        .opacity(notch.grown ? 1 : 0)
                }
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
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                // The mascot, curious, on the sheet's own clock; decorative — the question says it all. After a
                // site's Yes it is pleased, inside a ring that closes into a check (owner 2026-11-23).
                WormFace(mood: state.confirmedAt == nil ? .asking : .pleased, size: SaveWhyPanelView.headPoints)
                    .padding(CicadaTheme.scaled(4))
                    .overlay { if Self.turnedOn(state) { ConnectedRing() } }
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
                    Text(Self.title(state))
                        .font(CicadaTheme.font(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.Notch.textPrimary)
                        .lineLimit(1)
                    Text(Self.line(state))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.Notch.textTertiary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer()
                if state.confirmedAt != nil, Self.hasButtons(state) {
                    // The one thing the person may need to do: the setting the words name (never a prompt, ruling 77).
                    answer(Copy.ConnectSuggest.openSettings, tone: CicadaTheme.Notch.textPrimary, filled: true) {
                        center.input(.openSetting)
                    }
                } else {
                    answer(Copy.ConnectSuggest.no, tone: CicadaTheme.Notch.textTertiary) { center.input(.no) }
                    answer(Copy.ConnectSuggest.notNow, tone: CicadaTheme.Notch.textSecondary) { center.input(.notNow) }
                    answer(Copy.ConnectSuggest.yes, tone: CicadaTheme.Notch.textPrimary, filled: true) {
                        center.input(.yes)
                    }
                }
            }
            // Once answered the buttons have nothing left to do; they keep their place so the card does not jump.
            .opacity(Self.hasButtons(state) ? 1 : 0)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.top, CicadaTheme.spacingSM)
        .padding(.bottom, CicadaTheme.spacingMD)
        .frame(width: Self.width, alignment: .leading)
        .allowsHitTesting(Self.hasButtons(state))
    }

    /// The answers show before the Yes; after it only the setting's button, and only when the words name one.
    static func hasButtons(_ state: ConnectSuggestPanelState) -> Bool {
        state.confirmedAt == nil || (state.result?.needsReading == true && state.result?.isFailure == false)
    }

    /// What Yes came to is a turned-on source (the ring closes and a check shows), not a refusal or a page opened.
    static func turnedOn(_ state: ConnectSuggestPanelState) -> Bool {
        if case .turnedOn? = state.result { return true }
        return false
    }

    /// The panel's title: the question; "Turning on…" while the Yes is at work; then what it came to.
    static func title(_ state: ConnectSuggestPanelState) -> String {
        guard state.confirmedAt != nil else { return Copy.ConnectSuggest.title(state.appName) }
        switch state.result {
        case nil: return Copy.ConnectSuggest.turningOn
        case .failed?: return Copy.ConnectSuggest.couldntTurnOn
        default: return Copy.ConnectSuggest.turnedOn
        }
    }

    /// The one line under it. Said only as true as it is: "will ask why" only when the site really will.
    static func line(_ state: ConnectSuggestPanelState) -> String {
        switch state.result {
        case .turnedOn(let asksWhy, let needsAccessibility)?:
            if needsAccessibility { return Copy.ConnectSuggest.needsAccessibility(state.appName) }
            if asksWhy { return Copy.ConnectSuggest.willAskWhy(state.appName) }
            return Copy.ConnectSuggest.reads(state.target)
        case .failed(let note)?:
            return note ?? Copy.ConnectSuggest.tryOnSources
        default:
            return state.keepsSave ? Copy.ConnectSuggest.keepsSave : Copy.ConnectSuggest.reads(state.target)
        }
    }

    /// The answers' size (owner 2026-11-23: "make the no, not now and yes buttons bigger"): the row face, in a pill whose
    /// whole shape takes the click — the padding is the button's, never air around it.
    static let answerFont: CGFloat = 14
    static let answerInsets = EdgeInsets(top: 9, leading: 16, bottom: 9, trailing: 16)

    /// One answer. Yes is the notch's one filled capsule (`chipSelected` with its ring); No and Not now are words of
    /// the same size, quieter by ink alone.
    private func answer(_ title: String, tone: Color, filled: Bool = false, action: @escaping () -> Void) -> some View {
        let insets = Self.answerInsets
        return Button(action: action) {
            Text(title)
                .font(CicadaTheme.font(size: Self.answerFont, weight: filled ? .semibold : .medium))
                .foregroundStyle(tone)
                .lineLimit(1)
                .fixedSize()
                .padding(.vertical, CicadaTheme.scaled(insets.top))
                .padding(.horizontal, CicadaTheme.scaled(filled ? insets.leading + 4 : insets.leading))
                .background(Capsule().fill(filled ? CicadaTheme.Notch.chipSelected : Color.clear))
                .overlay(Capsule().strokeBorder(filled ? CicadaTheme.Notch.chipSelectedRing : Color.clear, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
    }
}

/// G221 — "connected", drawn: a ring closing around the worm's head, then a check at its corner. One beat each, on
/// `CicadaMotion`'s clock; under Reduce Motion both are simply there.
private struct ConnectedRing: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var closed = false
    @State private var checked = false

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            Circle()
                .trim(from: 0, to: closed ? 1 : 0)
                .stroke(CicadaTheme.Notch.textPrimary, style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Image(systemName: "checkmark.circle.fill")
                .font(CicadaTheme.font(size: 12, weight: .semibold))
                .foregroundStyle(CicadaTheme.Notch.textPrimary)
                .opacity(checked ? 1 : 0)
        }
        .onAppear {
            withAnimation(CicadaMotion.connectRing(reduceMotion: reduceMotion)) { closed = true }
            withAnimation(CicadaMotion.connectCheck(reduceMotion: reduceMotion)) { checked = true }
        }
    }
}
