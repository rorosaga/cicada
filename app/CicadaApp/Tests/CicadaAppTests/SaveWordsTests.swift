import XCTest
@testable import CicadaApp

/// Ruling 80 (owner 2026-11-24: "if I save it already has a reason") — every sentence the app says about a save says what
/// Cicada did or will do with it, in plain words, and none of Cicada's own words for its parts reach the person ("What
/// even is lookup?"). A grep over the copy files that carry saves' words, and a render of every sentence that is built.
final class SaveWordsTests: XCTestCase {
    /// The words that name Cicada's parts, never the person's. "its turn" is the pile's old name for waiting.
    static let internalWords = ["lookup", "indexed", "index-only", "index only", "lean", "its turn", "findable"]

    /// The copy files that say what a save is, from the plan (section 6, Track R).
    static let copyFiles = ["Copy.swift", "Copy+Sources.swift", "Copy+Streams.swift", "Copy+Catalog.swift",
                            "Copy+Reading.swift", "Copy+SleepV5.swift"]

    /// Whole words only: "lean" is Cicada's word for a reduced read, and "cleanly" is not it.
    static func says(_ text: String, _ word: String) -> Bool {
        text.lowercased().range(of: "\\b" + NSRegularExpression.escapedPattern(for: word) + "\\b", options: .regularExpression) != nil
    }

    func testNoInternalWordIsInTheCopyThatSpeaksOfSaves() throws {
        let all = try ThemeTokenTests.swiftSources()
        for name in Self.copyFiles {
            let file = try XCTUnwrap(all.first { $0.lastPathComponent == name }, "no \(name)")
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains("\"") else { continue }
                for word in Self.internalWords {
                    XCTAssertFalse(Self.says(code, word), "\(name):\(index + 1) says \"\(word)\": \(code)")
                }
            }
        }
    }

    func testEverySentenceAboutASaveIsPlainAndSaysWhatHappensToIt() throws {
        let en = Locale(identifier: "en_US")
        var said: [String] = []
        for n in [1, 2, 371] {
            said += [Copy.savesNotReadYet(n, perNight: 100, en), Copy.savesNotReadYet(n, perNight: nil, en)].compactMap { $0 }
        }
        said += [Copy.Kept.explanation(perNight: 100, en), Copy.Kept.explanation(perNight: nil, en),
                 Copy.SleepV5.savesNotReadRow, Copy.Streams.depthRead, Copy.Streams.depthIndex,
                 Copy.Streams.itemRead, Copy.Streams.itemNotRead, Copy.Streams.itemNothing, Copy.Streams.itemRecord,
                 Copy.Streams.itemAsked, Copy.Streams.itemWatched, Copy.Streams.whoSees(app: nil),
                 Copy.Catalog.savedListOff, Copy.Reading.substackIntro]
        for sentence in said {
            for word in Self.internalWords {
                XCTAssertFalse(Self.says(sentence, word), "\"\(sentence)\" says \"\(word)\"")
            }
            XCTAssertFalse(sentence.contains("  "), sentence)
        }
    }

    /// The pace is the backend's number, never one written in the app: the line carries whatever it is given.
    func testThePaceIsTheOneTheBackendSent() throws {
        let en = Locale(identifier: "en_US")
        XCTAssertTrue(try XCTUnwrap(Copy.savesNotReadYet(9, perNight: 37, en)).contains("about 37 a night"))
        XCTAssertTrue(try XCTUnwrap(Copy.Kept.explanation(perNight: 37, en)).contains("about 37 a night"))
        XCTAssertFalse(try XCTUnwrap(Copy.savesNotReadYet(9, perNight: nil, en)).contains("100"))
    }

    /// Watch history, follows and records say they are kept and not read, and why.
    func testWhatYouDidNotSaveSaysSoAndItsWhy() {
        XCTAssertEqual(Copy.Streams.depthIndex, "kept, never read: you did not save it")
        XCTAssertEqual(Copy.Streams.itemRecord, "kept, never read")
    }
}
