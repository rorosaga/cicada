import SwiftUI
import XCTest
@testable import CicadaApp

/// G125 v3 Task 8 — the narrow guard on the numbers budget (R-A15, plan P19),
/// plus the motion budget's one testable half.
///
/// The broad form — "the set of numeric interpolations on this page equals the
/// budget table" — was refused on purpose: numbers reach the page through
/// `Copy.` helpers and `SleepHistoryPresentation.durationText(ms:)`, so such a
/// lint is falsified by the first refactor and then deleted, which is worse
/// than never having it. What a regex CAN hold is the one thing the reference
/// image got wrong: **a percentage always names what it is a percentage OF.**
/// The budget table in the plan is the reviewable artefact; this is its cheap
/// guard.
final class SleepNumbersLintTests: XCTestCase {

    /// `SleepMotion.swift` is the one file allowed to spell a duration — it is
    /// where the budget's numbers live. Same shape of exemption
    /// `FontLiteralLintTests` grants `Theme/CicadaTheme.swift`.
    static let motionFile = "SleepMotion.swift"

    /// `Sources/CicadaApp/Views/Sleep/**.swift`, reusing
    /// `ThemeTokenTests.swiftSources()` (the module's one enumerator, resolved
    /// from `#filePath` so it works from any working directory).
    static func sleepSources() throws -> [URL] {
        let all = try ThemeTokenTests.swiftSources().filter { $0.path.contains("/Views/Sleep/") }
        XCTAssertFalse(all.isEmpty, "found no sources under Views/Sleep — the lint would pass vacuously")
        return all
    }

