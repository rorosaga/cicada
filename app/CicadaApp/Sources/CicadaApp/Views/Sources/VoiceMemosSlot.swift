import AppKit
import SwiftUI

// Sources → Voice Memos on the standard source page (`SourcePageLayout`). DR-5 (one primary), DR-38 (said once),
// DR-52 (the installed app's own icon; Apple's marks are never committed), DR-59 (one line).

/// G43 — Connect turns the reader on and starts the first read (macOS asks then, never before the click); on, the area's
/// one line says what came in, and the footer holds Refresh and Disconnect.
struct VoiceMemosSlot: View {
    let slot: SourceSlot
    @Environment(VoiceMemosReader.self) private var reader
    @Environment(Store.self) private var store

    var body: some View {
        switch slot {
        case .connect:
            let line = VoiceMemosReader.line(reader.status)
            if reader.enabled && reader.deniedByMac {
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.allowFullDiskAccess) {
                    NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
                }, line: line?.text, lineIsAttention: true)
            } else if reader.enabled {
                SourceConnectArea(line: line?.text, lineIsAttention: line?.isProblem ?? false)
            } else {
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.connect(Copy.voiceMemosTitle),
                                                               help: Copy.voiceMemosConnectHelp) {
                    run { await reader.turnOn() }
                }, line: line?.text, lineIsAttention: line?.isProblem ?? false)
            }
        case .footer:
            if reader.enabled {
                SourcePageFooter(actions: [
                    .refresh(isDisabled: reader.status == .syncing) { run { await reader.syncNow() } },
                    .disconnect(Copy.voiceMemosTitle) { run { await reader.turnOff() } },
                ])
            }
        }
    }

    private func run(_ act: @escaping () async -> Void) {
        Task {
            await act()
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        }
    }
}
