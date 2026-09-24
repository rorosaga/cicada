import AppKit
import XCTest
@testable import CicadaApp

/// C11 / R-PE10 — a picture write paints what is known before the server answers, settles on the answer, and rolls
/// back with the server's own sentence.
@MainActor
final class EntityPictureWriteTests: XCTestCase {
    private func setup() -> (Store, FakeSyncAPI, PictureStore) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        store.bank = "work"
        let pictures = PictureStore(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)) { _ in nil }
        return (store, api, pictures)
    }

    private func picture() throws -> PreparedPicture {
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 64, pixelsHigh: 64, bitsPerSample: 8,
                                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        return PreparedPicture(data: try XCTUnwrap(rep.representation(using: .png, properties: [:])), ext: "png",
                               width: 64, height: 64)
    }

    private let key = Store.pictureKey(bank: "work", id: "bob-example")

    func testAnUploadPaintsItsOwnURLAtOnceAndTheAnswerSettlesIt() async throws {
        let (store, api, pictures) = setup()
        let p = try picture()
        let url = "/entities/bob-example/picture?v=\(p.sha)"
        api.pictureAnswer = EntityPictureAnswer(entityId: "bob-example", picture: url, pictureSource: "upload",
                                                pictureInputs: PictureInputs(type: "person", choice: "upload", uploadSha: p.sha))
        api.gateWrites = true
        let write = EntityPictureWrite(entityId: "bob-example", type: .person, bank: "work", action: .upload(p),
                                       inputs: nil, store: store, pictures: pictures)
        let task = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        XCTAssertEqual(store.picture(for: "bob-example"), EntityPictureRef(url: url, source: .upload))
        let primed = await pictures.image(.api(path: url), bank: "work")
        XCTAssertNotNil(primed, "the chosen bytes are in the cache under the URL the server will answer")
        api.releaseWriteGate()
        let landed = await task.value
        XCTAssertTrue(landed)
        XCTAssertEqual(api.writes.last, "setEntityPicture:bob-example:png:\(p.data.count)")
        XCTAssertNotEqual(store.pictureOverrides[key]?.at, .distantFuture, "settled on the answer")
        XCTAssertEqual(store.pictureInputs(for: "bob-example", held: nil)?.choice, "upload")
    }

    func testAFailedWriteRollsBackAndSaysTheServersSentence() async throws {
        let (store, api, pictures) = setup()
        api.pictureError = APIError.httpError(409, #"{"detail":"Sleep is updating your memory — try the picture again in a moment."}"#)
        let landed = await store.perform(EntityPictureWrite(entityId: "bob-example", type: .person, bank: "work",
                                                            action: .useInitials, inputs: nil, store: store,
                                                            pictures: pictures))
        XCTAssertFalse(landed)
        XCTAssertNil(store.pictureOverrides[key])
        XCTAssertEqual(store.toast, "Sleep is updating your memory — try the picture again in a moment.")
    }

    func testARemovalPaintsTheDetectedRungOnlyWhenTheInputsAreInHand() async throws {
        let (store, api, pictures) = setup()
        api.gateWrites = true
        let inputs = PictureInputs(type: "company", choice: "upload", uploadSha: "3f9a1c0b2d4e", logo: true)
        let known = Task {
            await store.perform(EntityPictureWrite(entityId: "acme-example", type: .company, bank: "work", action: .clear,
                                                   inputs: inputs, store: store, pictures: pictures))
        }
        await api.waitForParkedWrite()
        XCTAssertEqual(store.picture(for: "acme-example"), EntityPictureRef(url: "/entities/acme-example/logo", source: .logo))
        api.releaseWriteGate()
        _ = await known.value
        let unknown = Task {
            await store.perform(EntityPictureWrite(entityId: "globex-example", type: .company, bank: "work", action: .clear,
                                                   inputs: nil, store: store, pictures: pictures))
        }
        await api.waitForParkedWrite()
        XCTAssertNil(store.pictureOverrides[Store.pictureKey(bank: "work", id: "globex-example")],
                     "nothing is painted where the answer is not known")
        api.releaseWriteGate()
        _ = await unknown.value
    }

    func testAFailedPictureWriteSpeaksThePersonsWords() {
        XCTAssertEqual(PictureWriteFailure.message(APIError.httpError(413, #"{"detail":"That picture is too large — Cicada keeps pictures under 512 KB."}"#)),
                       "That picture is too large — Cicada keeps pictures under 512 KB.")
        XCTAssertEqual(PictureWriteFailure.message(APIError.httpError(404, #"{"detail":"Entity bob-example not found"}"#)),
                       Copy.People.saveFailed, "a 404's detail names ids (DR-54)")
        XCTAssertEqual(PictureWriteFailure.message(APIError.serverUnreachable), Copy.People.backendDown)
        XCTAssertEqual(PictureWriteFailure.message(nil), Copy.People.saveFailed)
    }
}
