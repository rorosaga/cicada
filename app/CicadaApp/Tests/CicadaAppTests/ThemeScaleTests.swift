import Observation
import SwiftUI
import XCTest
@testable import CicadaApp

/// G130 slice 1a: `uiScale` is the one value ⌘+/⌘−/⌘0 change, and every font
/// and spacing token derives from it so a reader that observes any token
/// repaints on a zoom with no `.id()` anywhere (the PR #49 lesson —
/// `ThemeReactivityTests` is the sibling regression net for `mode`).
final class ThemeScaleTests: XCTestCase {

    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        super.tearDown()
    }

    // MARK: - clampScale (R1: stepped, then clamped)

    func test_clampScale_clamps_to_the_range() {
        XCTAssertEqual(ThemeStore.clampScale(2.0), 1.4)
        XCTAssertEqual(ThemeStore.clampScale(0.1), 0.8)
    }

    func test_clampScale_snaps_to_the_nearest_step() {
        XCTAssertEqual(ThemeStore.clampScale(1.05), 1.1)
    }

    // MARK: - Derived tokens

    func test_scaled_and_spacing_derive_from_uiScale() {
        CicadaTheme.uiScale = 1.2
        XCTAssertEqual(CicadaTheme.scaled(10), 12)
        XCTAssertEqual(CicadaTheme.spacingMD, 14.4)
    }

    func test_tokens_at_1_0_equal_todays_layout_exactly() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(CicadaTheme.spacingMD, 12)
        XCTAssertEqual(CicadaTheme.bodyFont, Font.system(size: 13, weight: .regular))
    }

    // MARK: - Chrome that has to scale with it (round-2 live check)

    /// The sidebar's minimum width was a bare `180`: ⌘+ grew the rows' font
    /// while their box stayed put, and at 1.4× "Inbox" wrapped to "Inbo / x".
    /// A width that ignores `uiScale` is the same bug slice 1b removed for
    /// every `.system(size:)` literal, so it goes through the same helper.
    func test_the_sidebar_minimum_width_scales_with_uiScale() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(CicadaTheme.scaled(SidebarView.minWidth), SidebarView.minWidth,
                       "at 1.0 the sidebar must be exactly as wide as it has always been")

        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(CicadaTheme.scaled(SidebarView.minWidth), 252)
    }

    /// It grows at every step, never at only the extremes — the label wraps at
    /// whichever zoom the box stops keeping up.
    func test_the_sidebar_minimum_width_grows_at_every_zoom_step() {
        var previous: CGFloat = 0
        for scale in [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4] {
            CicadaTheme.uiScale = scale
            let width = CicadaTheme.scaled(SidebarView.minWidth)
            XCTAssertGreaterThan(width, previous, "the sidebar did not grow at \(scale)×")
            previous = width
        }
    }

    // MARK: - Observation (the PR #49 mechanism, applied to scale)

    func test_reading_a_font_token_subscribes_the_reader_to_uiScale() {
        CicadaTheme.uiScale = 1.0
        var notified = false

        withObservationTracking {
            _ = CicadaTheme.bodyFont
        } onChange: {
            notified = true
        }

        CicadaTheme.uiScale = 1.1

        XCTAssertTrue(notified, "A view that painted with CicadaTheme.bodyFont was not told the scale changed")
    }

    /// R4: idempotent, and never called from a body — a redundant write must
    /// not invalidate readers mid-render (the same invalidation-loop trap
    /// `ThemeReactivityTests` guards for `mode`).
    func test_assigning_the_same_scale_notifies_nobody() {
        CicadaTheme.uiScale = 1.1
        var notified = false

        withObservationTracking {
            _ = CicadaTheme.bodyFont
        } onChange: {
            notified = true
        }

        CicadaTheme.uiScale = 1.1

        XCTAssertFalse(notified, "A redundant uiScale write invalidated its readers")
    }

    // MARK: - Zoom actions (R1: 0.1 steps, clamped at the edges)

    func test_zoomIn_steps_up_by_0_1_three_times() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.zoomIn()
        CicadaTheme.zoomIn()
        CicadaTheme.zoomIn()
        XCTAssertEqual(CicadaTheme.uiScale, 1.3)
    }

    func test_zoomOut_stays_clamped_at_the_floor() {
        CicadaTheme.uiScale = 0.8
        CicadaTheme.zoomOut()
        XCTAssertEqual(CicadaTheme.uiScale, 0.8)
    }

    func test_resetZoom_returns_to_1_0() {
        CicadaTheme.uiScale = 1.4
        CicadaTheme.resetZoom()
        XCTAssertEqual(CicadaTheme.uiScale, 1.0)
    }

    // MARK: - Launch read (mirrors ThemeReactivityTests' mode launch-read test)

    /// `defaults.double(forKey:)` returns exactly `0` both when the key is
    /// absent (fresh install) and when it holds a non-numeric value (a
    /// hand-edited plist) — either must default to 1.0, today's layout,
    /// never to `clampScale(0)`'s floor of 0.8.
    func test_the_persisted_scale_is_read_at_launch_not_mirrored_from_a_view() {
        let defaults = UserDefaults(suiteName: "cicada.zoom.tests")!
        defaults.removePersistentDomain(forName: "cicada.zoom.tests")

        XCTAssertEqual(ThemeStore(defaults: defaults).uiScale, 1.0, "no stored scale should mean 1.0, not the clamped floor")

        defaults.set(1.2, forKey: ThemeStore.scaleKey)
        XCTAssertEqual(ThemeStore(defaults: defaults).uiScale, 1.2, "a stored scale must apply on the first frame")

        defaults.set("not-a-number", forKey: ThemeStore.scaleKey)
        XCTAssertEqual(ThemeStore(defaults: defaults).uiScale, 1.0, "an unreadable stored value should fall back to 1.0")

        defaults.removePersistentDomain(forName: "cicada.zoom.tests")
    }
}
