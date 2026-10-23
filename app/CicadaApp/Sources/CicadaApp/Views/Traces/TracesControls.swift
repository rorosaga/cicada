import AppKit
import SwiftUI

// G218 — Traces' own control on the Sources page (`SourceCatalogDetail.controls`, case "traces"). Off: one line of
// what traces are and "Turn on…", which opens the consent sheet. On: the state line, Pause / Resume, Forget the last
// 15 minutes, Browse, Turn off and Wipe; then what is recorded, what joins memory, how long, what is never recorded,
// which browsers' addresses may be read and which chat apps may keep titles; then what is on this Mac. Every write goes
// through the recorder (`TraceRecorder.update`), never straight to the backend.
//
// DR-40 (neutral buttons; the destructive Wipe behind a confirmation in words), DR-47 (one section label), DR-38
// (nothing the detail's head already says), DR-58 (day words from `RelativeDay`), DR-76 (the app's own field).

/// The one call allowed to raise a browser's Automation prompt, behind a seam so tests never send Apple Events.
protocol TraceBrowserAsking: Sendable {
    /// Asks macOS whether Cicada may script this browser — the prompt may appear. Only on the person's click.
    func ask(bundleId: String) -> Bool
    /// Whether macOS already allows it, never asking.
    func granted(bundleId: String) -> Bool
}

struct LiveTraceBrowserAsker: TraceBrowserAsking {
    func ask(bundleId: String) -> Bool { LiveTraceBrowserTabs.ask(bundleId: bundleId) }
    func granted(bundleId: String) -> Bool { LiveTraceBrowserTabs().granted(bundleId: bundleId) }
}

/// The controls' logic with no view in it: the state line, list edits, and the browser switch.
enum TracesControlsLogic {
    /// The state line under the head.
    static func stateLine(_ state: TraceRecorder.State, settings: TraceSettings, now: Date,
                          calendar: Calendar = .autoupdatingCurrent, locale: Locale = .autoupdatingCurrent) -> String {
        switch state {
        case .recording: return Copy.Traces.recording
        case .paused:
            guard let when = pausedWhen(settings.pausedUntil, now: now, calendar: calendar, locale: locale) else {
                return Copy.Traces.pausedUntilResumed
            }
            return Copy.Traces.pausedUntil(when)
        case .off: return Copy.Traces.off
        case .notThisMac: return Copy.Traces.notThisMac
        case .failed(let why): return Copy.Traces.failed(why)
        }
    }

    /// "3:40 PM" (later today), "tomorrow" (a pause until tomorrow's start), "tomorrow at 12:30 AM"; nil for a pause
    /// that lasts until the person resumes (or one with no end known).
    static func pausedWhen(_ until: String?, now: Date, calendar: Calendar = .autoupdatingCurrent,
                           locale: Locale = .autoupdatingCurrent) -> String? {
        guard let until, until != TraceSettings.untilResumed, let end = TraceClock.parse(until) else { return nil }
        var style = Date.FormatStyle(date: .omitted, time: .shortened, locale: locale, calendar: calendar)
        style.timeZone = calendar.timeZone
        let today = ISODay.today(now: now, calendar: calendar)
        let endDay = ISODay.today(now: end, calendar: calendar)
        if endDay == today { return end.formatted(style) }
        let distance = RelativeDay.distance(endDay, today: today)
        if calendar.startOfDay(for: end) == end { return distance }
        return "\(distance) \(end.formatted(style))"
    }

