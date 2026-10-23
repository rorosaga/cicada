import Foundation

/// G218 — `APIClient` is the traces backend: its `trace…` methods (APIClient.swift, "Activity traces") are each gated
/// to This Mac's own backend (`APIClient.traceGate`).
extension APIClient: TraceBackend {}

extension TraceRecorder {
    /// The app's one recorder, on the live seams.
    static func live() -> TraceRecorder {
        TraceRecorder(backend: APIClient.shared, workspace: LiveTraceWorkspace(), idle: LiveTraceIdleProbe(),
                      titles: LiveTraceWindowTitles(), tabs: LiveTraceBrowserTabs(), capture: LiveTraceScreenCapture(),
                      recognizer: LiveTraceTextRecognizer())
    }
}
