import SwiftUI
import WebKit

struct GraphView: NSViewRepresentable {
    @Environment(GraphViewModel.self) private var viewModel

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "cicada")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")
        webView.underPageBackgroundColor = .clear
        webView.layer?.backgroundColor = .clear

        // Load bundled HTML
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
            }
            webView.evaluateJavaScript(jsCall, completionHandler: nil)
            DispatchQueue.main.async {
                self.viewModel.zoomAction = nil
            }
        }

        // Handle filter updates
        if viewModel.pendingFilterUpdate {
            let types = viewModel.enabledTypes.map { $0.rawValue }
            if let data = try? JSONSerialization.data(withJSONObject: types),
               let json = String(data: data, encoding: .utf8) {
                webView.evaluateJavaScript("filterTypes('\(json)')") { _, error in
                    if let error { print("Filter error: \(error)") }
                }
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
