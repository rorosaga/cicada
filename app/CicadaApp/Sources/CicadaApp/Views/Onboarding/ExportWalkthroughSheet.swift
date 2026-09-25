import AppKit
import SwiftUI

/// F-03 (G145; owner: "a see how video per provider that shows a browser like zooming into each step … with a button
/// to take you to the website") — a floating sheet over Import (DR-9/DR-10, `floatingSurface`): text tabs Claude ·
/// ChatGPT · Gemini with their real marks (DR-45, DR-52), a DRAWN browser — neutral wireframe shapes, the vendor
/// only as its mark and name in the tab and its host in the address bar, never a screenshot or a copy of its UI —
/// walked by `ExportWalkthrough.frame`, the step's caption, a counter and pips, Replay, and one primary that opens the
/// provider's export page (`WalkthroughVendor.exportURL`). *Remind me* (R-IB22) sits in the footer. R-OB21.
struct ExportWalkthroughSheet: View {
    @State var vendor: ChatVendor
    let onClose: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var start = Date()

    var body: some View {
        let scene = ExportWalkthrough.scene(vendor)
        ZStack {
            CicadaTheme.scrim.ignoresSafeArea().onTapGesture(perform: onClose)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                header(scene)
                TimelineView(.animation(minimumInterval: SceneRunPolicy.frameInterval(lowPower: false))) { context in
                    let frame = ExportWalkthrough.frame(at: context.date.timeIntervalSince(start), scene: scene,
                                                        reduceMotion: reduceMotion)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        DrawnBrowser(scene: scene, frame: frame)
                            .aspectRatio(16 / 8, contentMode: .fit)
                        stepLine(scene, frame: frame)
                    }
                    .animation(CicadaMotion.walkthroughOverlay(reduceMotion: reduceMotion), value: frame.overlay)
                    .animation(reduceMotion ? CicadaMotion.fade : nil, value: frame.step)
                }
                Text(scene.honestLine).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                footer(scene)
            }
            .padding(CicadaTheme.spacingXL)
            .frame(width: CicadaTheme.scaled(760))
            .floatingSurface(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        }
        .onExitCommand(perform: onClose)
        .onChange(of: vendor) { _, _ in start = Date() }
    }

    private func header(_ scene: ExportScene) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack {
                Text(Copy.seeHowTitle)
                    .font(CicadaTheme.displayFont(size: 22))
                    .tracking(CicadaTheme.displayTracking(size: 22))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                IconButton(systemName: "xmark", help: Copy.seeHowDone, action: onClose)
            }
            HStack {
                ForEach(ChatVendor.allCases) { v in
                    Button { vendor = v } label: {
                        HStack(spacing: CicadaTheme.spacingXS) {
                            VendorMark(vendor: v, size: CicadaTheme.scaled(14))
                            Text(v.title).font(CicadaTheme.font(size: 13, weight: v == vendor ? .medium : .regular))
                        }
                        .padding(.horizontal, CicadaTheme.scaled(9))
                        .frame(height: CicadaTheme.scaled(TextTabs<ChatVendor>.height))
                        .background(v == vendor ? CicadaTheme.bgSelected : Color.clear,
                                    in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(v == vendor ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .accessibilityAddTraits(v == vendor ? .isSelected : [])
                }
                Spacer()
                Text(Copy.seeHowSteps(scene.steps.count)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func stepLine(_ scene: ExportScene, frame: WalkthroughFrame) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.seeHowStepOf(frame.step + 1, scene.steps.count)).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary).monospacedDigit()
                Text(scene.steps[frame.step].caption).font(CicadaTheme.font(size: 15, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.updatesFrequently)
                Spacer()
                TextButton(title: Copy.seeHowReplay) { start = Date() }
            }
            HStack(spacing: CicadaTheme.scaled(4)) {
                ForEach(0..<scene.steps.count, id: \.self) { i in
                    Capsule().fill(i <= frame.step ? CicadaTheme.textSecondary : CicadaTheme.bgSelected)
                        .frame(height: CicadaTheme.scaled(3))
                }
            }
            .accessibilityHidden(true)
        }
    }

    private func footer(_ scene: ExportScene) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            TextButton(title: Copy.seeHowDone, action: onClose)
            ExportReminderMenu(vendor: scene.vendor)
            Spacer()
            // Through Copy: a `Text("\(…)")` in Views/Onboarding/ trips CountLiteralLintTests (its scope).
            Text(Copy.seeHowWhere(host: scene.host, path: scene.path)).font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            PrimaryActionButton(title: Copy.seeHowOpenPage(scene.vendor.title), systemImage: "arrow.up.right.square") {
                NSWorkspace.shared.open(scene.exportURL)
            }
        }
    }
}

