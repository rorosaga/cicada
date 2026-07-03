import SwiftUI
import AppKit
import Foundation

/// The "synced apps" setup sheet: keyless bookmark sync — Chrome and Safari
/// read straight from their local bookmark files
/// (`api/services/bookmark_sync.py`), no login and no OAuth. Opened from
/// `SourcesView`'s "Set up synced apps →" button. Mirrors `ConnectView`'s
/// real-paths-not-placeholders convention and its `onDone` sheet-dismiss
/// pattern.
struct SyncSetupView: View {
    var onDone: (() -> Void)? = nil

    @State private var isSyncing = false
    @State private var syncResult: BookmarkSyncResult?
    @State private var syncError: String?

    // Mirrors `bookmark_sync.chrome_bookmarks_path()` / `safari_bookmarks_path()`
    // so the paths shown here are exactly what the backend reads.
    private let chromePath = (NSHomeDirectory() as NSString)
        .appendingPathComponent("Library/Application Support/Google/Chrome/Default/Bookmarks")
    private let safariPath = (NSHomeDirectory() as NSString)
        .appendingPathComponent("Library/Safari/Bookmarks.plist")

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(
                title: "Synced apps",
                subtitle: "Keyless, local sync — nothing leaves this Mac."
            ) {
                Button {
                    onDone?()
                } label: {
                    Text("Done")
                        .font(.system(size: 13, weight: .semibold))
                        .padding(.horizontal, CicadaTheme.spacingLG)
                        .padding(.vertical, CicadaTheme.spacingSM)
                        .background(CicadaTheme.accent.opacity(0.9))
                        .foregroundStyle(.white)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    sourceCard(
                        icon: "globe",
                        brand: Color(hex: 0x4285F4),
                        name: "Chrome bookmarks",
                        path: chromePath,
                        found: FileManager.default.fileExists(atPath: chromePath),
                        summary: sourceSummary(matching: "chrome")
                    )
                    sourceCard(
                        icon: "safari",
                        brand: Color(hex: 0x2E9BF0),
                        name: "Safari bookmarks",
                        path: safariPath,
                        found: FileManager.default.fileExists(atPath: safariPath),
                        summary: sourceSummary(matching: "safari")
                    )
                    combinedSyncCard
                    rssNoteCard
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXXL)
            }
        }
        .background(CicadaTheme.background)
        .frame(minWidth: 560, idealWidth: 640, minHeight: 480, idealHeight: 560)
    }

    private func sourceSummary(matching origin: String) -> BookmarkSyncSourceSummary? {
        syncResult?.sources.first { $0.origin.lowercased().contains(origin) }
    }

    @ViewBuilder
    private func sourceCard(
        icon: String,
        brand: Color,
        name: String,
        path: String,
        found: Bool,
        summary: BookmarkSyncSourceSummary?
    ) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(RoundedRectangle(cornerRadius: 10).fill(brand.opacity(0.85)))

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(name)
                        .font(CicadaTheme.headingFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    statusPill(found: found)
                }
                Text(path)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)

                if let summary {
                    Text("Last sync: found \(summary.found) · \(summary.new) new · \(summary.skipped) skipped")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                } else if !found {
                    Text("No local bookmarks file detected here — nothing to sync until this app is installed and has at least one bookmark.")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func statusPill(found: Bool) -> some View {
        Text(found ? "Detected" : "Not found")
            .font(.system(size: 10, weight: .semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background((found ? Color(hex: 0x22C55E) : CicadaTheme.textTertiary).opacity(0.15))
            .foregroundStyle(found ? Color(hex: 0x22C55E) : CicadaTheme.textTertiary)
            .clipShape(Capsule())
    }

    private var combinedSyncCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("Sync reads both files directly and skips anything already saved — the same dedup Cicada uses for every source, so it's safe to run as often as you like.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: CicadaTheme.spacingMD) {
                Button {
                    Task { await sync() }
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        if isSyncing {
                            ProgressView().controlSize(.small).frame(width: 12, height: 12)
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath").font(.system(size: 12))
                        }
                        Text(isSyncing ? "Syncing…" : "Sync bookmarks now")
                            .font(.system(size: 13, weight: .semibold))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, CicadaTheme.spacingLG)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .background(CicadaTheme.accent.opacity(0.9))
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .disabled(isSyncing)

                if let result = syncResult {
                    Text("\(result.new) new · \(result.skipped) skipped")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(Color(hex: 0x22C55E))
                } else if let err = syncError {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(err)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(Color(hex: 0xEF4444))
                        Button("Retry") { Task { await sync() } }
                            .buttonStyle(.plain)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(CicadaTheme.accent)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var rssNoteCard: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: "dot.radiowaves.up.forward")
                .font(.system(size: 16))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: 44, height: 44)
                .background(RoundedRectangle(cornerRadius: 10).fill(CicadaTheme.surfaceElevated))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("RSS / Atom feeds")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("There's no standing feed subscription yet — add a feed from the Capture page's \"RSS feed\" tile whenever you want a fresh pull. Recurring feed polling is possible future work.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func sync() async {
        isSyncing = true
        syncError = nil
        do {
            let r = try await APIClient.shared.syncBookmarks()
            await MainActor.run {
                isSyncing = false
                syncResult = r
            }
        } catch {
            await MainActor.run {
                isSyncing = false
                syncError = Self.friendlyError(error)
            }
        }
    }

    private static func friendlyError(_ error: Error) -> String {
        if case APIError.httpError(let code, let msg) = error {
            if code == 404 { return "Bookmark sync isn't available yet — update the Cicada backend." }
            if let data = msg.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = obj["detail"] as? String {
                return detail
            }
            return msg
        }
        return error.localizedDescription
    }
}
