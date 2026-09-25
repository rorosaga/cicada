import CoreGraphics
import Foundation

/// R-OB21 — what a drawn browser shows over its page, as neutral wireframe shapes only (F-03: never a screenshot or a
/// copy of a vendor's UI).
enum ExportOverlay: String, Equatable, CaseIterable {
    case menu, settings, dialog, mail, download, productList, optionsPopup, delivery
}

struct ExportStep: Equatable {
    /// ≤ 8 words, from chat-exports.md.
    let caption: String
    /// The click target in the drawn page's unit space (0…1 across the page below the address bar).
    let target: CGRect
    /// How close the camera comes; 1 is the whole window.
    let zoom: CGFloat
    var overlay: ExportOverlay? = nil
}

struct ExportScene: Equatable {
    let vendor: ChatVendor
    /// The address bar and the sheet's footer: the vendor's own host.
    let host: String
    let path: String
    let honestLine: String
    let steps: [ExportStep]
    /// The one table of export links (`WalkthroughVendor`), never a second.
    var exportURL: URL { vendor.walkthrough.exportURL }
}

/// Where the drawn page's parts sit — one wireframe the three scenes share.
enum ExportTargets {
    static let avatar = CGRect(x: 0.02, y: 0.88, width: 0.06, height: 0.08)
    static let menuSettings = CGRect(x: 0.03, y: 0.66, width: 0.20, height: 0.05)
    static let settingsTab = CGRect(x: 0.23, y: 0.30, width: 0.14, height: 0.05)
    static let exportButton = CGRect(x: 0.66, y: 0.44, width: 0.10, height: 0.06)
    static let confirmButton = CGRect(x: 0.52, y: 0.56, width: 0.12, height: 0.06)
    static let mail = CGRect(x: 0.62, y: 0.04, width: 0.34, height: 0.14)
    static let download = CGRect(x: 0.62, y: 0.84, width: 0.34, height: 0.10)
    static let takeoutHeader = CGRect(x: 0.30, y: 0.02, width: 0.40, height: 0.06)
    static let deselectAll = CGRect(x: 0.74, y: 0.14, width: 0.12, height: 0.05)
    static let myActivityRow = CGRect(x: 0.20, y: 0.52, width: 0.50, height: 0.06)
    static let myActivityOptions = CGRect(x: 0.62, y: 0.52, width: 0.14, height: 0.06)
    static let geminiAppsRow = CGRect(x: 0.36, y: 0.46, width: 0.30, height: 0.06)
    static let nextStep = CGRect(x: 0.74, y: 0.88, width: 0.14, height: 0.06)
    static let deliveryRow = CGRect(x: 0.20, y: 0.30, width: 0.40, height: 0.06)
    static let frequencyRow = CGRect(x: 0.20, y: 0.46, width: 0.40, height: 0.06)
    static let formatRow = CGRect(x: 0.20, y: 0.62, width: 0.40, height: 0.06)
    static let createExport = CGRect(x: 0.66, y: 0.84, width: 0.18, height: 0.06)
}

struct WalkthroughFrame: Equatable {
    let step: Int
    let scale: CGFloat
    /// The unit point the camera centres.
    let focus: CGPoint
    /// Nil under Reduce Motion.
    let pointer: CGPoint?
    let ringOpacity: Double
    let overlay: ExportOverlay?
}

enum ExportWalkthrough {
    static func scene(_ vendor: ChatVendor) -> ExportScene {
        switch vendor {
        case .claude: claude
        case .chatgpt: chatgpt
        case .gemini: gemini
        }
    }

    static var allCaptions: [String] { ChatVendor.allCases.flatMap { scene($0).steps.map(\.caption) } }

    static let claude = ExportScene(vendor: .claude, host: "claude.ai", path: Copy.seeHowClaudePath,
                                    honestLine: Copy.seeHowClaudeHonest, steps: [
        ExportStep(caption: "Open your account menu.", target: ExportTargets.avatar, zoom: 1.8),
        ExportStep(caption: "Click Settings.", target: ExportTargets.menuSettings, zoom: 1.8, overlay: .menu),
        ExportStep(caption: "Go to Privacy.", target: ExportTargets.settingsTab, zoom: 1.6, overlay: .settings),
        ExportStep(caption: "Click Export data.", target: ExportTargets.exportButton, zoom: 1.8, overlay: .settings),
        ExportStep(caption: "Confirm the export.", target: ExportTargets.confirmButton, zoom: 1.8, overlay: .dialog),
        ExportStep(caption: "Check your email.", target: ExportTargets.mail, zoom: 1.6, overlay: .mail),
        ExportStep(caption: "Download within 24 hours.", target: ExportTargets.download, zoom: 1.6, overlay: .download),
    ])

    static let chatgpt = ExportScene(vendor: .chatgpt, host: "chatgpt.com", path: Copy.seeHowChatGPTPath,
                                     honestLine: Copy.seeHowChatGPTHonest, steps: [
        ExportStep(caption: "Open your profile menu.", target: ExportTargets.avatar, zoom: 1.8),
        ExportStep(caption: "Click Settings.", target: ExportTargets.menuSettings, zoom: 1.8, overlay: .menu),
        ExportStep(caption: "Select Data controls.", target: ExportTargets.settingsTab, zoom: 1.6, overlay: .settings),
        ExportStep(caption: "Find Export data, click Export.", target: ExportTargets.exportButton, zoom: 1.8,
                   overlay: .settings),
        ExportStep(caption: "Confirm export on the next screen.", target: ExportTargets.confirmButton, zoom: 1.8,
                   overlay: .dialog),
        ExportStep(caption: "Wait for email or text.", target: ExportTargets.mail, zoom: 1.6, overlay: .mail),
        ExportStep(caption: "Download within 24 hours.", target: ExportTargets.download, zoom: 1.6, overlay: .download),
    ])

