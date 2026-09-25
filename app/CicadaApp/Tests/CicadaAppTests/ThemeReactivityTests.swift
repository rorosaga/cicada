import Observation
import XCTest
@testable import CicadaApp

/// Regression net for the sun/moon toggle in the sidebar footer.
///
/// The bug: `CicadaTheme.mode` was a plain `static var`, so flipping it changed
/// what every colour token returned but invalidated no SwiftUI view. Only the
/// root and the sidebar — which read `@AppStorage("cicada.colorScheme")`
/// themselves — repainted; every other view kept its cached dark colours and the
/// toggle looked like it did nothing.
///
/// These tests assert the property that fixes it: reading a token registers an
/// observation dependency, so a mode change notifies the reader.
final class ThemeReactivityTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    func test_reading_a_colour_token_subscribes_the_reader_to_the_mode() {
        CicadaTheme.mode = .dark
        var notified = false

        withObservationTracking {
            // Stands in for a SwiftUI `body` that paints with a theme colour.
            _ = CicadaTheme.background
        } onChange: {
            notified = true
        }

        CicadaTheme.mode = .light

        XCTAssertTrue(
            notified,
            "A view that painted with CicadaTheme.background was not told the theme changed"
        )
    }

    func test_every_token_family_subscribes_its_reader() {
        // One representative read per accessor shape: a stored-palette token, a
        // token taking an argument, and one reached through a nested namespace.
        let reads: [(String, () -> Void)] = [
            ("background", { _ = CicadaTheme.background }),
            ("textPrimary", { _ = CicadaTheme.textPrimary }),
            ("entityColor(for:)", { _ = CicadaTheme.entityColor(for: .project) }),
        ]

        for (name, read) in reads {
            CicadaTheme.mode = .dark
            var notified = false
            withObservationTracking(read) { notified = true }
            CicadaTheme.mode = .light
            XCTAssertTrue(notified, "\(name) did not subscribe its reader to the theme mode")
        }
    }

    /// `@Observable` notifies on every write, equal or not. ContentView used to
    /// assign the mode from inside its own `body`; a notification from there
    /// invalidates the view that is mid-render, which is an invalidation loop.
    /// The assignment is gone, and the setter is idempotent as a second guard.
    func test_assigning_the_same_mode_notifies_nobody() {
        CicadaTheme.mode = .light
        var notified = false

        withObservationTracking {
            _ = CicadaTheme.background
        } onChange: {
            notified = true
        }

        CicadaTheme.mode = .light

        XCTAssertFalse(notified, "A redundant mode write invalidated its readers")
    }

    func test_the_persisted_choice_is_read_at_launch_not_mirrored_from_a_view() {
        let defaults = UserDefaults(suiteName: "cicada.theme.tests")!
        defaults.removePersistentDomain(forName: "cicada.theme.tests")

        XCTAssertEqual(ThemeStore(defaults: defaults).mode, .dark, "no stored choice should mean dark")

        defaults.set(AppColorScheme.light.rawValue, forKey: ThemeStore.defaultsKey)
        XCTAssertEqual(ThemeStore(defaults: defaults).mode, .light, "a stored light choice must apply on the first frame")

        defaults.set("not-a-mode", forKey: ThemeStore.defaultsKey)
        XCTAssertEqual(ThemeStore(defaults: defaults).mode, .dark, "an unreadable stored value should fall back to dark")

        defaults.removePersistentDomain(forName: "cicada.theme.tests")
    }
}
