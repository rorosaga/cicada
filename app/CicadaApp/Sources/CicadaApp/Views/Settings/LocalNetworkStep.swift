import SwiftUI

/// G132 ruling 51f, owner D4 — when Local Network is asked: once, at the person's first *Share this memory*, *Keep a
/// full copy here* or *Pair a device* click, never before and never in onboarding's list. After the step was seen and
/// while Local Network is not allowed, the same row sits on Devices' list card (above *Pair a device*), so a skipped or
/// refused answer can still be given. Hyrum: one new key, `cicada.devices.localNetworkStepSeen`.
enum LocalNetworkStep {
    static let seenKey = "cicada.devices.localNetworkStepSeen"

    static func due(defaults: UserDefaults = .standard, memory: LocalNetworkMemory = LocalNetworkMemory()) -> Bool {
        !memory.asked && !defaults.bool(forKey: seenKey)
    }

    static func rowShown(defaults: UserDefaults = .standard, memory: LocalNetworkMemory = LocalNetworkMemory()) -> Bool {
        defaults.bool(forKey: seenKey) && memory.state != .granted
    }

    static func markSeen(defaults: UserDefaults = .standard) { defaults.set(true, forKey: seenKey) }
}

/// The step's body: the onboarding Permissions step's own row (`PermissionList`, one row: Local network, what it
/// unlocks, *Allow…* raising macOS's prompt on that click only, or *Allowed*), one line about the firewall's question
/// only when the firewall is on, and *Continue* — the surface's one primary (DR-5, DR-40). Nothing is required: Continue
/// never waits on the row. Reuses the row, its card (DR-9, DR-10) and its words; no new pattern, no motion (DR-60).
struct LocalNetworkStepBody: View {
    /// The sheet's own Cancel, on the same foot as Continue (the pair sheet's); nil draws Continue alone.
    var onCancel: (() -> Void)? = nil
    var onContinue: () -> Void
    @State private var firewallOn = false
    @State private var going = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PermissionList(permissions: [.localNetwork], place: .settings).settingsCardSurface()
            if firewallOn {
                Text(Copy.LocalNetwork.firewall)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("localNetwork.firewall")
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer()
                if let onCancel { TextButton(title: Copy.DevicesPage.cancel) { onCancel() } }
                PrimaryActionButton(title: Copy.LocalNetwork.continueTitle) {
                    guard !going else { return }
                    going = true
                    LocalNetworkStep.markSeen()
                    Task {
                        await LanDiscovery.shared.stepDone()
                        onContinue()
                    }
                }
                .accessibilityIdentifier("localNetwork.continue")
            }
        }
        .task { firewallOn = await LanDiscovery.firewallOn() }
    }
}

/// The step on its own sheet, titled by the act the person clicked (*Share this memory…*, *Keep a full copy here*), so
/// no title repeats the row (owner, 2026-11-03: copy said once). *Pair a device* draws the body inside its own sheet.
struct LocalNetworkStepSheet: View {
    let title: String
    var onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(title).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            LocalNetworkStepBody(onContinue: onDone)
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(480))
        .background(CicadaTheme.background)
    }
}
