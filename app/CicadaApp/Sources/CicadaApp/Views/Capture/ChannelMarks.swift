import Foundation

/// The channel ids the backend serves, mirrored once so two tests can sweep
/// them (R-L7): `ChannelMarkTests` asserts none falls through to a generic
/// `tray` and that each resolves to the origin the backend's own catalog
/// names, and `LogoAssetTests`' T2 concatenates their marks when proving every
/// bundled PNG is claimed by some map.
///
/// A *source* file, not a test helper, precisely because both suites read it —
/// a copy inside one test file would drift from the other's.
enum ChannelMarks {
    /// Mirrors `api/services/channel_registry.py::CHANNEL_IDS` verbatim — a
    /// 14th id added there needs this list AND
    /// `ConnectedChannelRow.origin(forChannel:)` updated together, and the
    /// sweep in `ChannelMarkTests` is what makes forgetting the second half
    /// loud. `IntegrationsViewTests.testEveryChannelIdHasACategory` keeps its
    /// own copy of the same list for the category map; both are checked
    /// against the command in the plan's task 4 step 5.
    static let allChannelIds: [String] = [
        "chat-export:claude", "chat-export:chatgpt",
        "chrome-bookmarks", "safari-bookmarks", "safari-tabs",
        "notes", "rss", "calendar",
        "pinterest", "reddit", "x", "telegram", "files",
    ]
}
