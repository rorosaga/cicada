// A08: isolated WebKit ownership probe, no page load and no bank access.
import AppKit
import WebKit

final class AuditHandler: NSObject, WKScriptMessageHandler {
    var webView: WKWebView?
    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {}
}

@MainActor
func runProbe() {
    weak var viewProbe: WKWebView?
    weak var handlerProbe: AuditHandler?
    autoreleasepool {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let handler = AuditHandler()
        config.userContentController.add(handler, name: "synthetic-audit")
        let view = WKWebView(frame: .zero, configuration: config)
        handler.webView = view
        viewProbe = view
        handlerProbe = handler
    }
    print("View retained after external owners drop:", viewProbe != nil)
    print("Handler retained after external owners drop:", handlerProbe != nil)
    autoreleasepool {
        viewProbe?.configuration.userContentController.removeScriptMessageHandler(forName: "synthetic-audit")
        handlerProbe?.webView = nil
    }
    print("View released after cycle broken:", viewProbe == nil)
    print("Handler released after cycle broken:", handlerProbe == nil)
}
MainActor.assumeIsolated { runProbe() }
