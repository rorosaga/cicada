import SwiftUI

/// ROR-118 (owner, Sources round 1) — before the switch of a source an agent reads in the person's browser, a short
/// picture of who does what, drawn with the person's own things: their assistant app by its icon, their browser by its
/// icon, the site by its mark, and Cicada. It plays once, by itself, the first time on this Mac, and again whenever the
/// person clicks Replay (DR-60: a key never animates; with Reduce Motion it is the finished picture). Under it, four
/// honest lines: what is read, whose session, who else sees it, how to stop. DR-9 (a ring, no shadow), DR-52 (marks
/// are the real ones), DR-61 (explanatory motion, durations in `CicadaMotion`).
struct WebReadingCard: View {
    let entry: SourceCatalogEntry

    @Environment(AgentLiveProbe.self) private var agents: AgentLiveProbe?
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Said once on this Mac: the first card ever shown plays; every other shows the finished picture.
    @AppStorage("cicada.webReading.seen") private var seen = false
    /// The beat the picture has reached: -1 before it starts, 0...3 while it plays, 4 finished.
    @State private var beat = WebReadingScene.beats
    @State private var browser = BrowserLook.live()
    @State private var playing = false

    private var app: AgentCatalogEntry? { WebReadingScene.app(rows: Array(agents?.rows.values ?? [:].values)) }
    private var appName: String { app?.name ?? Copy.WebReading.yourAssistant }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            scene
            if app != nil {
                caption
                honestLines
            } else {
                noApp
            }
        }
        .padding(CicadaTheme.scaled(16))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .task(id: app?.id) { await start() }
    }

    // MARK: - The picture

    private var scene: some View {
        let lit = WebReadingScene.litNodes(atBeat: beat)
        let has = app != nil
        return HStack(alignment: .top, spacing: 0) {
            node(name: Copy.WebReading.cicada, lit: true) {
                Image(nsImage: NSApp.applicationIconImage).resizable().interpolation(.high).scaledToFit()
            }
            lane(forward: has && beat >= 1, back: has && beat >= 4)
            node(name: appName, lit: has && lit >= 2, dashed: !has) { appIcon }
            lane(forward: has && beat >= 2, back: has && beat >= 4)
            node(name: browser.name, lit: has && lit >= 3) { browserIcon }
            lane(forward: has && beat >= 3, back: has && beat >= 4)
            node(name: entry.title, lit: has && lit >= 4) { siteIcon }
        }
        .animation(CicadaMotion.webLight(reduceMotion: reduceMotion), value: beat)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(WebReadingScene.caption(beat: WebReadingScene.beats, entry: entry, app: appName,
                                                    browser: browser.name))
    }

    private func node<Icon: View>(name: String, lit: Bool, dashed: Bool = false,
                                  @ViewBuilder icon: () -> Icon) -> some View {
        let side = CicadaTheme.scaled(56)
        let shape = CicadaTheme.shape(side * 0.25)
        return VStack(spacing: CicadaTheme.scaled(6)) {
            ZStack {
                shape.fill(CicadaTheme.surfaceElevated)
                icon().frame(width: side * 0.66, height: side * 0.66)
                if dashed { shape.strokeBorder(CicadaTheme.border, style: StrokeStyle(lineWidth: 1, dash: [4, 3])) }
            }
            .frame(width: side, height: side)
            .ringed(in: shape)
            Text(name).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1).truncationMode(.tail)
        }
        .opacity(lit ? 1 : 0.35)
        .frame(width: CicadaTheme.scaled(96))
        .help(name)
    }

    /// The two lanes between nodes: the way out (a line drawn left to right) and the way back (right to left).
    private func lane(forward: Bool, back: Bool) -> some View {
        VStack(spacing: CicadaTheme.scaled(10)) {
            line(on: forward, towardsTrailing: true)
            // The way back is drawn only when it is the beat (never a second dim line to read past).
            line(on: back, towardsTrailing: false).opacity(back ? 1 : 0)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, CicadaTheme.scaled(14))
        .animation(CicadaMotion.webTravel(reduceMotion: reduceMotion), value: forward)
        .animation(CicadaMotion.webTravel(reduceMotion: reduceMotion), value: back)
    }

    private func line(on: Bool, towardsTrailing: Bool) -> some View {
        ZStack(alignment: towardsTrailing ? .leading : .trailing) {
            Capsule().fill(CicadaTheme.border).frame(height: 1.5)
            Capsule().fill(towardsTrailing ? CicadaTheme.accent : CicadaTheme.info).frame(height: 1.5)
                .scaleEffect(x: on ? 1 : 0.001, anchor: towardsTrailing ? .leading : .trailing)
        }
        .overlay(alignment: towardsTrailing ? .trailing : .leading) {
            Image(systemName: towardsTrailing ? "chevron.right" : "chevron.left")
                .font(CicadaTheme.font(size: 9, weight: .semibold))
                .foregroundStyle(on ? (towardsTrailing ? CicadaTheme.accent : CicadaTheme.info) : CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder private var appIcon: some View {
        if let app, let mark = app.mark, case let logo = (mark == "claude-code" ? "claude" : mark), LogoImage.exists(name: logo) {
            LogoImage(name: logo, size: CicadaTheme.scaled(36))
        } else {
            Image(systemName: app?.symbol ?? "terminal").font(CicadaTheme.font(size: 24)).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder private var browserIcon: some View {
        if let icon = browser.icon {
            Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
        } else {
            Image(systemName: "globe").font(CicadaTheme.font(size: 24)).foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    @ViewBuilder private var siteIcon: some View {
        let origin = entry.origin
        if let bundle = OriginIconography.appBundleId(for: origin), let icon = InstalledAppIcon.image(bundleId: bundle, size: 40) {
            Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
        } else if let logo = OriginIconography.logoName(for: origin), LogoImage.exists(name: logo) {
            LogoImage(name: logo, size: CicadaTheme.scaled(36))
        } else {
            Image(systemName: OriginIconography.symbol(for: origin)).font(CicadaTheme.font(size: 24))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    // MARK: - The words

    private var caption: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(WebReadingScene.caption(beat: min(max(beat, 0), WebReadingScene.beats), entry: entry, app: appName,
                                         browser: browser.name))
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: CicadaTheme.spacingSM)
            Button { Task { await play() } } label: {
                Label(Copy.WebReading.replay, systemImage: "arrow.counterclockwise").font(CicadaTheme.metaFont)
            }
            .buttonStyle(.cicadaPlain)
            .foregroundStyle(CicadaTheme.textSecondary)
            .disabled(playing)
            .help(Copy.WebReading.replayHelp)
            .accessibilityLabel(Copy.WebReading.replay)
        }
    }

    private var honestLines: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            line("eye", Copy.WebReading.whatIsRead(list: WebReadingScene.list(entry.id), app: appName))
            line("person.crop.circle", Copy.WebReading.whoseSession)
            line("building.2", Copy.WebReading.whoSees(app: appName))
            line("power", Copy.WebReading.oneClick)
        }
    }

    private func line(_ symbol: String, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(8)) {
            Image(systemName: symbol).font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(16))
            Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var noApp: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.WebReading.noApp).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.WebReading.noAppLine).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            Button(Copy.WebReading.openAgents) { router.routeToAgents() }
                .buttonStyle(.cicadaPlain).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.accentText)
        }
    }

    // MARK: - Playing

    /// The first showing on this Mac plays; any other opens finished. Called again when the app arrives or changes.
    private func start() async {
        guard app != nil else { beat = WebReadingScene.beats; return }
        if WebReadingScene.autoplays(seen: seen, hasApp: true, reduceMotion: reduceMotion) {
            seen = true
            await play()
        } else {
            beat = WebReadingScene.beats
        }
    }

    private func play() async {
        guard !reduceMotion, !playing else { beat = WebReadingScene.beats; return }
        playing = true
        defer { playing = false }
        beat = -1
        try? await Task.sleep(for: .seconds(CicadaMotion.webStartDelay))
        for next in 0...WebReadingScene.beats {
            if Task.isCancelled { break }
            beat = next
            try? await Task.sleep(for: .seconds(CicadaMotion.webTravelDuration + CicadaMotion.webBeatHold))
        }
        beat = WebReadingScene.beats
    }
}

/// The person's own browser: the default handler of web links, by its installed icon and name. One Launch Services
/// asks, once; nothing about their browsing is read.
struct BrowserLook {
    let name: String
    let icon: NSImage?

    static func live() -> BrowserLook {
        guard let url = URL(string: "https://example.com"), let app = NSWorkspace.shared.urlForApplication(toOpen: url) else {
            return BrowserLook(name: Copy.WebReading.yourBrowser, icon: nil)
        }
        let name = FileManager.default.displayName(atPath: app.path).replacingOccurrences(of: ".app", with: "")
        return BrowserLook(name: name, icon: NSWorkspace.shared.icon(forFile: app.path))
    }
}
