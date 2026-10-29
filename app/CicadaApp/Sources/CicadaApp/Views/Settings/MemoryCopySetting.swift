import SwiftUI

/// G132 phase 1 (ruling 51a/d) — Settings → Devices' *One memory on your computers*: on the computer that holds the
/// memory, *Share this memory with my other computers* (`/sync/publish`); on another, *Keep a full copy here*
/// (`/sync/replica`: that computer's address and the one-time code its *Pair a device* shows, then this computer's
/// backend starts again as a copy). While it keeps a copy the row says what it follows, how far behind it is and what
/// made here is still on its way. Existing patterns only: Settings' switch row with its caption below (as *Scheduled
/// runs may use my plan*), the address-and-code form of *Where your memory lives* with Settings' native rounded fields
/// (DR-76), a neutral button for the act and a text button for the rare one (DR-40); copy in plain words (DR-59),
/// provider-neutral, no path or variable (`Copy.MemoryCopy`).
struct MemoryCopySetting: View {
    @State private var model = MemoryCopyModel()
    @State private var formOpen = false
    @Environment(Store.self) private var store

    /// The open memory is a demo (the Store's roster, beside the backend's own answer): it is never shared.
    private var inDemo: Bool { model.isDemoMemory(isDemo: DemoMode.isShowing(store.banks.value, bank: store.bank)) }
    /// The Sleep the Store shows: this Mac's own — or, on a copy, the home's (`replica.home_sleep()`), which never
    /// stops this Mac from leaving its copy (`MemoryCopyModel.sleepBlocks`).
    private var sleeping: Bool { ProjectWriteGate.sleepRunning(store.status.value) }

    var body: some View {
        Group {
            if model.shown {
                SettingsGroupCard {
                    if model.canShare(isDemo: inDemo) {
                        shareRow
                        SettingsDivider()
                    }
                    copyRow
                }
            }
        }
        .task {
            await model.refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if Task.isCancelled { break }
                await model.refresh()
            }
        }
    }

    private var shareRow: some View {
        SettingsRow(.memoryShare, title: Copy.MemoryCopy.shareTitle, detail: Copy.MemoryCopy.shareDetail) {
            Toggle(Copy.MemoryCopy.shareTitle, isOn: Binding(get: { model.publish?.publish ?? false },
                                                             set: { on in Task { await model.setShare(on) } }))
                .labelsHidden()
                .toggleStyle(.switch)
                .disabled(model.busy || model.publish?.source == "env")
        } below: {
            if model.publish?.source == "env" { caption(Copy.MemoryCopy.shareFixed) }
        }
    }

    /// This computer shares its own memory: it is a home, so it does not also keep a copy of another's.
    private var sharing: Bool { model.publish?.publish ?? false }

    private var copyRow: some View {
        let isCopy = model.replica?.isReplica ?? false
        return SettingsRow(.memoryCopy, title: Copy.MemoryCopy.copyTitle,
                           detail: isCopy ? nil : Copy.MemoryCopy.copyDetail) {
            Toggle(Copy.MemoryCopy.copyTitle, isOn: Binding(get: { isCopy || formOpen }, set: { on in
                if on { formOpen = true } else if isCopy { Task { await model.stopCopy() } } else { formOpen = false }
            }))
            .labelsHidden()
            .toggleStyle(.switch)
            .disabled(model.busy || model.restarting || sharing || inDemo
                      || MemoryCopyModel.sleepBlocks(sleeping: sleeping, isCopy: isCopy))
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if model.restarting {
                    caption(Copy.MemoryCopy.restarting)
                } else if MemoryCopyModel.sleepBlocks(sleeping: sleeping, isCopy: isCopy) {
                    caption(Copy.MemoryCopy.waitForSleep)
                } else if inDemo && !isCopy {
                    caption(Copy.MemoryCopy.notForDemo)
                } else if sharing && !isCopy {
                    caption(Copy.MemoryCopy.whileSharing)
                } else if isCopy, let copy = model.replica?.replica {
                    caption(copy.text)
                    if let host = model.replica?.home, copy.status == "following" {
                        caption(Copy.MemoryCopy.following(host))
                    }
                    if let behind = copy.behind, behind > 0 { caption(Copy.MemoryCopy.behind(behind)) }
                    if let waiting = model.replica, waiting.onItsWay > 0 {
                        caption(Copy.MemoryCopy.onItsWay(waiting.onItsWay))
                    }
                    if model.replica?.needsCopyAgain == true {
                        TextButton(title: Copy.MemoryCopy.copyAgain, inline: true) {
                            Task { await model.copyAgain() }
                        }
                    }
                } else if formOpen {
                    form
                }
                if let error = model.error {
                    Text(error)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.danger)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    @ViewBuilder private var form: some View {
        caption(Copy.MemoryCopy.copyOff)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.MemoryCopy.homeTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            TextField(Copy.MemoryCopy.homePlaceholder, text: $model.address)
                .textFieldStyle(.roundedBorder)
                .font(CicadaTheme.bodyFont)
        }
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.MemoryCopy.codeTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            SecureField(Copy.MemoryCopy.codePlaceholder, text: $model.code)
                .textFieldStyle(.roundedBorder)
                .font(CicadaTheme.bodyFont)
        }
        HStack(spacing: CicadaTheme.spacingSM) {
            NeutralButton(title: Copy.MemoryCopy.keep, size: .compact,
                          isDisabled: model.busy || model.address.isEmpty || model.code.isEmpty) {
                Task { await model.keepCopy() }
            }
            if model.busy { ProgressView().controlSize(.small) }
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
