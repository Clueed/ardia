import Foundation

struct GatewayConnect {
  enum State {
    case pending
    case allowed
    case denied
  }

  let agent: String
  let profileId: String?
  let newName: String?
  let created = Date()
  var state = State.pending
  var settledAt: Date?
  var session: GatewaySession?
}
