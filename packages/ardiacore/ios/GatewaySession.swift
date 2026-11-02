import Foundation

final class GatewaySession {
  let token: String
  let id: String
  let profileId: String
  let key: String
  let kind: String
  let agent: String
  let allowedAt = Date()
  var polled = false
  var lastActive = Date()
  var created: [String] = []
  var proxies: [GatewayProxy] = []

  init(token: String, id: String, profile: GatewayProfile, agent: String) {
    self.token = token
    self.id = id
    self.profileId = profile.id
    self.key = profile.key
    self.kind = profile.kind
    self.agent = agent
  }

  func touch() {
    lastActive = Date()
  }

  func end() {
    let open = proxies
    proxies = []
    for proxy in open { proxy.close() }
  }
}
