import SwiftUI

/// State art, never a loop: the Mac's civil time chooses whole-pixel hand angles.
enum RoomClockReading {
    struct Indices: Equatable { let hour, minute, second: Int }
    struct Layer: Equatable { let tag: String; let index: Int }

    static func indices(at date: Date, zone: TimeZone) -> Indices {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let parts = calendar.dateComponents([.hour, .minute, .second], from: date)
        let hour = parts.hour ?? 0, minute = parts.minute ?? 0
        return .init(hour: (hour % 12) * 5 + minute / 12, minute: minute, second: parts.second ?? 0)
    }

    static func layers(at date: Date, zone: TimeZone, lighting: RoomLighting, reduceMotion: Bool) -> [Layer] {
        let indices = indices(at: date, zone: zone), suffix = lighting == .dark ? "-night" : ""
        var result: [Layer] = [.init(tag: "face" + suffix, index: 0), .init(tag: "hour" + suffix, index: indices.hour),
                               .init(tag: "minute" + suffix, index: indices.minute)]
        if !reduceMotion { result.append(.init(tag: "second" + suffix, index: indices.second)) }
        return result
    }

    static func label(at date: Date, zone: TimeZone, locale: Locale = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = locale; formatter.timeZone = zone
        formatter.dateStyle = .none; formatter.timeStyle = .short
        return "Wall clock, " + formatter.string(from: date)
    }
}

/// Its own timeline redraws only this leaf; leaving/occluding the room tears the timeline down.
struct RoomClock: View {
    let lighting: RoomLighting
    let cell: CGFloat
    var onScreen = true
    @Environment(\.scenePaused) private var hostPaused
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.spriteSnapshotDate) private var snapshotDate
    @State private var windowVisible = false

    var body: some View {
        Group {
            if snapshotDate == nil && onScreen && windowVisible && !hostPaused {
                TimelineView(.periodic(from: Date(), by: CicadaMotion.roomClockTick)) { context in
                    reading(at: context.date)
                }
            } else { reading(at: snapshotDate ?? Date()) }
        }
        .background { if snapshotDate == nil { WindowVisibilityReader { windowVisible = $0 } } }
        .accessibilitySortPriority(RoomA11yOrder.clock)
    }

    private func reading(at date: Date) -> some View {
        let sheet = SpriteSheets.sheet(named: "room-clock")
        let size = DeskScene.plan.first { $0.prop == .clock }.map { CGSize(width: $0.w, height: $0.h) } ?? .zero
        let label = RoomClockReading.label(at: date, zone: .current)
        return ZStack {
            ZStack {
                ForEach(RoomClockReading.layers(at: date, zone: .current, lighting: lighting, reduceMotion: reduceMotion), id: \.tag) { layer in
                    if let clip = sheet?.clip(layer.tag), clip.order.indices.contains(layer.index),
                       let image = sheet?.frameImage(clip.order[layer.index]) {
                        Image(decorative: image, scale: 1).resizable().interpolation(.none)
                    }
                }
            }
            .id(lighting)
            .transition(.opacity)
        }
        .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: lighting)
        .frame(width: size.width * cell, height: size.height * cell)
        .contentShape(Rectangle())
        .help(label)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
    }
}
