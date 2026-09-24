import XCTest
@testable import CicadaApp

/// R-S18 — the durable half of critique B1.
///
/// Three number-formatting conventions shared one window: the card grid printed
/// "1,035 entities" through a `UsageFormat.count` pinned to `en_US_POSIX`,
/// while Contributors, eight inches below, printed "1.927 files" from a bare
/// `Text("\(contributor.fileCount) files")` — which, being a
/// `LocalizedStringKey`, grouped the `Int` in the VIEWER's locale. One half was
/// consistent and locale-wrong, the other locale-right and inconsistent.
///
/// R-S17 fixed the formatter. This fixes the *next* one: a behavior test cannot
/// see a literal in a diff, only a source lint can — the same reasoning
/// `FontLiteralLintTests` states for `.system(size:)` (G130 R3).
///
/// **Scope is named, not global** (R-S18). A whole-tree lint would drown in
/// legitimate label interpolations — `Text("Removed from \(source.label)")` is
/// not a number — get noisy, and then get disabled. So it walks the places
/// Track S and Track I own, and every line it flags has an escape hatch that must state a
/// reason: a needle that tries to tell an `Int` from a `String` by variable name
/// would be guessing.
final class CountLiteralLintTests: XCTestCase {

    /// R-S18's four paths — two directories and two files, because
    /// `IntegrationCategory.swift` and `SourceOverview.swift` compose the same
    /// counts outside `Views/` — plus `Views/Home/` (Track I part b, R-IB9):
    /// Home is a page of numbers, each shown once, so it formats them the same
    /// way the Sources grid does — and `Views/Onboarding/` (Task 4): the
    /// Welcome's start line and its dropped-export rows carry counts too — and
    /// `Views/Shell/` (DS-1 T3): the rail's Inbox numeral and its "6 pending" label —
    /// and the two list-header components (DS-1 T5, DR-25/DR-45): a tab's count and
    /// the eyebrow's "6 pending" are the numbers every list page will show first — and the Inbox's
    /// columns and the Reader (DS-2, R-DI23): positions, counts and ages on every row — and the Graph's
    /// views (DS-3a): the Legend's counts and the entity column's tab counts — and the D list
    /// pages (DS-3c): Clusters' counts and the list pages' words.
    static let scope = [
        "/Views/Sources/",
        "/Views/Contributors/",
        "/Models/SourceOverview.swift",
        "/Models/IntegrationCategory.swift",
        "/Views/Home/",
        "/Views/Onboarding/",
        "/Views/Shell/",
        "/Views/Common/TextTabs.swift",
        "/Views/Common/EyebrowRow.swift",
        "/Views/Inbox/",
        "/Views/Provenance/ReaderColumn.swift",
        "/Views/Graph/",
        "/Views/Clusters/",
        "/Views/Feed/",
        "/Theme/Copy+Lists.swift",
    ]

    /// The documented way out, for a line the needle flags but that renders no
    /// number. The reason is required by convention (and by review), not by the
    /// regex — a bare marker with no `—` clause is still a deliberate act, which
    /// is the property that matters.
    static let escapeHatch = "count-lint:ok"

    /// Reuses `ThemeTokenTests.swiftSources()` — the module's ONE enumerator,
    /// resolved from `#filePath` so it works from any working directory.
    /// `FontLiteralLintTests` has its own copy only because its `sourceFiles()`
    /// is `private`; a third walker would be a third thing to keep correct.
    /// `SleepNumbersLintTests.sleepSources()` filters the same way.
    static func scopedSources() throws -> [URL] {
        let all = try ThemeTokenTests.swiftSources()
            .filter { url in scope.contains { url.path.contains($0) } }
        XCTAssertFalse(all.isEmpty, "found no sources in R-S18's scope — the lint would pass vacuously")
        return all
    }

    func testEveryInterpolatedTextInScopeGoesThroughUsageFormat() throws {
        for file in try Self.scopedSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                // A docstring quoting the defect it fixes is not the defect.
                guard !code.hasPrefix("//") else { continue }
                guard code.contains("Text(\""), code.contains("\\(") else { continue }
                guard !code.contains("UsageFormat."), !code.contains(Self.escapeHatch) else { continue }
                XCTFail(
                    "\(file.lastPathComponent):\(index + 1) interpolates into a Text without "
                    + "UsageFormat — route the number through UsageFormat.count(_:locale:) so it "
                    + "groups in the reader's locale, or mark the line "
                    + "`// \(Self.escapeHatch) — <reason>` if it renders no number (R-S5/R-S18)."
                )
            }
        }
    }

    /// The scope filter is itself the thing most likely to rot: a renamed
    /// directory would make `scopedSources()` return a smaller set that still
    /// passes the non-empty guard, and the lint would quietly stop watching
    /// half its ground. Pin every path in the scope by its known inhabitants.
    func testTheScopeActuallyCoversAllFourPaths() throws {
        let paths = try Self.scopedSources().map(\.path)
        for fragment in Self.scope {
            XCTAssertTrue(paths.contains { $0.contains(fragment) },
                          "R-S18 names \(fragment) but the walk found nothing there")
        }
    }
}
