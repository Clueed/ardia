import ExpoModulesCore

public class GatewayModule: Module {
  public func definition() -> ModuleDefinition {
    Name(Self.calls.moduleName)
    Events(Self.calls.domain)
    Self.calls.forwardEvents(to: self)
    Self.calls.function
  }

  static let calls = CallTable(domain: "gateway", handlers: [
    "start": { _, reply in Gateway.shared.start { status in DispatchQueue.main.async { reply.ok(status) } } },
    "stop": { _, reply in Gateway.shared.stop { DispatchQueue.main.async { reply.ok() } } },
    "profiles": { args, reply in
      Gateway.shared.setProfiles(try args.dicts("profiles"))
      reply.ok()
    },
    "shownTabs": { args, reply in
      Gateway.shared.setShownTabs(try args.dict("tabs"))
      reply.ok()
    },
    "connectReply": { args, reply in
      Gateway.shared.reply(request: try args.text("request"), allow: try args.bool("allow"), profile: args.profile)
      reply.ok()
    },
    "endSessions": { args, reply in
      Gateway.shared.endSessions(profile: args.profile)
      reply.ok()
    },
    "runReply": { args, reply in
      Gateway.shared.runReply(request: try args.text("request"), result: args.values["result"], error: args.values["error"] as? [String: Any])
      reply.ok()
    },
    "activateReply": { args, reply in
      Gateway.shared.activateReply(request: try args.text("request"), error: try args.optionalText("error"))
      reply.ok()
    },
    "tabOpened": { args, reply in
      Gateway.shared.tabOpened(request: try args.text("request"), tabId: try args.optionalText("tabId"))
      reply.ok()
    },
  ])
}
