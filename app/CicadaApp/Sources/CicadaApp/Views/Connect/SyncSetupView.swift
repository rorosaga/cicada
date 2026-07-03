import SwiftUI
import AppKit

// MARK: - Capture source catalog model

/// One place Cicada can pull memory from without a chat session in the loop —
/// bookmarks, forwarded messages, feeds. `id` doubles as the optional bundled-
/// logo resource name (`Resources/logos/<id>.png`); when no logo ships, the
/// square tile falls back to an SF Symbol on a brand-colored background, mirroring
/// `AgentTile` in ConnectView.swift.
struct CaptureSource: Identifiable {
    let id: String
    let name: String
    /// The `origin` tag this source writes onto captured episodes — kept
    /// visible on the card so provenance is never a guess.
    let origin: String
    let symbol: String
    let monogram: String
    let brand: Color
    let blurb: String
    let steps: [AgentSetup.SetupStep]
    var comingSoon = false
}

/// Builds the capture-source catalog with real absolute paths, mirroring
/// `AgentSetupCatalog` in ConnectView.swift.
enum CaptureSourceCatalog {
    static func all(home: String) -> [CaptureSource] {
        let envPath = "\(home)/api/.env"

        return [
            CaptureSource(
                id: "chrome",
                name: "Chrome bookmarks",
                origin: "chrome-bookmark",
                symbol: "globe",
                monogram: "Ch",
                brand: Color(hex: 0x4285F4),
                blurb: "Cicada polls your Chrome bookmarks and imports new ones — keyless, automatic.",
                steps: [
                    .init(
                        label: "No setup needed — click \"Sync now\" on the Capture page",
                        note: "Reads the local Chrome Bookmarks file directly; nothing leaves your Mac and no account is required."
                    ),
                ]
            ),
            CaptureSource(
                id: "safari",
                name: "Safari bookmarks",
                origin: "safari-bookmark",
                symbol: "safari",
                monogram: "Sf",
                brand: Color(hex: 0x00A2E8),
                blurb: "Same idea as Chrome — Cicada polls your Safari bookmarks and imports new ones, keyless and automatic.",
                steps: [
                    .init(
                        label: "No setup needed — click \"Sync now\" on the Capture page",
                        note: "Reads ~/Library/Safari/Bookmarks.plist directly; nothing leaves your Mac and no account is required."
                    ),
                ]
            ),
            CaptureSource(
                id: "telegram",
                name: "Telegram",
                origin: "telegram",
                symbol: "paperplane.fill",
                monogram: "Tg",
                brand: Color(hex: 0x26A5E4),
                blurb: "Forward yourself links, videos, and notes in Telegram and they land in your memory. The most flexible capture source — anything you can forward, Cicada can queue.",
                steps: [
                    .init(
                        label: "Create a bot with @BotFather and copy its token",
                        command: "/newbot",
                        note: "In Telegram, message @BotFather, send /newbot, follow the prompts, and copy the bot token it gives you."
                    ),
                    .init(
                        label: "Add the token to Cicada's backend config, then restart the backend",
                        command: "CICADA_TELEGRAM_BOT_TOKEN=<your token>",
                        note: "Put this line in \(envPath), then restart the backend so it picks up the new variable."
                    ),
                    .init(
                        label: "Point the bot's webhook at Cicada's capture endpoint",
                        command: "curl \"https://api.telegram.org/bot<token>/setWebhook?url=<your-public-url>/capture/telegram\"",
                        note: "Needs a public HTTPS URL that reaches your Mac — e.g. a cloudflared or ngrok tunnel in front of the local backend."
                    ),
                ]
            ),
            CaptureSource(
                id: "rss",
                name: "RSS feeds",
                origin: "rss",
                symbol: "dot.radiowaves.left.and.right",
                monogram: "RS",
                brand: Color(hex: 0xEE802F),
                blurb: "Subscribe to a feed and new posts flow in as they're published — no polling account, no login.",
                steps: [
                    .init(
                        label: "Paste a feed URL on the Capture page",
                        note: "Cicada checks subscribed feeds on the same schedule as bookmark sync and queues new entries."
                    ),
                ]
            ),
            CaptureSource(
                id: "share-sheet",
                name: "macOS / iOS Share Sheet",
                origin: "share-sheet",
                symbol: "square.and.arrow.up",
                monogram: "Sh",
                brand: Color(hex: 0x8896FF),
                blurb: "Share to Cicada from any app — Safari, Photos, Notes, whatever you're in — the way you'd share to Reminders or Notes today.",
                steps: [
                    .init(
                        label: "Coming soon",
                        note: "The share extension isn't built yet. Until it ships, use Telegram forwarding or bookmarks to get things into Cicada."
                    ),
                ],
                comingSoon: true
            ),
        ]
    }
}

