import CoreGraphics
import SwiftUI

/// Onboarding v2 (G217, G92, ruling 36 D1/D6; 2026-10-22) — six steps, one verb each, a visible Skip on the working
/// steps: Welcome · Intelligence · Agents · Sources · Meet your bookworm · Done. *See how* is a sheet over Sources,
/// never a step. *Meet your bookworm* (owner 2026-10-23) explains the menu-bar worm's number before the worm appears:
/// it comes after Sources, because what Sources brings in is what the number counts, and right before Done, so the
/// worm lands in the menu bar as setup closes (`MenuBarIntro`).
/// It replaced the seven-step flow (Import, Agents, Skills, Who reads, Keep it running); `init(stored:)` maps every
/// name either flow could have stored, so a person who quit mid-way on any build resumes on the nearest step.
enum OnboardingPage: Int, CaseIterable, Comparable {
    case welcome, intelligence, agents, sources, menuBar, done

    static let stepCount = allCases.count
    static func < (a: OnboardingPage, b: OnboardingPage) -> Bool { a.rawValue < b.rawValue }

    var step: Int { rawValue + 1 }
    var next: OnboardingPage? { OnboardingPage(rawValue: rawValue + 1) }
    var previous: OnboardingPage? { OnboardingPage(rawValue: rawValue - 1) }
    /// Welcome and Done are the room over a card, and *Meet your bookworm* the big menu-bar worm over a card; the
    /// working steps are the split frame, the room in its pane.
    var isSplit: Bool { self != .welcome && self != .done && self != .menuBar }
    /// The working steps carry a visible Skip (design-refs pattern 12): nothing on them is required. The worm's step
    /// too — skipping it still puts the worm in the menu bar, without the flight.
    var skippable: Bool { isSplit || self == .menuBar }

    /// The name a step is stored under (`OnboardingState.savedStep`) — a word, never the raw value, so a reorder
    /// never moves a stored step.
    var storedName: String {
        switch self {
        case .welcome: "welcome"
        case .intelligence: "intelligence"
        case .agents: "agents"
        case .sources: "sources"
        case .menuBar: "menuBar"
        case .done: "done"
        }
    }

    /// Hyrum mode B: every step name a build could have stored, mapped to the step that now holds its job. The
    /// seven-step flow's Import became Sources, Who reads became Intelligence, and Skills and Keep it running (gone
    /// from onboarding; both live on in the Skills page and Settings → General) land on the step after them.
    init?(stored: String) {
        switch stored {
        case "welcome": self = .welcome
        case "intelligence", "whoReads": self = .intelligence
        case "agents": self = .agents
        case "sources", "import", "skills": self = .sources
        case "menuBar": self = .menuBar
        case "done", "ready", "keepRunning": self = .done
        default: return nil
        }
    }

    /// The worm's mood in onboarding's room (owner 2026-10-16: the study room is onboarding's one illustration,
    /// DR-13): awake to say hello, reading for who reads and what comes in, happy to meet the agents and when set.
    var roomMood: BookwormState {
        switch self {
        case .welcome: .awake
        case .intelligence, .sources: .reading
        case .agents, .done: .happy
        // No room on this step — the menu-bar worm itself is the picture; its mood is the illustration's.
        case .menuBar: .happy
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
    /// The Sources grid's tile: wide enough for its two-line consent caption at 1×, so a 532 pt column holds 3.
    static let sourceTile: CGFloat = 150
    /// One height for every tile (looks pass 2026-10-23): a row of tiles sized to its longest caption made the grid's
    /// rows 100, 135 and 76 pt tall. The mark, the title, a two-line caption and the status line fit.
    static let sourceTileHeight: CGFloat = 128

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
}
