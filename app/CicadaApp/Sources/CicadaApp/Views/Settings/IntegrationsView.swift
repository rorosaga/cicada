import SwiftUI

/// Settings → Integrations (G126) — a categorized, logo-first page over the
/// existing `GET /sources/channels` registry, reusing `ChannelActions` and
/// `AddSourceTile` rather than adding a second sync path.
///
/// This is Task 2's minimal stub, just enough for the five-section sidebar
/// (Task 2) to build and route to a real page. Task 4 fleshes out this same
/// file in place — categorized rows (`IntegrationCategory`), state lines
/// (`IntegrationRowState`), and the `ConnectorSetupPanel` popover — rather
/// than creating a second `IntegrationsView.swift`.
struct IntegrationsView: View {
    var body: some View {
        PageHeader(title: Copy.integrations, subtitle: Copy.integrationsSubtitle) {}
    }
}
