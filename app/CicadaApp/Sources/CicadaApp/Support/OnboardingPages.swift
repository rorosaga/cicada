import CoreGraphics
import SwiftUI

/// R-OB1 — the paged onboarding's six steps (G145). *See how* (F-03) is a sheet over Import, never a step.
enum OnboardingPage: Int, CaseIterable, Comparable {
    /// `skills` (owner 2026-10-15): after Agents — the skills that let those agents see websites and use apps.
    case welcome, `import`, agents, skills, whoReads, keepRunning, ready

    static let stepCount = 7
    static func < (a: OnboardingPage, b: OnboardingPage) -> Bool { a.rawValue < b.rawValue }

    var step: Int { rawValue + 1 }
    var next: OnboardingPage? { OnboardingPage(rawValue: rawValue + 1) }
    var previous: OnboardingPage? { OnboardingPage(rawValue: rawValue - 1) }
    /// Welcome and You're set are the room over a card; the working pages are the split frame, the room in its pane.
    var isSplit: Bool { self != .welcome && self != .ready }

    /// The worm's mood in onboarding's room (owner 2026-10-16: the study room replaced the paintings), so each step's
    /// room says what the step is about: awake to say hello, reading for what comes in and who reads it, happy to meet
    /// the agents and skills and when it is set, asleep for what keeps running while the Mac rests.
    var roomMood: BookwormState {
        switch self {
        case .welcome: .awake
        case .import, .whoReads: .reading
        case .agents, .skills, .ready: .happy
        case .keepRunning: .sleeping(stage: 1)
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

    /// The room's pane gives way before the column does, and goes rather than become a sliver: it is art only
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