    static let gemini = ExportScene(vendor: .gemini, host: "takeout.google.com", path: Copy.seeHowGeminiPath,
                                    honestLine: Copy.seeHowGeminiHonest, steps: [
        ExportStep(caption: "Open Google Takeout.", target: ExportTargets.takeoutHeader, zoom: 1.4, overlay: .productList),
        ExportStep(caption: "Click Deselect all.", target: ExportTargets.deselectAll, zoom: 1.8, overlay: .productList),
        ExportStep(caption: "Scroll to My Activity, check it.", target: ExportTargets.myActivityRow, zoom: 1.6,
                   overlay: .productList),
        ExportStep(caption: "Open My Activity options.", target: ExportTargets.myActivityOptions, zoom: 1.8,
                   overlay: .productList),
        ExportStep(caption: "Deselect all, then check Gemini Apps.", target: ExportTargets.geminiAppsRow, zoom: 1.8,
                   overlay: .optionsPopup),
        ExportStep(caption: "Click OK, then Next step.", target: ExportTargets.nextStep, zoom: 1.6, overlay: .productList),
        ExportStep(caption: "Choose delivery: email link.", target: ExportTargets.deliveryRow, zoom: 1.6, overlay: .delivery),
        ExportStep(caption: "Set frequency: Export once.", target: ExportTargets.frequencyRow, zoom: 1.6, overlay: .delivery),
        ExportStep(caption: "Pick .zip and file size.", target: ExportTargets.formatRow, zoom: 1.6, overlay: .delivery),
        ExportStep(caption: "Click Create export.", target: ExportTargets.createExport, zoom: 1.8, overlay: .delivery),
        ExportStep(caption: "Wait, then check email.", target: ExportTargets.mail, zoom: 1.6, overlay: .mail),
    ])

    private static let home = CGPoint(x: 0.5, y: 0.5)

    /// The camera at `elapsed` seconds into the loop: one step every `walkthroughStep`, the camera gliding from the
    /// last step's hold to this one's in `walkthroughGlide`, the pointer landing by `walkthroughPointer`, the ring
    /// pulsing once after. Reduce Motion: the whole window, no pointer, the target ringed in place.
    static func frame(at elapsed: TimeInterval, scene: ExportScene, reduceMotion: Bool) -> WalkthroughFrame {
        let steps = scene.steps
        guard !steps.isEmpty else {
            return WalkthroughFrame(step: 0, scale: 1, focus: home, pointer: nil, ringOpacity: 0, overlay: nil)
        }
        let period = CicadaMotion.walkthroughStep
        let t = max(0, elapsed).truncatingRemainder(dividingBy: Double(steps.count) * period)
        let index = min(Int(t / period), steps.count - 1)
        let local = t - Double(index) * period
        let step = steps[index]
        guard !reduceMotion else {
            return WalkthroughFrame(step: index, scale: 1, focus: home, pointer: nil, ringOpacity: 1, overlay: step.overlay)
        }
        let target = CGPoint(x: step.target.midX, y: step.target.midY)
        let fromFocus = index == 0 ? home : center(steps[index - 1].target)
        let fromScale: CGFloat = index == 0 ? 1 : steps[index - 1].zoom
        let glide = CGFloat(ease(min(local / CicadaMotion.walkthroughGlide, 1)))
        let arrive = CGFloat(ease(min(local / CicadaMotion.walkthroughPointer, 1)))
        let fromPointer = index == 0 ? CGPoint(x: 0.5, y: 0.6) : fromFocus
        return WalkthroughFrame(step: index,
                                scale: fromScale + (step.zoom - fromScale) * glide,
                                focus: lerp(fromFocus, target, glide),
                                pointer: lerp(fromPointer, target, arrive),
                                ringOpacity: ringOpacity(local),
                                overlay: step.overlay)
    }

    /// Smoothstep: the camera eases in and out, never linear.
    static func ease(_ x: Double) -> Double { x * x * (3 - 2 * x) }

    /// One pulse after the pointer lands, zero outside it.
    static func ringOpacity(_ local: TimeInterval) -> Double {
        let window = CicadaMotion.walkthroughRing
        guard window.contains(local) else { return 0 }
        return sin(.pi * (local - window.lowerBound) / (window.upperBound - window.lowerBound))
    }

    private static func center(_ r: CGRect) -> CGPoint { CGPoint(x: r.midX, y: r.midY) }
    private static func lerp(_ a: CGPoint, _ b: CGPoint, _ p: CGFloat) -> CGPoint {
        CGPoint(x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p)
    }
}

/// The camera over the drawn page: scaled from the top-leading corner, offset to centre the focus, clamped so the
/// page's edge never shows.
enum WalkthroughGeometry {
    static func offset(size: CGSize, scale: CGFloat, focus: CGPoint) -> CGSize {
        let w = size.width, h = size.height
        let dx = w / 2 - focus.x * w * scale
        let dy = h / 2 - focus.y * h * scale
        return CGSize(width: min(0, max(w - w * scale, dx)), height: min(0, max(h - h * scale, dy)))
    }
}
