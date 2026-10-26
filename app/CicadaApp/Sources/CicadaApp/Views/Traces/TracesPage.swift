import SwiftUI

// G218 (owner 2026-10-26: "Traces are fine in Sources, but maybe it should be its own page, so we can actually see the
// trace of the screenshots that were taken. The user knows everything is local.") — the Traces page: the days down the
// side, a day's screenshots and spans beside them (`TracesTimelineView` in its page layout), one line on where all of it
// lives, Settings… (the controls Sources used to hold, `TracesControls`) and Wipe.
//
// Every G218 rail holds unchanged: the screenshots stay behind Touch ID or the login password and are fetched only
// after it, held in memory and dropped when the page goes or five minutes pass (`TracesBrowserModel`); every read is
// This Mac's backend's sealed store (`$CICADA_HOME/traces`, outside every bank and git), never the network or a remote
// door; nothing here is a mention. On the rail only while traces are on or were ever on (`TracesPageVisibility`).
//
// DR-22 (the rail cell, appended without a ⌘ digit), DR-25 (the eyebrow row's trailing actions), DR-40 (neutral
// buttons; Wipe behind a confirmation in words), DR-50 (empty states in words), DR-58 (day words), DR-60 (instant
// switches).
struct TracesPage: View {
    @Environment(TraceRecorder.self) private var recorder: TraceRecorder?
    @State private var showSettings = false
    @State private var confirmWipe = false
    @State private var note: String?
    /// The rail's second click returns the page to its root through the shared mechanism (`onRailReselect` →
    /// `popToRoot`: instant from ⌘, eased from a click — DR-60/61): Settings and the wipe question close, the note
    /// goes, and the timeline goes back to the newest day with no search (`TracesBrowserModel.returnToRoot`).
    @State private var rootToken = 0
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: eyebrow) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    NeutralButton(title: Copy.Traces.settings, systemImage: "slider.horizontal.3", size: .compact,
                                  help: Copy.Traces.settingsHelp) { showSettings = true }
                    NeutralButton(title: Copy.Traces.wipe, size: .compact, isDisabled: recorder == nil) {
                        confirmWipe = true
                    }
                }
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.Traces.staysHere(shotDays: recorder?.settings.shotDays ?? 7,
                                           timelineDays: recorder?.settings.timelineDays ?? 30))
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                if let note {
                    Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingGutter)
            .padding(.bottom, CicadaTheme.spacingLG)
            if let recorder {
                TracesTimelineView(status: recorder.status, rootToken: rootToken)
                    .padding(.horizontal, CicadaTheme.spacingGutter)
                    .padding(.bottom, CicadaTheme.spacingLG)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgBase)
        .task { await recorder?.refreshStatus() }
        .onRailReselect(.traces, router: router) {
            router?.popToRoot(reduceMotion: reduceMotion) {
                showSettings = false
                confirmWipe = false
                note = nil
                rootToken &+= 1
            }
        }
        .sheet(isPresented: $showSettings) {
            TracesSettingsSheet { showSettings = false }
        }
        .confirmationDialog(Copy.Traces.wipeTitle, isPresented: $confirmWipe) {
            Button(Copy.Traces.wipeConfirm, role: .destructive) { wipe() }
            Button(Copy.Traces.cancel, role: .cancel) {}
        } message: {
            Text(Copy.Traces.wipeMessage)
        }
    }

    private var eyebrow: String {
        guard let recorder else { return Copy.Traces.title }
        return Eyebrow.text(Copy.Traces.title,
                            TracesControlsLogic.stateLine(recorder.state, settings: recorder.settings, now: .now))
    }

    private func wipe() {
        guard let recorder else { return }
        Task { @MainActor in
            do { try await recorder.wipe(); note = Copy.Traces.wiped } catch { note = TraceRecorder.describe(error) }
        }
    }
}

/// The Traces page's Settings…: Sources' old controls in a sheet — pause, forget, what is recorded, what joins memory,
/// how long, what is never recorded, browsers, titles per app, what is on this Mac — with no "Browse" (the page is it).
struct TracesSettingsSheet: View {
    let onClose: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(Copy.Traces.settingsTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
                .padding([.horizontal, .top], CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingMD)
            ScrollView {
                TracesControls(showsBrowse: false)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, CicadaTheme.spacingXL)
            }
            HStack {
                Spacer()
                NeutralButton(title: Copy.Traces.done, size: .compact, shortcut: .cancelAction) { onClose() }
            }
            .padding(CicadaTheme.spacingMD)
        }
        .frame(width: CicadaTheme.scaled(560), height: CicadaTheme.scaled(620))
        .background(CicadaTheme.bgBase)
    }
}

/// Sources' Traces row once the page exists (owner 2026-10-26): one line and the way there. Before traces were ever on,
/// Sources keeps the switch itself (`TracesControls`' Turn on…).
struct TracesSourcesLink: View {
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(TraceRecorder.self) private var recorder: TraceRecorder?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let recorder {
                Text(TracesControlsLogic.stateLine(recorder.state, settings: recorder.settings, now: .now))
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            Text(Copy.Traces.onItsPage).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            NeutralButton(title: Copy.Traces.openPage, systemImage: AppTab.traces.icon, size: .compact,
                          help: Copy.Traces.openPageHelp) { router?.pendingTab = .traces }
        }
    }
}
