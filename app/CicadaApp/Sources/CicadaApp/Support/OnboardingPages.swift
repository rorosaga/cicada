import CoreGraphics
import SwiftUI

/// R-OB1 — the paged onboarding's six steps (G145). *See how* (F-03) is a sheet over Import, never a step.
enum OnboardingPage: Int, CaseIterable, Comparable {
    case welcome, `import`, agents, whoReads, keepRunning, ready

    static let stepCount = 6
    static func < (a: OnboardingPage, b: OnboardingPage) -> Bool { a.rawValue < b.rawValue }

    var step: Int { rawValue + 1 }
    var next: OnboardingPage? { OnboardingPage(rawValue: rawValue + 1) }
    var previous: OnboardingPage? { OnboardingPage(rawValue: rawValue - 1) }
    /// Welcome and You're set are the whole painting with a card; the working pages are the split frame.
    var isSplit: Bool { pane != nil }

    /// The page's painting in the split frame (ART_DIRECTION §4's framings).
    var pane: PaneFraming? {
        switch self {
        case .import: .import
        case .agents: .agents
        case .whoReads: .whoReads
        case .keepRunning: .keepRunning
        case .welcome, .ready: nil
        }
    }
}

enum OnboardingInput { case pointer, keyboard }

enum OnboardingNav {
    /// R-OB3 — DR-60: a key never animates; the pointer path narrows on the drawer curve (DR-61's column row),
    /// and Reduce Motion drops the movement (`CicadaMotion.columns`).
    static func animation(_ input: OnboardingInput, reduceMotion: Bool) -> Animation? {
        input == .keyboard ? nil : CicadaMotion.columns(reduceMotion: reduceMotion)
    }

    /// A topbar segment links to any page already reached — never past Get started before the owner is saved (R-OB2).
    static func canJump(to page: OnboardingPage, furthest: OnboardingPage, ownerSaved: Bool) -> Bool {
        page <= furthest && (page == .welcome || ownerSaved)
    }
}

/// R-OB1 — the frame's geometry (F-02's board: pane 540, column padding 64, topbar 52, foot 36 from the bottom).
enum OnboardingLayout {
    static let pane: CGFloat = 540
    static let minColumn: CGFloat = 620
    static let minPane: CGFloat = 240
    static let columnPadding: CGFloat = 64
    static let topbarHeight: CGFloat = 52
    static let footBottom: CGFloat = 36
    static let cardMaxWidth: CGFloat = 640
    static let cardBottom: CGFloat = 48
    static let gutter: CGFloat = 16
    static let twoColumnImport: CGFloat = 700

    /// The painting gives way before the column does, and goes rather than become a sliver: it is paint only
    /// (DR-13), so losing it loses no word.
    static func paneWidth(windowWidth w: CGFloat, scale: CGFloat) -> CGFloat {
        guard w > 0, scale > 0 else { return 0 }
        let width = min(pane * scale, w - minColumn * scale)
        return width < minPane * scale ? 0 : width
    }

    static func cardWidth(windowWidth w: CGFloat, scale: CGFloat) -> CGFloat {
        max(0, min(cardMaxWidth * scale, w - 2 * gutter * scale))
    }

    /// F-02's categories in two columns only when both fit.
    static func importColumns(columnWidth: CGFloat, scale: CGFloat) -> Int {
        columnWidth >= twoColumnImport * scale ? 2 : 1
    }
}
