import Foundation

/// Everything graph.js posts, parsed in one place (DS-3a R-DG25). The coordinator used to hand-parse
/// each `type`; a new message is now one case here and one test in `GraphBridgeTests`, and the JS half
/// of every new message is tested under the real d3 (`Tests/graph/graph-canvas-bridge.test.js`).
enum GraphMessage: Equatable {
    case graphReady
    case nodeClicked(String)
    case hubExpanded(String)
    case nodeFocused(String)
    case focusCleared
    /// R-DG8 — a click on empty canvas, never a drag and never in pan mode.
    case backgroundClicked
    /// R-DG11 — Esc with no ego focus: the page decides what it closes.
    case escape
    case jsError(String)

    static func parse(_ body: Any) -> GraphMessage? {
        guard let string = body as? String, let data = string.data(using: .utf8),
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let type = json["type"] as? String
        else { return nil }
        let id = json["id"] as? String
        switch type {
        case "graphReady": return .graphReady
        case "backgroundClicked": return .backgroundClicked
        case "escape": return .escape
        case "focusCleared": return .focusCleared
        case "nodeClicked": return id.map(GraphMessage.nodeClicked)
        case "hubExpanded": return id.map(GraphMessage.hubExpanded)
        case "nodeFocused": return id.map(GraphMessage.nodeFocused)
        case "jsError":
            let stack = json["stack"] as? String ?? ""
            let at = "\(json["message"] as? String ?? "?") @ \(json["source"] as? String ?? "?"):"
                + "\(json["line"] as? Int ?? 0):\(json["col"] as? Int ?? 0)"
            return .jsError(stack.isEmpty ? at : "\(at)\n\(stack)")
        default: return nil
        }
    }
}

/// The page actions graph.js asks Swift for (R-DG8, R-DG11), relayed through `GraphViewModel` so the page
/// that owns the panels and the Reader answers them.
enum CanvasEvent: Equatable {
    case backgroundClicked
    case escape
}

/// Every call Swift makes into graph.js that carries an id, spelled once (R-DG25). An id is a JSON string
/// literal, so no slug can break out of the call.
enum GraphJS {
    static func literal(_ s: String) -> String {
        guard let data = try? JSONEncoder().encode(s), let lit = String(data: data, encoding: .utf8) else { return "null" }
        return lit
    }
    static func setSelectedNode(_ id: String?) -> String { "setSelectedNode(\(id.map(literal) ?? "null"))" }
    static func revealNode(_ id: String) -> String { "revealNode(\(literal(id)))" }
    static func setFocus(_ id: String, hops: Int) -> String { "setFocus(\(literal(id)), \(hops))" }
}
