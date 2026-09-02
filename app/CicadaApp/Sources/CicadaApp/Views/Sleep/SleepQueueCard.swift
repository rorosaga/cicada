import SwiftUI

/// "What is waiting for the next cycle", lifted off the retired Capture page
/// (G68 §1). It belongs on Sleep: the count it shows and the button it carries
/// are both about the cycle this page runs.
///
/// A projection over `Store.status` plus `SleepViewModel`; starts no fetches.
struct SleepQueueCard: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    private var status: StatusSnapshot? { store.status.value }
    private var isLoading: Bool { store.status.isEmpty && store.status.isRefreshing }

    /// PR #19 review: `store.status` missing is not one state, it's two — a
    /// fetch still in flight (`.loading`) vs. a fetch that already failed and
    /// left nothing behind (`.failed`) — and neither is "a confirmed zero
    /// queue" (`.loaded(count: 0)`, the only case "All caught up" may render
    /// for). Pulled out as a pure function, mirroring `SleepView.queueCount`
    /// /`queueNeedsReconcile`, so the precedence is unit-testable without a view.
    enum LoadState: Equatable {
        case loading
        case failed(String)
        case loaded(count: Int)
    }

    static func loadState(status: StatusSnapshot?, isLoading: Bool, error: String?) -> LoadState {
        if let status { return .loaded(count: status.episodes.unprocessed) }
        if isLoading { return .loading }
        if let error { return .failed(error) }
        // No snapshot, not refreshing, no latched failure yet — the fetch
        // simply hasn't started. Treat like loading rather than guessing.
        return .loading
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("QUEUE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            switch Self.loadState(status: status, isLoading: isLoading, error: store.domainErrors[.status]) {
            case .loading:
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Checking the queue…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            case .failed(let message):
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.danger)
                    Text(message)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    Button("Retry") { Task { await store.refresh([.status]) } }
                        .buttonStyle(.cicadaPlain)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.accent)
                        .accessibilityLabel("Retry loading the queue")
                }
            case .loaded(let count):
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    Image(systemName: count == 0 ? "checkmark.circle" : "tray.full")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(count == 0 ? CicadaTheme.success : CicadaTheme.accent)
                        .frame(width: 28, height: 28)
                        .background(Circle().fill((count == 0 ? CicadaTheme.success : CicadaTheme.accent).opacity(0.12)))
                        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(count == 0
                             ? "All caught up"
                             : "\(count) item\(count == 1 ? "" : "s") queued for the next Sleep cycle")
                            .font(CicadaTheme.headingFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if count > 0 {
                            Text("\(Copy.consolidateNow) to fold them into the graph immediately.")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        } else if let last = formattedLastSleep {
                            Text("Last consolidated \(last)")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }

                    Spacer()

                    HStack(spacing: CicadaTheme.spacingSM) {
                        consolidateButton(count: count)
                        if sleepVM.isRunning {
                            cancelButton
                        }
                    }
                }

                // A cancel that is running (or a failed trigger) explains
                // itself under the buttons.
                if sleepVM.isRunning {
                    Text(Copy.cancelSleepExplainer)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .fixedSize(horizontal: false, vertical: true)
                } else if let err = sleepVM.errorMessage ?? sleepVM.lastError, !err.isEmpty {
                    Text(err)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.danger)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func consolidateButton(count: Int) -> some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(.system(size: 12))
                }
                Text(sleepVM.isRunning ? Copy.consolidating : Copy.consolidateNow)
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(count == 0 && !sleepVM.isRunning ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(count == 0 && !sleepVM.isRunning ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isRunning || count == 0)
        .help(count == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }

    /// Only shown while a cycle is running (H1: the trigger button itself
    /// stays disabled + read-only for "Consolidating…", so this is the one
    /// live control the running state offers). Cooperative, not instant —
    /// `Copy.cancelSleepExplainer` says so both here (tooltip) and in the
    /// caption below the buttons.
    private var cancelButton: some View {
        Button {
            Task { await sleepVM.cancel() }
        } label: {
            HStack(spacing: 4) {
                if sleepVM.isCancelling {
                    ProgressView().controlSize(.small).frame(width: 10, height: 10)
                } else {
                    Image(systemName: "xmark").font(.system(size: 10, weight: .semibold))
                }
                Text(sleepVM.isCancelling ? Copy.cancellingSleep : Copy.cancelSleep)
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.surfaceElevated)
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isCancelling)
        .help(Copy.cancelSleepExplainer)
        .accessibilityLabel(Copy.cancelSleep)
    }

    private var formattedLastSleep: String? {
        guard let date = StatusSnapshot.parseDate(status?.lastSleepAt) else { return nil }
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return f.string(from: date)
    }
}
