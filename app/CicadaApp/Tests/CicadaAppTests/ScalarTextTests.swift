import XCTest
@testable import CicadaApp

/// Design §4.1 / §4.10 — offsets are Python `str` indices (code points).
/// Every fixture pair below was generated ONCE from the backend's own
/// `text[start:end]` (CPython 3.12, 2026-09-23), so a Swift slice that agrees
/// with them agrees with `/span`, `/text` and every evidence entry.
final class ScalarTextTests: XCTestCase {

    // (text, start, end, python text[start:end], python len(text))
    private let pythonFixtures: [(String, Int, Int, String, Int)] = [
        // An emoji is ONE code point but TWO UTF-16 units: an NSRange would land one early.
        ("user: I \u{1F600} moved the index to sqlite-vec", 29, 39, "sqlite-vec", 39),
        ("user: I \u{1F600} moved the index to sqlite-vec", 8, 9, "\u{1F600}", 39),
        // A combining accent is its own code point: `e` + U+0301 is one Character, two scalars.
        ("user: the cafe\u{0301} on alpha-project closes at 6", 19, 32, "alpha-project", 44),
        ("user: the cafe\u{0301} on alpha-project closes at 6", 13, 14, "e", 44),
        ("user: the cafe\u{0301} on alpha-project closes at 6", 13, 15, "e\u{0301}", 44),
        // CJK: one code point per ideograph, and no surrogate pairs.
        ("assistant: \u{6211}\u{4EEC}\u{628A}\u{7D22}\u{5F15}\u{79FB}\u{5230}\u{4E86} sqlite-vec "
            + "\u{6240}\u{4EE5}\u{641C}\u{7D22}\u{662F}\u{4E00}\u{6B21}\u{67E5}\u{627E}", 20, 30, "sqlite-vec", 40),
        // A flag is two regional indicators; a ZWJ family is five code points.
        ("user: \u{1F1EF}\u{1F1F5} trip with bob-example \u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} next week",
         19, 30, "bob-example", 46),
        ("user: \u{1F1EF}\u{1F1F5} trip with bob-example \u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} next week",
         6, 8, "\u{1F1EF}\u{1F1F5}", 46),
        ("user: \u{1F1EF}\u{1F1F5} trip with bob-example \u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} next week",
         31, 36, "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}", 46),
    ]

    func testSlicesAgreeWithPythonOnEmojiCombiningAccentsAndCJK() {
        for (text, start, end, expected, length) in pythonFixtures {
            let doc = ScalarText(text)
            XCTAssertEqual(doc.count, length, "count must be len(text) for \(text)")
            XCTAssertEqual(doc.slice(start, end), expected, "[\(start), \(end)) of \(text)")
        }
    }

    func testCharacterAndUTF16CountsDisagreeWithTheServerWhichIsWhyThisTypeExists() {
        let text = "user: I \u{1F600} moved the index to sqlite-vec"
        XCTAssertNotEqual(text.utf16.count, ScalarText(text).count)
        let accented = "cafe\u{0301}"
        XCTAssertNotEqual(accented.count, ScalarText(accented).count)
    }

    func testOutOfRangeOffsetsClampInsteadOfTrapping() {
        let doc = ScalarText("abc")
        XCTAssertEqual(doc.slice(-5, 2), "ab")
        XCTAssertEqual(doc.slice(1, 99), "bc")
        XCTAssertEqual(doc.slice(5, 9), "")
        XCTAssertEqual(doc.slice(2, 1), "", "an inverted range is empty, not a crash")
        XCTAssertEqual(doc.clamped(2, 1), 2..<2)
    }

    func testAroundGivesContextOnBothSides() {
        let doc = ScalarText("I \u{1F600} moved the index")
        let parts = doc.around(4, 9, radius: 2)
        XCTAssertEqual(parts.span, "moved")
        XCTAssertEqual(parts.before, "\u{1F600} ")
        XCTAssertEqual(parts.after, " t")
    }
}
