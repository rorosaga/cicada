import Observation
import SwiftUI

/// Onboarding's skills step (owner 2026-10-15): "suggest installing these two skills … so that they come with Cicada.
/// By default they come, but the person can say no." The two harnesses are ticked, the video skill is listed but not
/// ticked, and No thanks unticks all. Nothing installs on this page: Continue is the consent (`OnboardingView.advance`
/// posts the ticks, and the backend installs in the background). A decline is recorded and never asked again; the
/// Skills page installs later. The backend owns every decision (`GET|POST /skills/onboarding`).
@MainActor
@Observable
final class SkillsStepModel {
    private(set) var offer: SkillsOnboardingOffer?
    var ticked: Set<String> = []
    private(set) var problem: String?
    private(set) var answered = false
    private let api: SkillsAPI

    init(api: SkillsAPI = APIClient.shared) { self.api = api }

    var uvPresent: Bool { offer?.uv.present ?? false }

    /// A suggestion that can be ticked now: not installed already, and not a tool while uv is missing.
    func available(_ s: SkillsOnboardingOffer.Suggestion) -> Bool {
        s.installed != true && !(s.needsUv == true && !uvPresent)
    }

    func load() async {
        let first = offer == nil
        do { offer = try await api.skillsOnboarding() } catch { problem = SkillsError.words(error); return }
        problem = nil
        if first { ticked = Self.defaults(offer?.suggestions ?? [], uvPresent: uvPresent) }
        else { ticked = ticked.filter { id in offer?.suggestions.first { $0.id == id }.map(available) ?? false } }
    }

    /// The catalog's defaults, minus what is installed already or cannot install without uv. Pure.
    nonisolated static func defaults(_ suggestions: [SkillsOnboardingOffer.Suggestion], uvPresent: Bool) -> Set<String> {
        Set(suggestions.filter { $0.default == true && $0.installed != true && !($0.needsUv == true && !uvPresent) }
            .map(\.id))
    }

    func noThanks() { ticked = [] }

    /// Continue: what stays ticked installs in the background; nothing ticked is "No thanks", recorded.
    func submit() async {
        guard offer != nil else { return }
        let ids = (offer?.suggestions ?? []).map(\.id).filter { ticked.contains($0) }
        _ = try? await api.answerSkillsOnboarding(install: ids, agents: [])
        answered = true
    }
}

struct SkillsStepPage: View {
    let model: SkillsStepModel

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.Skills.onboardingTitle, subline: Copy.Skills.onboardingLead)
            if let problem = model.problem {
                Text(problem).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let offer = model.offer {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(offer.suggestions.enumerated()), id: \.element.id) { index, item in
                        if index > 0 { Divider().overlay(CicadaTheme.border) }
                        row(item)
                    }
                }
                .settingsCardSurface()
                if !offer.uv.present && offer.suggestions.contains(where: { $0.needsUv == true }) {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        Text(Copy.Skills.onboardingNoUv).font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textSecondary).fixedSize(horizontal: false, vertical: true)
                        if !offer.uv.installCommand.isEmpty { CommandBox(command: offer.uv.installCommand) }
                        HStack(spacing: CicadaTheme.spacingSM) {
                            if let url = URL(string: offer.uv.installUrl) {
                                Link(Copy.Skills.getUv, destination: url).font(CicadaTheme.metaFont)
                            }
                            NeutralButton(title: Copy.Skills.checkAgain, size: .compact) {
                                Task { await model.load() }
                            }
                        }
                    }
                }
                HStack {
                    Text(Copy.Skills.onboardingFoot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    TextButton(title: Copy.Skills.noThanks) { model.noThanks() }
                }
            }
        }
        .task { await model.load() }
    }

    private func row(_ item: SkillsOnboardingOffer.Suggestion) -> some View {
        let available = model.available(item)
        return HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Toggle("", isOn: Binding(get: { model.ticked.contains(item.id) || item.installed == true },
                                     set: { on in
                                         if on { model.ticked.insert(item.id) } else { model.ticked.remove(item.id) }
                                     }))
                .toggleStyle(.checkbox)
                .labelsHidden()
                .accessibilityLabel(item.title ?? item.id)
                .disabled(!available)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(item.title ?? item.id).font(CicadaTheme.font(size: 14, weight: .medium))
                    if item.installed == true { Tag(text: Copy.Skills.alreadyInstalled) }
                    else if item.default != true { Tag(text: Copy.Skills.offByDefault) }
                }
                if let line = item.line {
                    Text(line).font(CicadaTheme.bodyFont).fixedSize(horizontal: false, vertical: true)
                }
                if let asks = item.asks {
                    Text(asks).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .opacity(available || item.installed == true ? 1 : NeutralButton.disabledOpacity)
    }
}