    /// `trace_policy.valid_bundle`.
    static func validBundle(_ raw: String) -> Bool {
        raw.range(of: #"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,199}$"#, options: .regularExpression) != nil
    }

    /// `trace_policy.normalize_host`: what the person typed into the excluded sites, as the store keeps it.
    static func normalizeHost(_ text: String) -> String? {
        var raw = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !raw.isEmpty else { return nil }
        if !raw.contains("://") { raw = "https://" + raw }
        guard var host = URLComponents(string: raw)?.host else { return nil }
        if host.hasPrefix("www.") { host = String(host.dropFirst(4)) }
        guard host.contains("."), host.range(of: #"^[a-z0-9.-]{1,253}$"#, options: .regularExpression) != nil else {
            return nil
        }
        return host
    }

    static func adding(_ value: String, to list: [String]) -> [String] { Array(Set(list + [value])).sorted() }
    static func removing(_ value: String, from list: [String]) -> [String] { list.filter { $0 != value } }

    /// The browser names (`chrome`, `brave`, `edge`, `vivaldi`) whose addresses may be read, each with its first
    /// bundle id installed on this Mac. A name with nothing installed is not offered.
    static func browsers(_ lists: TracePolicyLists, installed: (String) -> Bool) -> [(name: String, bundleId: String)] {
        lists.urlBrowsers.keys.sorted().compactMap { name in
            guard let bundle = lists.urlBrowsers[name]?.first(where: installed) else { return nil }
            return (name, bundle)
        }
    }

    /// The browser's name as a person would say it.
    static func browserLabel(_ name: String) -> String {
        switch name {
        case "chrome": "Chrome"
        case "brave": "Brave"
        case "edge": "Edge"
        case "vivaldi": "Vivaldi"
        default: name.capitalized
        }
    }

    /// The person's click on one browser's switch. On: asks macOS for that browser (its Automation prompt — the one
    /// moment it may appear), then saves the choice. Off: saves it, asking nothing. Returns whether macOS allowed it
    /// (nil when turned off). The ask runs off the main thread: it waits on the person's answer.
    static func setBrowser(_ name: String, on: Bool, bundleId: String, current: [String],
                           asker: any TraceBrowserAsking,
                           update: ([String: TracePatchValue]) async throws -> Void) async throws -> Bool? {
        guard on else {
            try await update(["browsers": .strings(removing(name, from: current))])
            return nil
        }
        let allowed = await Task.detached(priority: .userInitiated) { asker.ask(bundleId: bundleId) }.value
        try await update(["browsers": .strings(adding(name, to: current))])
        return allowed
    }

    /// The chat and mail apps installed here that keep only their name and times, for "Allow titles for…".
    static func titleOffApps(_ lists: TracePolicyLists, installed: (String) -> Bool) -> [String] {
        Array(Set(lists.titleOffApps).union(TracePolicy.floorTitleOff)).filter(installed).sorted()
    }

    /// An app's name on this Mac, else its identifier.
    @MainActor
    static func appName(_ bundleId: String) -> String {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) else { return bundleId }
        return FileManager.default.displayName(atPath: url.path).replacingOccurrences(of: ".app", with: "")
    }

    @MainActor
    static func isInstalled(_ bundleId: String) -> Bool {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) != nil
    }
}

/// An app that is open now, for "Add an app" (never a guess: only what is running, or what the person types).
struct TracesRunningApp: Identifiable, Hashable {
    let bundleId: String
    let name: String
    var id: String { bundleId }

    @MainActor
    static func current(excluding: Set<String>) -> [TracesRunningApp] {
        let own = Bundle.main.bundleIdentifier
        let apps = NSWorkspace.shared.runningApplications.compactMap { app -> TracesRunningApp? in
            guard app.activationPolicy == .regular, let bundle = app.bundleIdentifier, bundle != own,
                  !excluding.contains(bundle) else { return nil }
            return TracesRunningApp(bundleId: bundle, name: app.localizedName ?? bundle)
        }
        return Array(Set(apps)).sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }
}

struct TracesControls: View {
    var probe: any TracePermissionProbe = LiveTracePermissionProbe()
    var asker: any TraceBrowserAsking = LiveTraceBrowserAsker()

    @Environment(TraceRecorder.self) private var recorder
    @State private var showConsent = false
    @State private var showBrowser = false
    @State private var confirmWipe = false
    @State private var note: String?
    @State private var busy = false
    @State private var granted: [TracePermission: Bool] = [:]
    @State private var browserAllowed: [String: Bool] = [:]
    @State private var appField = ""
    @State private var siteField = ""
    @State private var runningApps: [TracesRunningApp] = []

    private var settings: TraceSettings { recorder.settings }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            switch recorder.state {
            case .off:
                offControls
            case .notThisMac:
                line(Copy.Traces.notThisMac)
            case .failed:
                line(TracesControlsLogic.stateLine(recorder.state, settings: settings, now: .now))
                NeutralButton(title: Copy.Traces.tryAgain, size: .compact) { Task { await recorder.reload() } }
            case .recording, .paused:
                onControls
            }
            if let note {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .task { await recorder.refreshStatus() }
        .onAppear { readPermissions() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            readPermissions()
        }
        .sheet(isPresented: $showConsent) {
            TracesConsentSheet(probe: probe) { showConsent = false; readPermissions() }
        }
        .sheet(isPresented: $showBrowser) {
            TracesTimelineView(status: recorder.status) { showBrowser = false }
        }
        .confirmationDialog(Copy.Traces.wipeTitle, isPresented: $confirmWipe) {
            Button(Copy.Traces.wipeConfirm, role: .destructive) { wipe() }
            Button(Copy.Traces.cancel, role: .cancel) {}
        } message: {
            Text(Copy.Traces.wipeMessage)
        }
    }

