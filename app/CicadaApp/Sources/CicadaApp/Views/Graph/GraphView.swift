import SwiftUI
import WebKit

/// WKWebView that accepts a click even when its window isn't already key.
/// This app is a bundle-less SwiftPM executable launched from a terminal, so
/// the Cicada window is rarely the active window when the user reaches over to
/// click a graph node — and a plain WKWebView swallows that first click as a
/// mere window-activation (mousemove/hover still works, which is why the graph
/// reacts to hover but not to clicks). Accepting first mouse routes the click
/// straight through to the canvas as a real DOM mousedown.
final class ClickableWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var acceptsFirstResponder: Bool { true }
}

struct GraphView: NSViewRepresentable {
    @Environment(GraphViewModel.self) private var viewModel

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "cicada")

        let webView = ClickableWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")
        webView.underPageBackgroundColor = .clear
        webView.layer?.backgroundColor = .clear

        // Load bundled HTML
        // TODO(G26): theme graph.js webview. The SwiftUI chrome is now
        // light/dark switchable (CicadaTheme.mode), but this WKWebView loads
        // a static graph/index.html + graph.js that hard-codes the dark d3
        // canvas palette. Follow-up: either postMessage the active
        // AppColorScheme into the page (bridge already exists via
        // `cicada` in WKUserContentController, see Coordinator below) and
        // have graph.js swap its color constants, or accept the graph
        // staying dark for now as scoped.
        if let resourceURL = Bundle.module.url(forResource: "graph/index", withExtension: "html") {
            webView.loadFileURL(resourceURL, allowingReadAccessTo: resourceURL.deletingLastPathComponent())
        }

        context.coordinator.webView = webView
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Handle zoom actions from Swift UI
        if let action = viewModel.zoomAction {
            let jsCall: String
            switch action {
            case .zoomIn: jsCall = "zoomIn()"
            case .out: jsCall = "zoomOut()"
            case .reset: jsCall = "zoomReset()"
            case .fit: jsCall = "fitGraph()"
            }
            webView.evaluateJavaScript(jsCall, completionHandler: nil)
            DispatchQueue.main.async {
                self.viewModel.zoomAction = nil
            }
        }

        // Handle graph data refresh (after sleep cycle or initial load).
        // Gate on isGraphReady — if graph.js hasn't loaded yet, the Coordinator
        // will push the pending data when it receives the "graphReady" message
        // from init(). Calling updateGraph() before DOMContentLoaded raises
        // "TypeError: undefined is not a function".
        if viewModel.pendingGraphUpdate && viewModel.isGraphReady {
            let json = viewModel.graphDataJSON
            let filterJSON = viewModel.filterJSON
            webView.evaluateJavaScript("updateGraph(\(json))") { _, error in
                if let error { print("Graph update error: \(error)") }
                // Re-assert the current filter so a fresh payload respects it
                // (status/confidence defaults hide archived nodes from first paint).
                webView.evaluateJavaScript("applyFilters(\(filterJSON))", completionHandler: nil)
            }
            DispatchQueue.main.async {
                self.viewModel.pendingGraphUpdate = false
            }
        }

        // Handle filter updates (also requires graph.js to be loaded)
        if viewModel.pendingFilterUpdate && viewModel.isGraphReady {
            webView.evaluateJavaScript("applyFilters(\(viewModel.filterJSON))") { _, error in
                if let error { print("Filter error: \(error)") }
            }
            DispatchQueue.main.async {
                self.viewModel.pendingFilterUpdate = false
            }
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(viewModel: viewModel)
    }

    class Coordinator: NSObject, WKScriptMessageHandler {
        let viewModel: GraphViewModel
        var webView: WKWebView?
        var isGraphReady = false
        private var hasPushedInitialData = false

        init(viewModel: GraphViewModel) {
            self.viewModel = viewModel
        }

        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard let bodyString = message.body as? String,
                  let data = bodyString.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = json["type"] as? String
            else { return }

            DispatchQueue.main.async { [self] in
                switch type {
                case "graphReady":
                    isGraphReady = true
                    viewModel.isGraphReady = true
                    pushGraphData()

                case "nodeClicked":
                    if let id = json["id"] as? String {
                        viewModel.selectEntity(id: id)
                    }

                case "hubExpanded":
                    // Hub tapped while in hubs-only paint: zoom into its
                    // 1-hop neighborhood instead of opening a detail card.
                    if let id = json["id"] as? String {
                        webView?.evaluateJavaScript("setFocus('\(id)', 1)", completionHandler: nil)
                    }

                case "nodeFocused", "focusCleared":
                    // Informational — focus state lives in JS.
                    break

                case "jsError":
                    let stack = json["stack"] as? String ?? ""
                    print("Graph JS error: \(json["message"] as? String ?? "?") @ \(json["source"] as? String ?? "?"):\(json["line"] as? Int ?? 0):\(json["col"] as? Int ?? 0)\(stack.isEmpty ? "" : "\n\(stack)")")

                default:
                    break
                }
            }
        }

        private func pushGraphData() {
            guard !hasPushedInitialData, let webView else { return }
            hasPushedInitialData = true
            let json = viewModel.graphDataJSON
            webView.evaluateJavaScript("updateGraph(\(json))") { _, error in
                if let error { print("Initial graph push error: \(error)") }
            }
        }
    }
}
