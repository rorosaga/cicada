import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// C11 (G146 plan R-PE4, R-PE15) — what can be done to a picture, by where it came from.
enum PictureMenuModel {
    enum Option: Hashable { case change, add, useInitials, remove, useDetected(PictureSource) }

    static func options(current: EntityPictureRef?, detected: EntityPictureRef?) -> [Option] {
        guard let current else { return [.add] }
        switch current.source {
        case .upload: return [.change, .remove]
        case .initials: return [.change] + (detected.map { [.useDetected($0.source)] } ?? [])
        case .contacts, .logo, .thumbnail: return [.change, .useInitials]
        }
    }
}

/// The picture writes as the person starts them: the image picker, a drop, a menu choice. Each ends in one
/// `EntityPictureWrite` through `Store.perform`.
@MainActor
enum PictureActions {
    /// Only a page can hold a picture: a hub or a synthetic repo node has no file to mark. `nonisolated` so a pure
    /// caller (a test, a model) can ask without the main actor.
    nonisolated static func canEdit(_ type: EntityType) -> Bool { type != .hub && type != .unknown }

    /// F-11 — "It opens an NSOpenPanel for images."
    static func change(id: String, name: String, type: EntityType, store: Store, inputs: PictureInputs?) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = Copy.People.pickMessage(name)
        panel.prompt = Copy.People.pickPrompt
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await upload(fileURL: url, id: id, type: type, store: store, inputs: inputs) }
    }

    static func upload(fileURL: URL, id: String, type: EntityType, store: Store, inputs: PictureInputs?) async {
        let prepared = await Task.detached(priority: .userInitiated) { () -> Result<PreparedPicture, PictureImport.Failure> in
            do { return .success(try PictureImport.prepare(fileURL: fileURL)) } catch {
                return .failure(error as? PictureImport.Failure ?? .unreadable)
            }
        }.value
        await send(prepared, id: id, type: type, store: store, inputs: inputs)
    }

    static func upload(data: Data, id: String, type: EntityType, store: Store, inputs: PictureInputs?) async {
        let prepared = await Task.detached(priority: .userInitiated) { () -> Result<PreparedPicture, PictureImport.Failure> in
            do { return .success(try PictureImport.prepare(data: data)) } catch {
                return .failure(error as? PictureImport.Failure ?? .unreadable)
            }
        }.value
        await send(prepared, id: id, type: type, store: store, inputs: inputs)
    }

    private static func send(_ prepared: Result<PreparedPicture, PictureImport.Failure>, id: String, type: EntityType,
                             store: Store, inputs: PictureInputs?) async {
        switch prepared {
        case .success(let picture):
            await store.perform(EntityPictureWrite(entityId: id, type: type, bank: store.bank, action: .upload(picture),
                                                   inputs: inputs, store: store))
        case .failure(let failure):
            store.toast = Copy.People.importFailed(failure)
        }
    }

    static func run(_ option: PictureMenuModel.Option, id: String, name: String, type: EntityType, store: Store,
                    inputs: PictureInputs?) {
        switch option {
        case .change, .add:
            change(id: id, name: name, type: type, store: store, inputs: inputs)
        case .useInitials:
            Task { await store.perform(EntityPictureWrite(entityId: id, type: type, bank: store.bank, action: .useInitials,
                                                          inputs: inputs, store: store)) }
        case .remove, .useDetected:
            Task { await store.perform(EntityPictureWrite(entityId: id, type: type, bank: store.bank, action: .clear,
                                                          inputs: inputs, store: store)) }
        }
    }
}

/// The right-click menu on every editable picture (R-PE15).
struct PictureMenuItems: View {
    let id: String
    let name: String
    let type: EntityType
    let held: EntityPictureRef?
    let heldInputs: PictureInputs?

    @Environment(Store.self) private var store

    var body: some View {
        let inputs = store.pictureInputs(for: id, held: heldInputs)
        let detected = inputs.flatMap { EntityPictureResolver.detected(id: id, $0) }
        ForEach(PictureMenuModel.options(current: store.picture(for: id, held: held), detected: detected), id: \.self) { option in
            Button(Copy.People.optionLabel(option)) {
                PictureActions.run(option, id: id, name: name, type: type, store: store, inputs: inputs)
            }
        }
    }
}

/// R-PE15 — the hover or drop veil: the picture dims under a camera, and the hero adds "Change…".
struct EntityPictureVeil: View {
    let showsWord: Bool
    let units: CGFloat

    var body: some View {
        ZStack {
            CicadaTheme.scrim
            VStack(spacing: CicadaTheme.scaled(2)) {
                Image(systemName: "camera")
                    .font(CicadaTheme.font(size: max(10, units * 0.24), weight: .medium))
                if showsWord {
                    Text(Copy.People.change).font(CicadaTheme.font(size: 12, weight: .medium))
                }
            }
            .foregroundStyle(CicadaTheme.onFill)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