    func testNoBarePercentReachesATextInTheSleepFolder() throws {
        // Every noun a percentage on this page is allowed to be OF. Adding one
        // here is a deliberate act — which is the point.
        let nouns = ["Rested", "Read", "volume", "age", "Stage"]
        for file in try Self.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                guard code.contains("Text("), code.contains("%") else { continue }
                XCTAssertTrue(nouns.contains { code.contains($0) },
                              "\(file.lastPathComponent):\(index + 1) renders a % with no noun (R-A5/R-A15)")
            }
        }
    }

    /// **One number, one place** (R-A5) — the round-2 live check's finding.
    /// The hero's labelled meter drew `Rested n%` and `SleepView`'s
    /// `moodDetailLine` drew `Rested n% — volume v%, age a%` two rows below
    /// it, so a reader saw the same percentage twice and had to work out
    /// whether they were the same reading. The breakdown moved to the meter
    /// label's hover text (`heroMeterHelp`), and this pins the number's one
    /// home the same way the `%`-with-a-noun lint pins its wording: the word
    /// may appear in prose anywhere, but only `SleepHero.swift` may spell it
    /// in code.
    func testTheRestedPercentageIsSpelledByExactlyOneFile() throws {
        var spelling: [String] = []
        for file in try Self.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let hit = text.components(separatedBy: .newlines).contains { line in
                let code = line.trimmingCharacters(in: .whitespaces)
                return !code.hasPrefix("//") && code.contains("Rested")
            }
            if hit { spelling.append(file.lastPathComponent) }
        }
        XCTAssertEqual(spelling.sorted(), ["SleepHero.swift"],
                       "`Rested n%` belongs to the hero meter's label and nowhere else (R-A5)")
    }

    // MARK: The motion budget (R-A13)

    /// Nothing on this page animates longer than 400 ms except the stage
    /// pulse, which is capped separately at 1.2 s by `SleepStages`. A budget
    /// stated only in a comment drifts; these are the numbers the comment
    /// names.
    func testEveryNamedDurationIsInsideTheBudget() {
        XCTAssertLessThanOrEqual(SleepMotion.settleDuration, SleepMotion.maxDuration)
        XCTAssertLessThanOrEqual(SleepMotion.pileDuration, SleepMotion.maxDuration)
        XCTAssertLessThanOrEqual(SleepMotion.disclosureDuration, SleepMotion.maxDuration)
        XCTAssertLessThanOrEqual(SleepMotion.maxDuration, 0.4)
        XCTAssertLessThanOrEqual(SleepStages.pulsePeriod, 1.2)
        // Track Z Z5 — the sentence cross-fade, and every beat (≤ 3 frames).
        XCTAssertLessThanOrEqual(SleepMotion.sentenceDuration, SleepMotion.maxDuration)
        XCTAssertLessThanOrEqual(SleepMotion.beatFrameInterval * Double(SleepMotion.maxBeatFrames),
                                 SleepMotion.maxDuration)
        XCTAssertEqual(SleepMotion.beatFrameInterval, BookwormSprites.reactionInterval,
                       "one beat clock — the sprite's and the page's")
        XCTAssertEqual(SleepMotion.answerDwell, .seconds(12))
    }

    /// Reduce Motion holds every animation at its terminal frame. `nil` is how
    /// SwiftUI spells "no transition — jump to the new value", which is
    /// exactly the terminal frame; the worm and the stage pulse reach the same
    /// place through `frameIndex(…reduceMotion:)` / `stagePulse(…)`.
    func testReduceMotionRemovesEveryTransition() {
        XCTAssertNil(SleepMotion.settle(reduceMotion: true))
        XCTAssertNil(SleepMotion.pile(reduceMotion: true))
        XCTAssertNil(SleepMotion.disclosure(reduceMotion: true))
        XCTAssertNotNil(SleepMotion.settle(reduceMotion: false))
        XCTAssertNotNil(SleepMotion.pile(reduceMotion: false))
        XCTAssertNotNil(SleepMotion.disclosure(reduceMotion: false))
        XCTAssertNil(SleepMotion.sentence(reduceMotion: true))
        XCTAssertNotNil(SleepMotion.sentence(reduceMotion: false))
    }

    /// Design §10 — the pointer is read in ONE place under `Views/Sleep/`, the
    /// room box (`StudyRoom.swift`); every other leaf observes the model.
    func testOnlyTheRoomReadsTheContinuousPointer() throws {
        var readers: [String] = []
        for file in try Self.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let hit = text.components(separatedBy: .newlines).contains {
                let code = $0.trimmingCharacters(in: .whitespaces)
                return !code.hasPrefix("//") && code.contains("onContinuousHover")
            }
            if hit { readers.append(file.lastPathComponent) }
        }
        XCTAssertEqual(readers, ["StudyRoom.swift"])
    }

    /// R-Z4 — all worm motion is sprite frames on the one lattice: no
    /// `.offset`, `.scaleEffect`, `.rotationEffect` or `.spring(` hangs off a
    /// `BookwormView(` or `WormStage(` under `Views/Sleep/`. The one allowed
    /// form is the lattice placement itself — an `.offset(` built from
    /// `wormOrigin`, which is a whole number of cells by construction.
    func testTheWormIsNeverTransformed() throws {
        var chains = 0
        for file in try Self.sleepSources() {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            var i = 0
            while i < lines.count {
                let code = lines[i].trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains("BookwormView(") || code.contains("WormStage(") else {
                    i += 1; continue
                }
                // The call itself (to its closing paren), then every following
                // line that is a modifier (starts with ".") or a comment.
                var chain = [lines[i]]
                var depth = lines[i].filter { $0 == "(" }.count - lines[i].filter { $0 == ")" }.count
                i += 1
                while i < lines.count, depth > 0 {
                    chain.append(lines[i])
                    depth += lines[i].filter { $0 == "(" }.count - lines[i].filter { $0 == ")" }.count
                    i += 1
                }
                while i < lines.count {
                    let next = lines[i].trimmingCharacters(in: .whitespaces)
                    guard next.hasPrefix(".") || next.hasPrefix("//") else { break }
                    chain.append(lines[i]); i += 1
                }
                chains += 1
                for line in chain where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                    for needle in [".scaleEffect(", ".rotationEffect(", ".spring("] {
                        XCTAssertFalse(line.contains(needle), "\(file.lastPathComponent): \(line)")
                    }
                    if line.contains(".offset(") {
                        XCTAssertTrue(line.contains("wormOrigin"), "\(file.lastPathComponent): \(line)")
                    }
                }
            }
        }
        XCTAssertGreaterThan(chains, 0, "found no worm — the lint would pass vacuously")
    }

    /// The two value-driven bars on this page (the hero meter's blocks and the
    /// strip's Read fill) went through a literal `.easeInOut(duration: 0.35)`
    /// that ignored Reduce Motion. They route through `SleepMotion` now, and
    /// this pins that no literal came back — the same shape of guard
    /// `FontLiteralLintTests` uses for `.system(size:)`.
    func testTheSleepFolderDeclaresNoLiteralAnimationDuration() throws {
        for file in try Self.sleepSources() where file.lastPathComponent != Self.motionFile {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                XCTAssertFalse(code.contains("duration:"),
                               "\(file.lastPathComponent):\(index + 1) hardcodes an animation duration — "
                               + "route it through SleepMotion so Reduce Motion reaches it (R-A13).")
            }
        }
    }
}
