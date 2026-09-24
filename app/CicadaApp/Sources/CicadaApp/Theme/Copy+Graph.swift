import Foundation

/// The Graph page's words (Direction D, DS-3a), in their own file — the `Copy+Inbox.swift` precedent, so
/// tracks appending to `Copy.swift` never edit the same lines. Each later task adds its own
/// `extension Copy.Graph` block below. Plain words for a person who has never heard "node" or "claim".
extension Copy {
    enum Graph {
        // The floating group (R-DG3)
        static let controlsLabel = "Graph controls"
        static let all = "All"
        static let external = "External"
        static let legend = "Legend"
        static let legendFiltered = "Legend · filtered"
        static let legendHelp = "Legend and filters"
        static let zoomIn = "Zoom in"
        static let zoomOut = "Zoom out"
        static let fit = "Fit the whole graph"
        static let panOffHelp = "Pan mode — drag anywhere to move the graph (or hold Shift)"
        static let panOnHelp = "Pan mode is on — click to return to normal (or just hold Shift)"

        // The Legend panel (R-DG4)
        static let whoseBeliefs = "Whose beliefs"
        static let contextHeading = "Context · edge colour"
        static let typeHeading = "Type · node colour"
        static let statusHeading = "Status"
        static let minConfidence = "Minimum confidence"
        static let anyConfidence = "Any"
        static func orMore(_ n: Int) -> String { "\(n) or more" }
        static let showAll = "Show all"
        static let showLogos = "Show logos"
        static let showLogosHelp = "Show entity logos on graph nodes"
        static let dashed = "dashed"
        static let hiddenByDefault = "hidden by default"
        static let keyBigger = "Bigger means more confident"
        static let keyDashed = "Dashed means fading"
        static let keyPulse = "Amber ring: a question waits"

        // Find on the canvas (R-DG5)
        static let findOnCanvas = "Find on the canvas"
        static let closeFind = "Close (Esc)"
        static let noNodeMatches = "No node matches"

        // The Graph's `?` (R-DG6)
        static let helpTitle = "How the graph works"
    }
}
