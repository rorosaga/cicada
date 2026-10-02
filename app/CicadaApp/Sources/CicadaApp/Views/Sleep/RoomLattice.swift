import CoreGraphics

/// One whole-point lattice for every room sprite (P12, TODO ruling 18).
enum RoomLattice {
    static let cols = 160
    static let rows = 64
    static func cell(uiScale: Double) -> CGFloat { max(2, (3 * uiScale).rounded()) }
}