    // MARK: - Off

    private var offControls: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            line(Copy.Traces.whatTheyAre)
            NeutralButton(title: Copy.Traces.turnOnEllipsis, size: .compact) { showConsent = true }
        }
    }

    // MARK: - On

    private var onControls: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                line(TracesControlsLogic.stateLine(recorder.state, settings: settings, now: .now))
                actions
            }
            recordSection
            memorySection
            keepSection
            excludeSection
            browsersSection
            titleAppsSection
            statusSection
        }
    }

    private var actions: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if recorder.state == .paused {
                NeutralButton(title: Copy.Traces.resume, size: .compact, isDisabled: busy) {
                    run { await recorder.resume() }
                }
            } else {
                pauseMenu
            }
            NeutralButton(title: Copy.Traces.forget, size: .compact, isDisabled: busy, help: Copy.Traces.forgetHelp) {
                run {
                    do { try await recorder.forget(minutes: 15); note = Copy.Traces.forgot } catch { note = describe(error) }
                }
            }
            NeutralButton(title: Copy.Traces.browse, size: .compact, help: Copy.Traces.browseHelp) { showBrowser = true }
        }
    }

    private var pauseMenu: some View {
        Menu {
            Button(Copy.Traces.pauseHour) { run { await recorder.pause(.hour) } }
            Button(Copy.Traces.pauseTomorrow) { run { await recorder.pause(.untilTomorrow) } }
            Button(Copy.Traces.pauseResumed) { run { await recorder.pause(.untilResumed) } }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.Traces.pause)
                Image(systemName: "chevron.down").font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .font(CicadaTheme.metaMediumFont)
            .foregroundStyle(CicadaTheme.textPrimary)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(height: CicadaTheme.scaled(NeutralButton.Size.compact.height))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgButton))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .help(Copy.Traces.pauseHelp)
        .disabled(busy)
    }

    // MARK: - What is recorded

    private var recordSection: some View {
        section(Copy.Traces.recordSection) {
            toggle(Copy.Traces.screenshots, help: Copy.Traces.screenshotsHelp, isOn: settings.screenshots) {
                patch(["screenshots": .bool($0)])
            }
            if settings.screenshots, granted[.screenRecording] == false {
                permissionLine(Copy.Traces.needsScreenRecording, button: Copy.Traces.allowScreenRecording,
                               kind: .screenRecording)
            }
            toggle(Copy.Traces.titles, help: Copy.Traces.titlesHelp, isOn: settings.titles) {
                patch(["titles": .bool($0)])
            }
            if settings.titles, granted[.accessibility] == false {
                permissionLine(Copy.Traces.needsAccessibility, button: Copy.Traces.allowAccessibility,
                               kind: .accessibility)
            }
        }
    }

    private func permissionLine(_ words: String, button: String, kind: TracePermission) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(words).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: button, size: .compact) {
                PermissionDragHelper.present(kind: kind, probe: probe) { granted[kind] = true }
            }
        }
    }

    // MARK: - Into memory

    private var memorySection: some View {
        section(Copy.Traces.memorySection) {
            toggle(Copy.Traces.youtube, help: Copy.Traces.youtubeHelp, isOn: settings.youtubeToWatchHistory) {
                patch(["youtube_to_watch_history": .bool($0)])
            }
            toggle(Copy.Traces.dailySummary, help: Copy.Traces.dailySummaryHelp, isOn: settings.dailySummary) { on in
                // The nested switch cannot outlive its parent.
                patch(on ? ["daily_summary": .bool(true)]
                         : ["daily_summary": .bool(false), "learn_from_summary": .bool(false)])
            }
            if settings.dailySummary {
                toggle(Copy.Traces.learn, help: Copy.Traces.learnHelp, isOn: settings.learnFromSummary) {
                    patch(["learn_from_summary": .bool($0)])
                }
                .padding(.leading, CicadaTheme.spacingLG)
            }
        }
    }

    // MARK: - How long

    private var keepSection: some View {
        section(Copy.Traces.keepSection) {
            Stepper(value: Binding(get: { settings.timelineDays },
                                   set: { patch(["timeline_days": .int($0)]) }), in: 1...30) {
                Text(Copy.Traces.timelineDays(settings.timelineDays)).font(CicadaTheme.bodyFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .controlSize(.small)
            Stepper(value: Binding(get: { settings.shotDays }, set: { patch(["shot_days": .int($0)]) }), in: 1...7) {
                Text(Copy.Traces.shotDays(settings.shotDays)).font(CicadaTheme.bodyFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .controlSize(.small)
            caption(Copy.Traces.keepHelp)
        }
    }

    // MARK: - Never recorded

    private var excludeSection: some View {
        section(Copy.Traces.excludeSection) {
            Text(Copy.Traces.excludedApps).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
            if settings.excludedApps.isEmpty {
                caption(Copy.Traces.excludedAppsNone)
            }
            ForEach(settings.excludedApps, id: \.self) { bundle in
                listRow(TracesControlsLogic.appName(bundle), detail: bundle, bundleId: bundle) {
                    patch(["excluded_apps": .strings(TracesControlsLogic.removing(bundle, from: settings.excludedApps))])
                }
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                Menu {
                    ForEach(runningApps) { app in
                        Button(app.name) { addApp(app.bundleId) }
                    }
                } label: {
                    Text(Copy.Traces.addApp).font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textPrimary)
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help(Copy.Traces.addAppHelp)
                .onAppear { refreshRunningApps() }
                .onReceive(NSWorkspace.shared.notificationCenter.publisher(
                    for: NSWorkspace.didLaunchApplicationNotification)) { _ in refreshRunningApps() }
                TextField("", text: $appField)
                    .cicadaField(prompt: Copy.Traces.bundlePrompt, isEmpty: appField.isEmpty)
                    .onSubmit { addTypedApp() }
                NeutralButton(title: Copy.Traces.add, size: .compact, isDisabled: appField.isEmpty) { addTypedApp() }
            }
            Text(Copy.Traces.excludedSites).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                .padding(.top, CicadaTheme.spacingSM)
            if settings.excludedSites.isEmpty {
                caption(Copy.Traces.excludedSitesNone)
            }
            ForEach(settings.excludedSites, id: \.self) { host in
                listRow(host, detail: nil, bundleId: nil) {
                    patch(["excluded_sites": .strings(TracesControlsLogic.removing(host, from: settings.excludedSites))])
                }
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField("", text: $siteField)
                    .cicadaField(prompt: Copy.Traces.sitePrompt, isEmpty: siteField.isEmpty)
                    .onSubmit { addSite() }
                NeutralButton(title: Copy.Traces.add, size: .compact, isDisabled: siteField.isEmpty) { addSite() }
            }
        }
    }

    // MARK: - Browsers and titles per app

    @ViewBuilder
    private var browsersSection: some View {
        let browsers = TracesControlsLogic.browsers(recorder.lists, installed: TracesControlsLogic.isInstalled)
        if !browsers.isEmpty {
            section(Copy.Traces.browsersSection) {
                caption(Copy.Traces.browsersHelp)
                ForEach(browsers, id: \.name) { browser in
                    let on = settings.browsers.contains(browser.name)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        toggle(TracesControlsLogic.browserLabel(browser.name), help: nil, isOn: on) { value in
                            setBrowser(browser.name, bundleId: browser.bundleId, on: value)
                        }
                        if on, browserAllowed[browser.bundleId] == false {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                caption(Copy.Traces.browserNotAllowed(TracesControlsLogic.browserLabel(browser.name)))
                                NeutralButton(title: Copy.Traces.askAgain, size: .compact) {
                                    setBrowser(browser.name, bundleId: browser.bundleId, on: true)
                                }
                            }
                        }
                    }
                }
            }
            .onAppear {
                for browser in browsers { browserAllowed[browser.bundleId] = asker.granted(bundleId: browser.bundleId) }
            }
        }
    }

    @ViewBuilder
    private var titleAppsSection: some View {
        let apps = TracesControlsLogic.titleOffApps(recorder.lists, installed: TracesControlsLogic.isInstalled)
        if settings.titles, !apps.isEmpty {
            section(Copy.Traces.titleAppsSection) {
                caption(Copy.Traces.titleAppsHelp)
                ForEach(apps, id: \.self) { bundle in
                    toggle(TracesControlsLogic.appName(bundle), help: nil, isOn: settings.titleApps.contains(bundle)) { on in
                        let next = on ? TracesControlsLogic.adding(bundle, to: settings.titleApps)
                                      : TracesControlsLogic.removing(bundle, from: settings.titleApps)
                        patch(["title_apps": .strings(next)])
                    }
                }
            }
        }
    }

    // MARK: - On this Mac

    private var statusSection: some View {
        section(Copy.Traces.statusSection) {
            Text(Eyebrow.text(Copy.Traces.daysKept(recorder.status.days),
                              Copy.Traces.sizeOnDisk(ByteCountFormatter.string(fromByteCount: Int64(recorder.status.bytes),
                                                                               countStyle: .file))))
                .font(CicadaTheme.bodyFont).monospacedDigit().foregroundStyle(CicadaTheme.textSecondary)
            if !recorder.status.key.isEmpty {
                caption(Copy.Traces.keyLives(recorder.status.key))
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.Traces.turnOff, size: .compact, isDisabled: busy, help: Copy.Traces.turnOffHelp) {
                    run { await recorder.turnOff() }
                }
                NeutralButton(title: Copy.Traces.wipe, size: .compact, isDisabled: busy) { confirmWipe = true }
            }
        }
    }

    // MARK: - Pieces

    private func line(_ words: String) -> some View {
        Text(words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func caption(_ words: String) -> some View {
        Text(words).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            content()
        }
    }

    private func toggle(_ title: String, help: String?, isOn: Bool, set: @escaping (Bool) -> Void) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Toggle(isOn: Binding(get: { isOn }, set: set)) {
                Text(title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            .toggleStyle(.switch)
            .controlSize(.small)
            .disabled(busy)
            if let help { caption(help) }
        }
    }

    private func listRow(_ title: String, detail: String?, bundleId: String?, remove: @escaping () -> Void) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let bundleId, let icon = InstalledAppIcon.image(bundleId: bundleId, size: CicadaTheme.scaled(16)) {
                Image(nsImage: icon).accessibilityHidden(true)
            }
            Text(title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
            if let detail, detail != title {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            IconButton(systemName: "xmark", help: Copy.Traces.removeHelp(title), accessibilityLabel: Copy.Traces.remove,
                       action: remove)
        }
    }

    // MARK: - Writes (every one through the recorder)

    private func patch(_ values: [String: TracePatchValue]) {
        run {
            do { try await recorder.update(values); note = nil } catch { note = describe(error) }
        }
    }

    private func run(_ work: @escaping @MainActor () async -> Void) {
        Task { @MainActor in
            busy = true
            defer { busy = false }
            await work()
        }
    }

    private func addTypedApp() {
        let bundle = appField.trimmingCharacters(in: .whitespacesAndNewlines)
        guard TracesControlsLogic.validBundle(bundle) else { note = Copy.Traces.badBundle; return }
        appField = ""
        addApp(bundle)
    }

    private func addApp(_ bundle: String) {
        patch(["excluded_apps": .strings(TracesControlsLogic.adding(bundle, to: settings.excludedApps))])
        runningApps.removeAll { $0.bundleId == bundle }
    }

    private func addSite() {
        guard let host = TracesControlsLogic.normalizeHost(siteField) else { note = Copy.Traces.badSite; return }
        siteField = ""
        patch(["excluded_sites": .strings(TracesControlsLogic.adding(host, to: settings.excludedSites))])
    }

    private func setBrowser(_ name: String, bundleId: String, on: Bool) {
        let current = settings.browsers
        let asker = self.asker
        run {
            do {
                let allowed = try await TracesControlsLogic.setBrowser(name, on: on, bundleId: bundleId,
                                                                       current: current, asker: asker) {
                    try await recorder.update($0)
                }
                if let allowed { browserAllowed[bundleId] = allowed }
                note = nil
            } catch {
                note = describe(error)
            }
        }
    }

    private func wipe() {
        run {
            do { try await recorder.wipe(); note = Copy.Traces.wiped } catch { note = describe(error) }
        }
    }

    private func refreshRunningApps() {
        runningApps = TracesRunningApp.current(excluding: Set(settings.excludedApps))
    }

    private func readPermissions() {
        for kind in [TracePermission.accessibility, .screenRecording] { granted[kind] = probe.granted(kind) }
    }

    private func describe(_ error: Error) -> String { TraceRecorder.describe(error) }
}