/// The drawn browser: a tab with the vendor's real mark and name, an address bar with its host, and the page as
/// neutral bars (graphite tokens only), under a camera. The pointer is the system's own arrow glyph; the click ring
/// is a neutral stroke (DR-5: never the accent).
private struct DrawnBrowser: View {
    let scene: ExportScene
    let frame: WalkthroughFrame

    var body: some View {
        VStack(spacing: 0) {
            chrome
            GeometryReader { geo in
                let size = geo.size
                ZStack(alignment: .topLeading) {
                    WireframePage(overlay: frame.overlay, gemini: scene.vendor == .gemini, size: size)
                    // `frame.step` is always a valid index (`ExportWalkthrough.frame` clamps it).
                    let target = scene.steps[frame.step].target
                    CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)   // DR-12: continuous, never a bare RoundedRectangle
                        .strokeBorder(CicadaTheme.textPrimary.opacity(frame.ringOpacity), lineWidth: 2)
                        .frame(width: target.width * size.width + 8, height: target.height * size.height + 8)
                        .offset(x: target.minX * size.width - 4, y: target.minY * size.height - 4)
                    if let pointer = frame.pointer {
                        Image(systemName: "cursorarrow")
                            .font(CicadaTheme.font(size: 18))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .offset(x: pointer.x * size.width, y: pointer.y * size.height)
                    }
                }
                .frame(width: size.width, height: size.height, alignment: .topLeading)
                .scaleEffect(frame.scale, anchor: .topLeading)
                .offset(WalkthroughGeometry.offset(size: size, scale: frame.scale, focus: frame.focus))
                .clipped()
            }
        }
        .background(CicadaTheme.bgBase)
        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .accessibilityHidden(true)   // the caption is its text twin (DR-69)
    }

    private var chrome: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingXS) {
                VendorMark(vendor: scene.vendor, size: CicadaTheme.scaled(12))
                Text(scene.vendor.title).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(22))
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            Text(scene.host).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .frame(maxWidth: .infinity, alignment: .leading)
                .frame(height: CicadaTheme.scaled(22))
                .background(CicadaTheme.bgPane, in: Capsule())
        }
        .padding(CicadaTheme.spacingXS)
        .background(CicadaTheme.bgPane)
    }
}

/// The drawn page under the camera: neutral wireframe shapes only, in the page's unit space (`ExportTargets`), so a
/// target the walkthrough points at is always a shape that is drawn (R-OB21). No text — the vendor lives only in the
/// browser's tab and address bar (F-03: never a copy of anyone's UI). Every shape is continuous (DR-12) and filled with
/// a graphite token (DR-3), and each overlay crossfades in (`.transition(.opacity)`, timed by the sheet).
private struct WireframePage: View {
    let overlay: ExportOverlay?
    let gemini: Bool
    let size: CGSize

