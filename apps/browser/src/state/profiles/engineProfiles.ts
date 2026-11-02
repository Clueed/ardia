import type { BrowserState } from "../browser/store";
import { engineProfile, isIncognitoProfile } from "../browser/model";
import { isAgentProfile } from "../browser/agents";

export const engineProfiles = (s: Pick<BrowserState, "profiles">) =>
  [...new Set(Object.keys(s.profiles).filter((id) => !isIncognitoProfile(id) && !isAgentProfile(s, id)).map((id) => engineProfile(s, id)))];
