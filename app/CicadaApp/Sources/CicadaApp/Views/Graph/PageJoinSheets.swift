import SwiftUI

// G227 follow-up (owner 2026-10-29): "this should be something that can be merged and stuff down the line, or entities
// can be separated if they were joined like what happened now." Two sheets from the page's menu (DR-81: actions live
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
                                Text(node.id).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
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

/// Split this page: tick what is about the other thing (the read's suggestions pre-ticked), name it, Split.
struct SplitPageSheet: View {
    let entity: Entity
    let close: () -> Void
    let done: (String) -> Void

    @Environment(Store.self) private var store
    @State private var plan: SplitPlan?
    @State private var selection = SplitSelection()
    @State private var failed = false
    @State private var suggesting = false
    @State private var working = false
    @State private var problem: String?
    @FocusState private var nameFocused: Bool

    private static let types = ["person", "project", "company", "concept", "tool", "skill", "location", "directory"]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.PageJoin.splitTitle(entity.name)).font(CicadaTheme.headingFont)
            Text(Copy.PageJoin.splitExplain).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let plan {
                content(plan)
            } else if failed {
                Text(Copy.PageJoin.failed).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                SectionLoading(text: Copy.PageJoin.loading)
            }
            if let problem {
                Label(problem, systemImage: "exclamationmark.circle")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if plan != nil {
                    NeutralButton(title: suggesting ? Copy.PageJoin.splitSuggesting : Copy.PageJoin.splitSuggest,
                                  size: .compact, isDisabled: suggesting || working) { Task { await load(suggest: true) } }
                }
                if working { ProgressView().controlSize(.small) }
                Spacer()
                TextButton(title: Copy.PageJoin.cancel, action: close).keyboardShortcut(.cancelAction)
                PrimaryActionButton(title: Copy.PageJoin.splitAction) { split() }
                    .disabled(plan == nil || selection.isEmpty || working)
                    .help(selection.isEmpty ? Copy.PageJoin.nothingPicked : "")
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(680))
        .task { await load(suggest: false) }
    }

    @ViewBuilder
    private func content(_ plan: SplitPlan) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            TextField("", text: $selection.name)
                .focused($nameFocused)
                .cicadaField(isFocused: nameFocused, prompt: Copy.PageJoin.newName, isEmpty: selection.name.isEmpty)
            Picker(Copy.PageJoin.newType, selection: $selection.type) {
                ForEach(Self.types, id: \.self) { Text(EntityType(rawValue: $0)?.label ?? $0).tag($0) }
            }
            .fixedSize()
        }
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                group(Copy.PageJoin.sentences, plan.sentences) { s in
                    check(s.text, detail: s.reason, on: bind(\.sentences, s.n))
                }
                group(Copy.PageJoin.beliefs, plan.claims) { c in
                    check(c.text, detail: nil, on: bind(\.claims, c.id))
                }
                group(Copy.PageJoin.sources, plan.sources) { s in
                    check(s.label ?? s.ref, detail: s.label == nil ? nil : s.ref, on: bind(\.sources, s.ref))
                }
                group(Copy.PageJoin.conversations, plan.conversations) { c in
                    check(c.title ?? c.id, detail: c.date, on: bind(\.episodes, c.id))
                }
                group(Copy.PageJoin.links, plan.references) { ref in linkRow(ref, plan: plan) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: CicadaTheme.scaled(420))
        if plan.suggested, plan.sentences.allSatisfy({ !$0.suggested }) {
            Text(Copy.PageJoin.splitSuggestNone).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder
    private func group<Item: Identifiable, Row: View>(_ title: String, _ items: [Item],
                                                       @ViewBuilder row: @escaping (Item) -> Row) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                SectionLabel(title)
                ForEach(items) { row($0) }
            }
        }
    }

    private func check(_ text: String, detail: String?, on: Binding<Bool>) -> some View {
        Toggle(isOn: on) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(1)) {
                Text(text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                if let detail, !detail.isEmpty {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .toggleStyle(.checkbox)
    }

    /// A link: which page it means — what its evidence says as conversations are ticked, until the person says.
    private func linkRow(_ ref: SplitPlan.Reference, plan: SplitPlan) -> some View {
        let shown = selection.choice(for: ref, plan: plan)
        return HStack(spacing: CicadaTheme.spacingSM) {
            Text(ref.name).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            if !ref.episodes.isEmpty {
                Text(Copy.PageJoin.linkRests(ref.episodes.count)).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Picker("", selection: Binding(get: { shown }, set: { selection.references[ref.pageId] = $0 })) {
                Text(Copy.PageJoin.linkStay).tag(SplitLinkChoice.stay)
                Text(Copy.PageJoin.linkNew).tag(SplitLinkChoice.new)
                if shown == .ask { Text(Copy.PageJoin.linkAsk).tag(SplitLinkChoice.ask) }
            }
            .labelsHidden()
            .fixedSize()
        }
    }

    private func bind<T: Hashable>(_ key: WritableKeyPath<SplitSelection, Set<T>>, _ value: T) -> Binding<Bool> {
        Binding(get: { selection[keyPath: key].contains(value) },
                set: { on in if on { selection[keyPath: key].insert(value) } else { selection[keyPath: key].remove(value) } })
    }

    private func load(suggest: Bool) async {
        if suggest { suggesting = true }
        defer { suggesting = false }
        do {
            let fresh = try await APIClient.shared.fetchSplitPlan(entityId: entity.id, suggest: suggest)
            if plan == nil {
                selection = SplitSelection.starting(from: fresh)
            } else {
                // Suggestions add ticks; what the person already ticked or unticked stays theirs.
                selection.sentences.formUnion(fresh.sentences.filter(\.suggested).map(\.n))
            }
            plan = fresh
        } catch {
            if plan == nil { failed = true } else { problem = PageJoinWords.problem(error) }
        }
    }

    private func split() {
        working = true
        problem = nil
        let chosen = selection
        Task {
            defer { working = false }
            do {
                let answer = try await APIClient.shared.splitPage(entityId: entity.id, selection: chosen)
                store.toast = Copy.PageJoin.split(chosen.name.isEmpty ? entity.name : chosen.name)
                done(answer.otherId ?? answer.entityId)
            } catch {
                problem = PageJoinWords.problem(error)
            }
        }
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
