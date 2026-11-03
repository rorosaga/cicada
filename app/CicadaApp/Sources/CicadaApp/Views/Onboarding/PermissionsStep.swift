import SwiftUI

/// Onboarding's Permissions step (owner 2026-11-03, verbatim: *"in onboarding we should have one step to ask for all
/// permissions and do it as all apps … they overlay the app so you drag and drop it into the allowed list"*; G92): every
/// macOS permission Cicada's app can use, one row each, live (`MacPermissionsCard`, the same rows as Settings → Privacy &
/// data). A drag list opens System Settings with the floating drag helper over it; a prompt asks on the row's click;
/// nothing asks before a click, and every row can be skipped — Continue and Skip both move on. Allowing a permission
/// turns no source on: the Sources step after it does (a browser is read only once the person turned it on).
/// DR-5, DR-9, DR-12, DR-17, DR-39, DR-52, DR-59, DR-60; DESIGN_RULES §9 2026-11-03.
struct PermissionsStep: View {
    let place: PermissionPlace
    var onGranted: ((MacPermission) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.MacPermissions.title, subline: Copy.MacPermissions.subline)
            MacPermissionsCard(place: place, onGranted: onGranted)
        }
    }
}