    var body: some View {
        ZStack(alignment: .topLeading) {
            if gemini { takeoutBase } else { chatBase }
            if let overlay {
                overlayView(overlay)
                    .transition(.opacity)
                    .id(overlay)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
    }

    // MARK: Base pages

    /// A chat app: a side panel with four bars and the avatar at its foot, conversation bars and a composer.
    private var chatBase: some View {
        ZStack(alignment: .topLeading) {
            box(CGRect(x: 0, y: 0, width: 0.28, height: 1), fill: CicadaTheme.bgPane, ring: false)
            ForEach(0..<4, id: \.self) { i in
                bar(CGRect(x: 0.03, y: 0.08 + Double(i) * 0.08, width: 0.20, height: 0.04))
            }
            circle(ExportTargets.avatar)
            ForEach(0..<3, id: \.self) { i in
                bar(CGRect(x: 0.36, y: 0.14 + Double(i) * 0.14, width: i == 1 ? 0.36 : 0.52, height: 0.05))
            }
            box(CGRect(x: 0.36, y: 0.80, width: 0.56, height: 0.12), fill: CicadaTheme.bgFocus)
        }
    }

    /// Takeout: a header and a column of product rows, each with a checkbox.
    private var takeoutBase: some View {
        ZStack(alignment: .topLeading) {
            bar(ExportTargets.takeoutHeader)
            ForEach(0..<6, id: \.self) { i in
                bar(CGRect(x: 0.20, y: 0.24 + Double(i) * 0.10, width: 0.50, height: 0.05))
            }
        }
    }

    // MARK: Overlays

    @ViewBuilder
    private func overlayView(_ overlay: ExportOverlay) -> some View {
        switch overlay {
        case .menu:
            ZStack(alignment: .topLeading) {
                box(CGRect(x: 0.02, y: 0.50, width: 0.24, height: 0.36), fill: CicadaTheme.bgMenu)
                ForEach(0..<4, id: \.self) { i in
                    bar(CGRect(x: 0.04, y: 0.54 + Double(i) * 0.075, width: 0.18, height: 0.035))
                }
                box(ExportTargets.menuSettings, fill: CicadaTheme.bgSelected, ring: false)
            }
        case .settings:
            ZStack(alignment: .topLeading) {
                box(CGRect(x: 0.2, y: 0.12, width: 0.6, height: 0.76), fill: CicadaTheme.bgMenu)
                ForEach(0..<4, id: \.self) { i in
                    bar(CGRect(x: 0.23, y: 0.18 + Double(i) * 0.08, width: 0.14, height: 0.04))
                }
                box(ExportTargets.settingsTab, fill: CicadaTheme.bgSelected, ring: false)
                ForEach(0..<3, id: \.self) { i in
                    bar(CGRect(x: 0.42, y: 0.20 + Double(i) * 0.12, width: 0.30, height: 0.04))
                }
                box(ExportTargets.exportButton, fill: CicadaTheme.bgFocus)
            }
        case .dialog:
            ZStack(alignment: .topLeading) {
                box(CGRect(x: 0.33, y: 0.35, width: 0.34, height: 0.3), fill: CicadaTheme.bgMenu)
                bar(CGRect(x: 0.36, y: 0.40, width: 0.24, height: 0.04))
                bar(CGRect(x: 0.36, y: 0.47, width: 0.18, height: 0.03))
                box(ExportTargets.confirmButton, fill: CicadaTheme.bgFocus)
            }
        case .mail:
            ZStack(alignment: .topLeading) {
                box(ExportTargets.mail, fill: CicadaTheme.bgMenu)
                bar(CGRect(x: ExportTargets.mail.minX + 0.02, y: ExportTargets.mail.minY + 0.03,
                           width: 0.20, height: 0.03))
                bar(CGRect(x: ExportTargets.mail.minX + 0.02, y: ExportTargets.mail.minY + 0.08,
                           width: 0.26, height: 0.03))
            }
        case .download:
            ZStack(alignment: .topLeading) {
                box(ExportTargets.download, fill: CicadaTheme.bgMenu)
                bar(CGRect(x: ExportTargets.download.minX + 0.02, y: ExportTargets.download.minY + 0.035,
                           width: 0.22, height: 0.03))
            }
        case .productList:
            ZStack(alignment: .topLeading) {
                box(ExportTargets.deselectAll, fill: CicadaTheme.bgFocus)
                box(ExportTargets.myActivityRow, fill: CicadaTheme.bgSelected, ring: false)
                box(ExportTargets.myActivityOptions, fill: CicadaTheme.bgFocus)
                box(ExportTargets.nextStep, fill: CicadaTheme.bgFocus)
            }
        case .optionsPopup:
            ZStack(alignment: .topLeading) {
                box(CGRect(x: 0.32, y: 0.24, width: 0.38, height: 0.52), fill: CicadaTheme.bgMenu)
                ForEach(0..<4, id: \.self) { i in
                    bar(CGRect(x: 0.36, y: 0.30 + Double(i) * 0.10, width: 0.26, height: 0.04))
                }
                box(ExportTargets.geminiAppsRow, fill: CicadaTheme.bgSelected, ring: false)
            }
        case .delivery:
            ZStack(alignment: .topLeading) {
                box(CGRect(x: 0.16, y: 0.22, width: 0.72, height: 0.72), fill: CicadaTheme.bgMenu)
                box(ExportTargets.deliveryRow, fill: CicadaTheme.bgFocus)
                box(ExportTargets.frequencyRow, fill: CicadaTheme.bgFocus)
                box(ExportTargets.formatRow, fill: CicadaTheme.bgFocus)
                box(ExportTargets.createExport, fill: CicadaTheme.bgSelected)
            }
        }
    }

    // MARK: Shapes

    private func box(_ r: CGRect, fill: Color, ring: Bool = true) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
        return Group {
            if ring {
                shape.fill(fill).ringed(in: shape)
            } else {
                shape.fill(fill)
            }
        }
        .frame(width: r.width * size.width, height: r.height * size.height)
        .offset(x: r.minX * size.width, y: r.minY * size.height)
    }

    private func bar(_ r: CGRect) -> some View {
        Capsule().fill(CicadaTheme.bgSelected)
            .frame(width: r.width * size.width, height: r.height * size.height)
            .offset(x: r.minX * size.width, y: r.minY * size.height)
    }

    private func circle(_ r: CGRect) -> some View {
        let d = min(r.width * size.width, r.height * size.height)
        return Circle().fill(CicadaTheme.bgSelected)
            .frame(width: d, height: d)
            .offset(x: r.minX * size.width, y: r.minY * size.height)
    }
}
