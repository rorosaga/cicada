import SwiftUI

// G227 follow-up (owner 2026-10-29): "this should be something that can be merged and stuff down the line, or entities
// can be separated if they were joined like what happened now." Merge is one sheet from the page's menu (DR-81: actions live
// in the page menu, never a fold), built only from patterns the app already has — the Add-skill sheet's shape (a
// heading, a lead, a checkbox list, Cancel + the one primary action, DR-40), `Tag` for a qualifier (DR-44), a
// `SectionLabel` per group. No disclosure, nothing folds (owner taste; DR-81). Each join is one commit the person can
// take back from the page's History (`EntityHistoryView`'s Undo).

/// Merge this page into another: pick the page that stays, read what happens, Merge.
struct MergePageSheet: View {
    let entity: Entity
    let close: () -> Void
    let done: (String) -> Void

    @Environment(Store.self) private var store
    @State private var query = ""
    @State private var picked: GraphNode?
    @State private var working = false
    @State private var problem: String?
    @FocusState private var fieldFocused: Bool

    private var candidates: [GraphNode] {
        let nodes = (store.graph.value?.nodes ?? []).filter { $0.id != entity.id && !$0.isHub }
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else {
            // The likeliest first: pages with exactly this title (G227's same-name pages).
            return Array(nodes.filter { $0.name.lowercased() == entity.name.lowercased() }.prefix(8))
        }
        return Array(nodes.filter { $0.name.lowercased().contains(q) || $0.id.contains(q) }
            .sorted { ($0.name.lowercased().hasPrefix(q) ? 0 : 1, $0.name) < ($1.name.lowercased().hasPrefix(q) ? 0 : 1, $1.name) }
            .prefix(12))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.PageJoin.mergeTitle(entity.name)).font(CicadaTheme.headingFont)
            TextField("", text: $query)
                .focused($fieldFocused)
                .cicadaField(isFocused: fieldFocused, prompt: Copy.PageJoin.mergeSearch, isEmpty: query.isEmpty)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    if candidates.isEmpty, !query.isEmpty {
                        Text(Copy.PageJoin.mergeNoMatch).font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    ForEach(candidates, id: \.id) { node in
                        Button { picked = node } label: {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                Image(systemName: picked?.id == node.id ? "largecircle.fill.circle" : "circle")
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                Text(node.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                                QualifierTag(qualifier: node.qualifier)
                                Spacer(minLength: 0)
                            }
                            .padding(.vertical, CicadaTheme.scaled(4))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(240))
            if let picked {
                Text(Copy.PageJoin.mergeExplain(entity.name, picked.name))
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let problem {
                Label(problem, systemImage: "exclamationmark.circle")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if working { ProgressView().controlSize(.small) }
                Spacer()
                TextButton(title: Copy.PageJoin.cancel, action: close).keyboardShortcut(.cancelAction)
                PrimaryActionButton(title: Copy.PageJoin.mergeAction) { merge() }
                    .disabled(picked == nil || working)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(520))
        .onAppear { fieldFocused = true }
    }

    private func merge() {
        guard let target = picked else { return }
        working = true
        problem = nil
        Task {
            defer { working = false }
            do {
                let answer = try await APIClient.shared.mergePage(entityId: entity.id, into: target.id)
                store.toast = Copy.PageJoin.merged(target.name)
                done(answer.entityId)
            } catch {
                problem = PageJoinWords.problem(error)
            }
        }
    }
}

/// Owner 2026-10-29: "the separation of entities should mainly happen by talking to an agent." The page's quiet way in
/// copies a ready sentence for the person's own agent, which proposes the split in the conversation and applies it on
/// their yes (`cicada_split_page`); the app holds no checklist of its own.
enum SeparateHandOff {
    static func prompt(id: String, name: String) -> String { Copy.PageJoin.separatePrompt(name, id) }

    @MainActor static func copy(id: String, name: String, store: Store) {
        AppPasteboard.copy(prompt(id: id, name: name))
        store.toast = Copy.PageJoin.separateCopied
    }
}

enum PageJoinWords {
    /// The server's own sentence for a refusal (it says what to do instead), else a plain failure.
    static func problem(_ error: Error) -> String {
        if case let APIError.httpError(_, body) = error,
           let data = body.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = json["detail"] as? String {
            return detail
        }
        return Copy.PageJoin.failed
    }
}
