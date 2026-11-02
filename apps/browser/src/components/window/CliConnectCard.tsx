import { View } from "react-native";
import { answerConnect, connectTitle, usePendingConnect } from "../../state/app/cliConnect";
import { useIsFocusedWindow } from "../../state/windows/hooks";
import { Button, Popover, POPOVER_MARGIN } from "../ui";
import { PromptBody } from "../site/Prompts";
import { usePromptInputGuard } from "../site/PromptParts";

const CARD_WIDTH = 300;
const CARD_TOP = 52;

export function CliConnectCard({ windowId, windowWidth }: { windowId: string; windowWidth: number }) {
  const pending = usePendingConnect();
  const front = useIsFocusedWindow(windowId);
  const guard = usePromptInputGuard(pending?.id);
  if (!pending || !front || windowWidth <= 0) return null;
  return (
    <Popover key={pending.id} width={Math.min(CARD_WIDTH, windowWidth - 2 * POPOVER_MARGIN)} top={CARD_TOP} right={POPOVER_MARGIN} modal={false}>
      <View accessibilityLabel="ardia connection request">
        <PromptBody icons={["terminal"]} title={connectTitle(pending)} message="It can open and control pages in that profile until it disconnects.">
          <Button variant="pill" title="Deny" onPress={guard(() => answerConnect(pending.id, false))} />
          <Button variant="pill" title="Allow" primary onPress={guard(() => answerConnect(pending.id, true))} />
        </PromptBody>
      </View>
    </Popover>
  );
}
