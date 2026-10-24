import AppKit
import SwiftUI

// G218 — the one consent sheet: what is recorded, where it stays, how long, what joins memory, how to wipe, and the
// honest limit, in the person's words. Turn on is the only thing that turns traces on (`recorder.turnOn()`, which
// sends the sheet's version); Not now changes nothing. Then the two permissions, each optional and each through
// `PermissionDragHelper` — never a prompting API.
//
// DR-5.2 / DR-40 (one primary action per surface: Turn on, then Done; Not now is a text button), DR-47 (section
// labels), DR-36 (the sheet's text column stays narrow), DR-38 (each fact once).

struct TracesConsentSheet: View {
    var probe: any TracePermissionProbe = LiveTracePermissionProbe()
    let onClose: () -> Void

    @Environment(TraceRecorder.self) private var recorder
    @State private var step: Step = .consent
    @State private var busy = false
    @State private var problem: String?
    @State private var granted: [TracePermission: Bool] = [:]

    enum Step { case consent, permissions }

    var body: some View {
        SettingsSheet(title: Copy.Traces.consentTitle, onClose: onClose) {
            switch step {
            case .consent: consent
            case .permissions: permissions
            }
        }
    }

    // MARK: - Consent

    private var consent: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    block(Copy.Traces.whatTitle) {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                            ForEach(Copy.Traces.what, id: \.self) { item in
                                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                                    Text(verbatim: "•").foregroundStyle(CicadaTheme.textTertiary)
                                    paragraph(item)
                                }
                            }
                        }
                    }
                    block(Copy.Traces.whereTitle) { paragraph(Copy.Traces.where_) }
                    block(Copy.Traces.howLongTitle) { paragraph(Copy.Traces.howLong) }
                    block(Copy.Traces.intoMemoryTitle) { paragraph(Copy.Traces.intoMemory) }
                    block(Copy.Traces.wipeTitleConsent) { paragraph(Copy.Traces.wipeHow) }
                    Text(Copy.Traces.honestLimit)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: CicadaTheme.scaled(420))
            if let problem {
                Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer()
                TextButton(title: Copy.Traces.notNow, action: onClose)
                PrimaryActionButton(title: Copy.Traces.turnOn) { turnOn() }
                    .disabled(busy)
            }
        }
    }

    // MARK: - Permissions

    private var permissions: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.Traces.stepsTitle).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                paragraph(Copy.Traces.stepsLead)
            }
            stepRow(.accessibility, title: Copy.Traces.stepTitles, line: Copy.Traces.stepTitlesLine)
            stepRow(.screenRecording, title: Copy.Traces.stepShots, line: Copy.Traces.stepShotsLine)
            HStack {
                Spacer()
                PrimaryActionButton(title: Copy.Traces.done, action: onClose)
            }
        }
        .onAppear { readPermissions() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            readPermissions()
        }
    }

    private func stepRow(_ kind: TracePermission, title: String, line: String) -> some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if granted[kind] == true {
                StatusWord(word: Copy.Traces.allowed, tone: .on)
            } else {
                PermissionAllowButton(kind: kind, title: Copy.Traces.allow, probe: probe, place: .traces) {
                    granted[kind] = true
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }

    // MARK: - Pieces

    private func block<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(title)
            content()
        }
    }

    private func paragraph(_ words: String) -> some View {
        Text(words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func turnOn() {
        Task { @MainActor in
            busy = true
            defer { busy = false }
            do {
                try await recorder.turnOn()
                problem = nil
                step = .permissions
            } catch TraceBackendError.notThisMac {
                problem = Copy.Traces.notThisMac
            } catch {
                problem = Eyebrow.text(Copy.Traces.turnOnFailed, TraceRecorder.describe(error))
            }
        }
    }

    private func readPermissions() {
        for kind in [TracePermission.accessibility, .screenRecording] { granted[kind] = probe.granted(kind) }
    }
}