// MARK: - Sync setup page

/// The "Capture sources" page: how memory gets fed from the places the user
/// already saves things, without a chat session in the loop. Mirrors
/// ConnectView.swift's layout (PageHeader, glassCard rows, CommandBox steps)
/// so the two setup pages read as one system.
struct SyncSetupView: View {
    private let home = BackendProcess.installRoot().path
    @State private var sources: [CaptureSource] = []

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(
                title: "Capture sources",
                subtitle: "Memory doesn't only come from chat — these feed it too."
            )

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    introCard

                    ForEach(sources) { source in
                        CaptureSourceCard(source: source)
                    }

                    footerCard
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXXL)
            }
        }
        .background(CicadaTheme.background)
        .onAppear {
            if sources.isEmpty { sources = CaptureSourceCatalog.all(home: home) }
        }
    }

    private var introCard: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            BookwormView(state: .happy)
                .frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Bring what you already save")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Bookmarks, forwarded messages, and feeds are as much a source of memory as conversation. Wire up the sources below and Cicada keeps them flowing in on its own — each one tags what it captures with an origin so you can always tell where a piece of memory came from.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var footerCard: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: "moon.fill")
                .font(.system(size: 16))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: 44, height: 44)
                .background(RoundedRectangle(cornerRadius: 10).fill(CicadaTheme.surfaceElevated))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Everything waits for the next Sleep cycle")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Everything captured waits in a queue and is consolidated on the next Sleep cycle (or when your agent runs the cicada-librarian skill) — no key needed.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }
}

// MARK: - Source card

private struct CaptureSourceCard: View {
    let source: CaptureSource

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                SourceTile(source: source)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(source.name)
                            .font(CicadaTheme.headingFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if source.comingSoon {
                            Text("COMING SOON")
                                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                                .tracking(0.8)
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .padding(.horizontal, CicadaTheme.spacingSM)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(CicadaTheme.surfaceElevated))
                                .overlay(Capsule().stroke(CicadaTheme.border, lineWidth: 1))
                        }
                    }
                    Text(source.blurb)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("origin: \(source.origin)")
                        .font(.system(size: 10, weight: .regular, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .padding(.top, 2)
                }
                Spacer(minLength: 0)
            }

            ForEach(source.steps) { step in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(step.label)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    if let command = step.command {
                        CommandBox(command: command)
                    }
                    if let note = step.note {
                        Text(note)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .opacity(source.comingSoon ? 0.75 : 1.0)
    }
}

// MARK: - Square identity tile

/// 44pt square icon tile. Prefers a bundled `Resources/logos/<id>.png` (drop
/// official marks there — e.g. telegram.png, chrome.png — to upgrade the
/// page); falls back to an SF Symbol on a brand-colored background, and
/// finally to a plain monogram if neither is available. Mirrors `AgentTile`
/// in ConnectView.swift.
private struct SourceTile: View {
    let source: CaptureSource

    var body: some View {
        Group {
            if let logo = Self.logo(for: source.id) {
                Image(nsImage: logo)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .padding(6)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.92)))
            } else {
                Image(systemName: source.symbol)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(
                        LinearGradient(
                            colors: [source.brand, source.brand.opacity(0.7)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            }
        }
        .frame(width: 44, height: 44)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(CicadaTheme.border, lineWidth: 1))
    }

    private static func logo(for id: String) -> NSImage? {
        guard let url = Bundle.module.url(
            forResource: id, withExtension: "png", subdirectory: "Resources/logos"
        ) else { return nil }
        return NSImage(contentsOf: url)
    }
}
