import Foundation

/// C11 (G146 plan R-PE10) — one picture write, run by `Store.perform` like every write the app sends. Its paint is
/// computed by the twin, so it is only ever what the server will answer: an upload shows its own URL at once (the bytes
/// are hashed here exactly as the server hashes them, and `PictureStore` is primed with them), "Use initials" the
/// monogram, a removal the detected rung when the surface holds the inputs — otherwise the old picture stays until the
/// answer ("painted where the answer is known", `ProjectWrite`'s rule). The answer settles the override; a failure
/// rolls it back and toasts the server's own sentence.
struct EntityPictureWrite: Mutation {
    enum Action: Equatable { case upload(PreparedPicture), useInitials, clear }

    let entityId: String
    let type: EntityType
    let bank: String
    let action: Action
    /// The rung inputs the surface holds (the card's), for a removal's paint.
    let inputs: PictureInputs?
    let store: Store
    let pictures: PictureStore
    private let previous = MutationMemo<PictureOverride>()
    private let failure = MutationMemo<any Error>()
    private let answer = MutationMemo<EntityPictureAnswer>()

    init(entityId: String, type: EntityType, bank: String, action: Action, inputs: PictureInputs?, store: Store,
         pictures: PictureStore = .shared) {
        self.entityId = entityId
        self.type = type
        self.bank = bank
        self.action = action
        self.inputs = inputs
        self.store = store
        self.pictures = pictures
    }

    var result: EntityPictureAnswer? { answer.value }

    private var key: String { Store.pictureKey(bank: bank, id: entityId) }

    var paint: PictureOverride? {
        var next = inputs ?? PictureInputs(type: type.rawValue)
        switch action {
        case .upload(let picture):
            next.choice = "upload"
            next.uploadSha = picture.sha
        case .useInitials:
            next.choice = "initials"
            next.uploadSha = nil
        case .clear:
            guard inputs != nil else { return nil }
            next.choice = nil
            next.uploadSha = nil
        }
        return PictureOverride(picture: EntityPictureResolver.resolve(id: entityId, next), inputs: next, at: .distantFuture)
    }

    func optimistic(_ store: Store) async {
        previous.value = store.pictureOverrides[key]
        guard let paint else { return }
        if case .upload(let picture) = action, let url = paint.picture?.url {
            await pictures.prime(.api(path: url), bank: bank, data: picture.data)
        }
        store.pictureOverrides[key] = paint
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            let reply: EntityPictureAnswer
            switch action {
            case .upload(let picture): reply = try await api.setEntityPicture(entityId: entityId, data: picture.data,
                                                                              ext: picture.ext)
            case .useInitials: reply = try await api.useEntityInitials(entityId: entityId)
            case .clear: reply = try await api.clearEntityPicture(entityId: entityId)
            }
            answer.value = reply
            store.pictureOverrides[key] = PictureOverride(picture: reply.ref, inputs: reply.pictureInputs ?? paint?.inputs,
                                                          at: Date())
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        store.pictureOverrides[key] = previous.value
    }

    var failureMessage: String { PictureWriteFailure.message(failure.value) }

    /// The graph carries the picture from here; the override yields to it once they agree (`Store.pictureOverride`).
    var refreshDomains: Set<SyncDomain> { [.graph] }
}

/// A failed picture write in the person's words: the server's own sentence for 400 / 409 / 413 (`entity_picture`'s
/// messages are written for them); every other failure this page's words — a 404's detail names ids (DR-54).
enum PictureWriteFailure {
    static func message(_ error: (any Error)?) -> String {
        guard let api = error as? APIError else { return Copy.People.saveFailed }
        switch api {
        case .httpError(let code, let body) where [400, 409, 413].contains(code):
            return ProjectWriteFailure.detail(body) ?? (code == 409 ? Copy.People.sleepBusy : Copy.People.saveFailed)
        case .serverUnreachable:
            return Copy.People.backendDown
        default:
            return Copy.People.saveFailed
        }
    }
}
