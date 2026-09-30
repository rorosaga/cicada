import Foundation

/// G162 — the watch run's one line about where a video goes, in `LeavesMacNote`'s style: a pure function, so a test
/// pins the words. Cicada hands the person's own agent each video's link, title, channel and length and nothing else
/// (`mcp_tools._video_lines`; Track V's rail: no download, no derived stream), so the sentence says exactly that and names no provider (R-VU11): which model or service the
/// agent uses is the agent's and the person's choice, never Cicada's.
enum WatchLeavesMacNote {
    static func text() -> String { Copy.Videos.leavesMacNote }
}
